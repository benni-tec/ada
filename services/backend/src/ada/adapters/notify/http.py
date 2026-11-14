import logging
from urllib.parse import urlsplit

import httpx
from anyio import fail_after

from ada.core.models.alerts import Alert, AlertRule, key_text
from ada.core.models.base import JsonObject
from ada.core.ports.notify import AlertNotifier

logger = logging.getLogger(__name__)


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

    @property
    def configured(self) -> bool:
        return bool(self.ntfy_url or self.webhook_url)

    async def firing(self, rule: AlertRule, alert: Alert, rows: list[JsonObject]) -> None:
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
            await self._post(
                self.ntfy_url,
                content=body[:1000].encode(),
                headers={**headers, "Content-Type": "text/plain; charset=utf-8"},
            )
        if self.webhook_url:
            await self._post(
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
            # httpx's timeout bounds each I/O operation; this also bounds total delivery.
            with fail_after(5):
                response = await self.client.post(
                    url, content=content, headers=headers, json=json, timeout=5
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as error:
            logger.warning("Alert delivery to %s failed: HTTP %s", host, error.response.status_code)
        except Exception as error:
            logger.warning("Alert delivery to %s failed: %s", host, type(error).__name__)
