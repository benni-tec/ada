import asyncio
import logging
from urllib.parse import urlsplit

import httpx
from anyio import fail_after

from ada.core.models.alerts import Alert, AlertRule, key_text
from ada.core.models.base import JsonObject
from ada.core.ports.notify import AlertNotifier

logger = logging.getLogger(__name__)


class _NotifyLogFilter(logging.Filter):
    def __init__(self) -> None:
        super().__init__()
        self.urls: set[str] = set()

    def filter(self, record: logging.LogRecord) -> bool:
        return not any(url in record.getMessage() for url in self.urls)


_notify_logs = _NotifyLogFilter()
logging.getLogger("httpx").addFilter(_notify_logs)


class HttpAlertNotifier(AlertNotifier):
    def __init__(
        self,
        client: httpx.AsyncClient,
        ntfy_url: str | None,
        webhook_url: str | None,
        public_url: str | None,
    ) -> None:
        self.client = client
        self.ntfy_url = ntfy_url
        self.webhook_url = webhook_url
        self.public_url = public_url
        self._tasks: set[asyncio.Task[None]] = set()
        for url in (ntfy_url, webhook_url):
            if url:
                _notify_logs.urls.add(url)
                try:
                    _notify_logs.urls.add(str(httpx.URL(url)))
                except httpx.InvalidURL:
                    pass

    @property
    def configured(self) -> bool:
        return bool(self.ntfy_url or self.webhook_url)

    async def firing(self, rule: AlertRule, alert: Alert, rows: list[JsonObject]) -> None:
        # The after-commit hook must return without waiting for network delivery.
        task = asyncio.create_task(self._deliver(rule, alert, rows))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Wait for deliveries still in flight; each is already capped at five seconds."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _deliver(self, rule: AlertRule, alert: Alert, rows: list[JsonObject]) -> None:
        try:
            with fail_after(5):
                await self._send(rule, alert, rows)
        except Exception as error:
            logger.warning("Alert delivery failed: %s", type(error).__name__)

    async def _send(self, rule: AlertRule, alert: Alert, rows: list[JsonObject]) -> None:
        deliveries = []
        project_url = (
            f"{self.public_url.rstrip('/')}/projects/{alert.project_id}/alerts"
            if self.public_url
            else None
        )
        if self.ntfy_url:
            # HTTP headers must be ASCII and cannot contain line breaks.
            title = (
                rule.name.encode("ascii", "replace").decode().replace("\r", " ").replace("\n", " ")
            )
            headers = {"Title": title[:200], "Tags": "rotating_light", "Priority": "high"}
            if project_url:
                headers["Click"] = project_url
            detail = "\n\n".join(
                "\n".join(f"{column}: {value}" for column, value in row.items()) for row in rows
            )
            body = (
                f"{key_text(alert.key)[:200]}\nStarted: {alert.started_at.isoformat()}\n\n{detail}"
            )
            deliveries.append(
                self._post(
                    self.ntfy_url,
                    content=body[:1000].encode(),
                    headers={**headers, "Content-Type": "text/plain; charset=utf-8"},
                )
            )
        if self.webhook_url:
            deliveries.append(
                self._post(
                    self.webhook_url,
                    json={
                        "event": "alert.firing",
                        "project_id": str(alert.project_id),
                        "rule_id": str(rule.id),
                        "rule_name": rule.name,
                        "alert_id": str(alert.id),
                        "key": alert.key,
                        "started_at": alert.started_at.isoformat(),
                        "rows": rows,
                        "project_url": project_url,
                    },
                )
            )
        await asyncio.gather(*deliveries)

    async def _post(
        self,
        url: str,
        *,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        json: JsonObject | None = None,
    ) -> None:
        host = "invalid"
        try:
            host = urlsplit(url).hostname or "invalid"
            response = await self.client.post(
                url, content=content, headers=headers, json=json, timeout=5
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            logger.warning("Alert delivery to %s failed: HTTP %s", host, error.response.status_code)
        except Exception as error:
            logger.warning("Alert delivery to %s failed: %s", host, type(error).__name__)
