"""Per-request context (request id, client ip) available to services such as the audit log."""

import contextvars
import uuid

import structlog
from starlette.types import ASGIApp, Receive, Scope, Send

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
client_ip_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("client_ip", default=None)


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        request_id = headers.get(b"x-request-id", b"").decode() or uuid.uuid4().hex
        forwarded = headers.get(b"x-forwarded-for", b"").decode().split(",")[0].strip()
        client = scope.get("client")
        ip = forwarded or (client[0] if client else None)

        rid_token = request_id_var.set(request_id)
        ip_token = client_ip_var.set(ip)
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_with_id(message: dict) -> None:  # type: ignore[type-arg]
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
            request_id_var.reset(rid_token)
            client_ip_var.reset(ip_token)
