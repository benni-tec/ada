import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import uuid7

import httpx

from ada.core.models.alerts import Alert, AlertDelivery, AlertRule, key_text
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
        email_to: str | None = None,
        record: Callable[[AlertDelivery], Awaitable[None]] | None = None,
    ) -> None:
        self.email_to = [
            address.strip() for address in (email_to or "").split(",") if address.strip()
        ]
        self.record = record
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
        return bool(self.ntfy_url or self.webhook_url or self.email_to)

    async def firing(
        self, rule: AlertRule, alert: Alert, rows: list[JsonObject], *, test: bool = False
    ) -> None:
        # The after-commit hook must return without waiting for network delivery.
        task = asyncio.create_task(self._deliver(rule, alert, rows, test=test))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Wait for in-flight deliveries; network and recording each have a five-second cap."""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _deliver(
        self, rule: AlertRule, alert: Alert, rows: list[JsonObject], *, test: bool = False
    ) -> None:
        try:
            await self._send(rule, alert, rows, test=test)
        except Exception as error:
            logger.warning("Alert delivery failed: %s", type(error).__name__)

    async def _send(
        self, rule: AlertRule, alert: Alert, rows: list[JsonObject], *, test: bool = False
    ) -> None:
        deliveries = []
        project_url = (
            f"{self.public_url.rstrip('/')}/projects/{alert.project_id}/alerts"
            if self.public_url
            else None
        )
        link = project_url or f"/projects/{alert.project_id}/alerts"
        detail = "\n\n".join(
            "\n".join(f"{column}: {value}" for column, value in row.items()) for row in rows
        )
        body = (
            f"{key_text(alert.key)}\nStarted: {alert.started_at.isoformat()}\n\n{detail}\n\n{link}"
        )
        subject = f"{'[TEST] ' if test else ''}{rule.name}"
        if self.email_to:
            logger.info("Simulated alert email for %s recipients", len(self.email_to))
            for address in self.email_to:
                deliveries.append(
                    self._record(
                        rule,
                        alert,
                        "email",
                        address,
                        "simulated",
                        test=test,
                        detail=f"Subject: {subject}\n\n{body}",
                    )
                )
        if self.ntfy_url:
            # HTTP headers must be ASCII and cannot contain line breaks.
            title = (
                subject.encode("ascii", "replace").decode().replace("\r", " ").replace("\n", " ")
            )
            headers = {"Title": title[:200], "Tags": "rotating_light", "Priority": "high"}
            if project_url:
                headers["Click"] = project_url
            deliveries.append(
                self._post(
                    self.ntfy_url,
                    rule=rule,
                    alert=alert,
                    channel="ntfy",
                    test=test,
                    content=body[:1000].encode(),
                    headers={**headers, "Content-Type": "text/plain; charset=utf-8"},
                )
            )
        if self.webhook_url:
            deliveries.append(
                self._post(
                    self.webhook_url,
                    rule=rule,
                    alert=alert,
                    channel="webhook",
                    test=test,
                    json={
                        "event": "alert.firing",
                        "test": test,
                        "project_id": str(alert.project_id),
                        "rule_id": str(rule.id),
                        "rule_name": subject,
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
        rule: AlertRule,
        alert: Alert,
        channel: str,
        test: bool,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        json: JsonObject | None = None,
    ) -> None:
        host = "invalid"
        status = "failed"
        http_status = None
        detail = None
        try:
            host = urlsplit(url).hostname or "invalid"
            async with asyncio.timeout(5):
                response = await self.client.post(
                    url, content=content, headers=headers, json=json, timeout=5
                )
            http_status = response.status_code
            response.raise_for_status()
            status = "sent"
        except httpx.HTTPStatusError as error:
            detail = f"HTTP {error.response.status_code}"
            logger.warning("Alert delivery to %s failed: HTTP %s", host, error.response.status_code)
        except Exception as error:
            detail = type(error).__name__
            logger.warning("Alert delivery to %s failed: %s", host, type(error).__name__)

        await self._record(
            rule, alert, channel, host, status, test=test, http_status=http_status, detail=detail
        )

    async def _record(
        self,
        rule: AlertRule,
        alert: Alert,
        channel: str,
        target: str,
        status: str,
        *,
        test: bool,
        http_status: int | None = None,
        detail: str | None = None,
    ) -> None:
        if self.record:
            try:
                async with asyncio.timeout(5):
                    await self.record(
                        AlertDelivery(
                            id=uuid7(),
                            alert_id=None if test else alert.id,
                            project_id=alert.project_id,
                            rule_id=rule.id,
                            test=test,
                            channel=channel,
                            target=target,
                            status=status,
                            http_status=http_status,
                            detail=detail,
                            created_at=datetime.now(UTC),
                        )
                    )
            except Exception as error:
                logger.warning("Alert delivery recording failed: %s", type(error).__name__)
