"""Domain errors rendered as RFC 7807 problem+json."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"


class AppError(Exception):
    status = 400
    code = "bad_request"
    title = "Bad request"

    def __init__(self, detail: str | None = None, *, errors: list[dict[str, Any]] | None = None):
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.errors = errors or []


class Unauthorized(AppError):
    status, code, title = 401, "unauthorized", "Authentication required"


class Forbidden(AppError):
    status, code, title = 403, "forbidden", "Permission denied"


class NotFound(AppError):
    status, code, title = 404, "not_found", "Not found"


class Conflict(AppError):
    status, code, title = 409, "conflict", "Conflict"


class PreconditionFailed(AppError):
    status, code, title = 412, "stale_version", "The record was changed by someone else"


class ValidationFailed(AppError):
    status, code, title = 422, "validation_failed", "Validation failed"


class TooManyRequests(AppError):
    status, code, title = 429, "too_many_requests", "Too many requests"


def field_error(field: str, message: str, code: str = "invalid") -> dict[str, Any]:
    return {"field": field, "code": code, "message": message}


def _problem(status: int, code: str, title: str, detail: str, errors: list[dict[str, Any]]) -> JSONResponse:
    body: dict[str, Any] = {"type": code, "title": title, "status": status, "detail": detail}
    if errors:
        body["errors"] = errors
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _problem(exc.status, exc.code, exc.title, exc.detail, exc.errors)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            field_error(
                ".".join(str(p) for p in err["loc"] if p not in ("body", "query", "path")),
                err["msg"],
                err["type"],
            )
            for err in exc.errors()
        ]
        return _problem(422, "validation_failed", "Validation failed", "Request is invalid", errors)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _problem(exc.status_code, "http_error", str(exc.detail), str(exc.detail), [])
