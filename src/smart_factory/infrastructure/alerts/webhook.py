"""Verified webhook delivery for anomaly alerts."""

import json
import ssl
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from smart_factory import __version__
from smart_factory.domain.alert import AnomalyAlert


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        return None


class WebhookAlertSink:
    """POST one idempotent JSON event without following redirects."""

    def __init__(
        self,
        url: str,
        *,
        timeout_seconds: float,
        bearer_token: str | None = None,
        ca_cert_path: str | None = None,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self._url = url
        self._timeout_seconds = timeout_seconds
        self._bearer_token = bearer_token
        if opener is None:
            context = ssl.create_default_context(
                cafile=str(Path(ca_cert_path)) if ca_cert_path is not None else None
            )
            self._opener = build_opener(
                _RejectRedirects(),
                HTTPSHandler(context=context),
            ).open
        else:
            self._opener = opener

    def send(self, alert: AnomalyAlert) -> None:
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": str(alert.event_id),
            "User-Agent": f"smart-factory-monitor/{__version__}",
        }
        if self._bearer_token is not None:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        request = Request(
            self._url,
            data=json.dumps(
                alert.model_dump(mode="json"),
                separators=(",", ":"),
            ).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with self._opener(request, timeout=self._timeout_seconds) as response:
            status = int(response.getcode())
            if not 200 <= status < 300:
                raise OSError(f"alert webhook returned HTTP {status}")
