import json
import logging
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.database import AsyncSessionLocal
from app.models.log import ApiLog

_mw_logger = logging.getLogger("app.middleware")

SKIP_PATHS = {"/docs", "/redoc", "/openapi.json", "/api/health"}

_SENSITIVE_FIELDS = {"password", "code", "token", "access_token", "refresh_token", "otp"}


def _redact(obj: object) -> object:
    """Recursively replace sensitive field values with '***'."""
    if isinstance(obj, dict):
        return {
            k: "***" if k.lower() in _SENSITIVE_FIELDS else _redact(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact(item) for item in obj]
    return obj


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in SKIP_PATHS:
            return await call_next(request)

        # Read and rebuild request body
        body_bytes = await request.body()

        async def receive():
            return {"type": "http.request", "body": body_bytes, "more_body": False}

        request = Request(request.scope, receive)

        request_body = None
        if body_bytes:
            try:
                request_body = json.loads(body_bytes)
            except Exception:
                request_body = None

        status_code = 500
        response_body = None

        try:
            response = await call_next(request)
            status_code = response.status_code

            # Read response body
            resp_bytes = b""
            async for chunk in response.body_iterator:
                resp_bytes += chunk

            try:
                response_body = json.loads(resp_bytes)
            except Exception:
                response_body = None

            response = Response(
                content=resp_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
        except Exception as exc:
            status_code = 500
            response = Response(content=b"Internal Server Error", status_code=500)
            _mw_logger.error("unhandled exception %s %s: %r", request.method, request.url.path, exc)
            raise exc
        finally:
            try:
                async with AsyncSessionLocal() as session:
                    log = ApiLog(
                        endpoint=request.url.path,
                        method=request.method,
                        status_code=status_code,
                        request_body=_redact(request_body),
                        response_body=_redact(response_body),
                    )
                    session.add(log)
                    await session.commit()
            except Exception as log_exc:
                _mw_logger.warning("failed to write api_log: %r", log_exc)

        return response
