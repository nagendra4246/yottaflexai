import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy.exc import SQLAlchemyError

from .api.routes import router
from .db.connection import check_database_connection
from .domain.errors import DomainError

logger = logging.getLogger(__name__)

app = FastAPI(
    title="YottaFlex AI",
    version="0.5.0",
    description="REST API for employee, leave, expense, approval, reimbursement, audit, and summary workflows.",
)
app.include_router(router)


@app.get("/health", tags=["health"], include_in_schema=False)
def health_check() -> dict[str, str]:
    try:
        connected = check_database_connection()
    except SQLAlchemyError as error:
        logger.exception("Database readiness check failed")
        raise StarletteHTTPException(
            status_code=503, detail="Database unavailable"
        ) from error
    if not connected:
        raise StarletteHTTPException(status_code=503, detail="Database unavailable")
    return {"status": "ok", "database": "connected"}


@app.exception_handler(DomainError)
async def domain_error_handler(_request: Request, error: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=jsonable_encoder(
            {
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "details": error.details,
                }
            }
        ),
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    _request: Request, error: RequestValidationError
) -> JSONResponse:
    details = [
        {
            "location": list(item["loc"]),
            "message": item["msg"],
            "type": item["type"],
        }
        for item in error.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": {"fields": details},
            }
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(
    _request: Request, error: StarletteHTTPException
) -> JSONResponse:
    message = error.detail if isinstance(error.detail, str) else "HTTP request failed"
    details = {} if isinstance(error.detail, str) else {"detail": error.detail}
    return JSONResponse(
        status_code=error.status_code,
        content=jsonable_encoder(
            {
                "error": {
                    "code": "HTTP_ERROR",
                    "message": message,
                    "details": details,
                }
            }
        ),
        headers=error.headers,
    )
