"""Tek biçimli hata yanıtı: ``{"code": "...", "detail": "..."}``.

``code`` makine tarafından okunur (arayüz buna göre davranır: ör. ``reauth_required`` gelince
yeniden doğrulama penceresi açar); ``detail`` kullanıcıya gösterilecek Türkçe metindir.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """``commit=True``: hata yanıtına rağmen işlem kaydedilir (ör. başarısız giriş denetim kaydı,
    MFA deneme sayacı). Varsayılan: işlem geri alınır."""

    def __init__(self, status: int, code: str, detail: str, *, commit: bool = False) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.commit = commit


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status, content={"code": exc.code, "detail": exc.detail}
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"loc": [str(p) for p in err.get("loc", ())][1:], "msg": err.get("msg", "")}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"code": "validation_error", "detail": "Geçersiz istek", "fields": fields},
        )


def unauthorized() -> ApiError:
    return ApiError(401, "unauthenticated", "Oturum açmanız gerekiyor")


def forbidden(detail: str = "Bu işlem için yetkiniz yok") -> ApiError:
    return ApiError(403, "forbidden", detail)


def rate_limited() -> ApiError:
    return ApiError(429, "rate_limited", "Çok fazla deneme. Lütfen biraz sonra tekrar deneyin")
