import structlog
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from vendi_core.audit.metrics import suppressed_errors_counter
from vendi_core.errors.domain import DomainError

logger = structlog.get_logger()


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """Catches DomainError (→ proper status) and unhandled exceptions (→ 500)."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            return await call_next(request)
        except DomainError as e:
            logger.info(
                "domain_error",
                path=request.url.path,
                method=request.method,
                code=e.code,
                message=e.message,
            )
            return JSONResponse(
                status_code=e.status_code,
                content={
                    "success": False,
                    "message": e.message,
                    "code": e.code,
                    "details": e.details,
                },
            )
        except Exception as e:
            # Unhandled exception path: emit the full traceback (exc_info=True
            # ensures Sentry + stdout get the stack), bump the suppressed-
            # errors counter so ops can alert on "we're 500ing silently" even
            # when Sentry is disabled in an environment, then return the JSON
            # envelope the frontend contract expects. The counter is the only
            # piece of telemetry that survives when trace exporters are
            # misconfigured, so it has to fire unconditionally.
            suppressed_errors_counter.labels(
                component="middleware.error_handler",
                reason=type(e).__name__,
            ).inc()
            logger.error(
                "unhandled_exception",
                path=request.url.path,
                method=request.method,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True,
            )
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Internal server error", "code": "INTERNAL_ERROR"},
            )
