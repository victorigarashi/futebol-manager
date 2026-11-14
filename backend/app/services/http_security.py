"""Small, bounded single-process request safeguards; no external state service."""

from __future__ import annotations

import time
from collections.abc import Callable

from fastapi import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings
from app.services.auth import SESSION_COOKIE, identity_from_token


class RequestSecurityMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings, clock: Callable[[], float] = time.monotonic):
        self.app = app
        self.settings = settings
        self.clock = clock
        self._windows: dict[str, tuple[float, int]] = {}
        self._next_cleanup = 0.0

    def _limited(self, key: str, limit: int) -> bool:
        now = self.clock()
        if now >= self._next_cleanup:
            self._windows = {key: value for key, value in self._windows.items() if now - value[0] < 60}
            self._next_cleanup = now + 60
        started, count = self._windows.get(key, (now, 0))
        if now - started >= 60:
            started, count = now, 0
        self._windows[key] = (started, count + 1)
        if len(self._windows) > 10_000:
            self._windows.pop(next(iter(self._windows)))
        return count >= limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
        method = scope["method"]
        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = headers.get("origin")
            if origin and "*" not in self.settings.cors_origins and origin not in self.settings.cors_origins:
                await JSONResponse({"detail": "Origem não autorizada."}, status_code=403)(scope, receive, send)
                return
        ip = str((scope.get("client") or ("unknown",))[0])
        key = f"ip:{ip}"
        cookie = headers.get("cookie", "")
        token = next((part.strip().split("=", 1)[1] for part in cookie.split(";")
                      if part.strip().startswith(f"{SESSION_COOKIE}=")), None)
        if token:
            try:
                key = "guest:" + identity_from_token(token).id
            except HTTPException:
                pass
        auth_request = scope.get("path") == "/api/v1/auth/guest" and method == "POST"
        limit_key = f"auth:{ip}" if auth_request else key
        limit = self.settings.auth_limit_per_minute if auth_request else self.settings.request_limit_per_minute
        if self._limited(limit_key, limit):
            await JSONResponse({"detail": "Muitas requisições. Aguarde um minuto e tente novamente."},
                               status_code=429, headers={"Retry-After": "60"})(scope, receive, send)
            return
        if method in {"POST", "PUT", "PATCH"}:
            # Read at most the configured bound before a handler can mutate state.
            chunks: list[bytes] = []
            size = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body = message.get("body", b"")
                size += len(body)
                if size > self.settings.max_request_body_bytes:
                    await JSONResponse({"detail": "Corpo da requisição excede o limite permitido."}, status_code=413)(scope, receive, send)
                    return
                chunks.append(body)
                if not message.get("more_body", False):
                    break
            supplied = False

            async def bounded_receive() -> Message:
                nonlocal supplied
                if not supplied:
                    supplied = True
                    return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
                return await receive()
        else:
            bounded_receive = receive

        async def secure_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.extend([(b"x-content-type-options", b"nosniff"),
                                         (b"referrer-policy", b"same-origin"),
                                         (b"cache-control", b"no-store")])
                message = {**message, "headers": response_headers}
            await send(message)

        await self.app(scope, bounded_receive, secure_send)
