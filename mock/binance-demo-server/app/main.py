"""Diem vao FastAPI cua mock Binance USDⓈ-M Futures."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api_account import router as account_router
from .api_core import router as core_router
from .api_market import router as market_router
from .api_order import router as order_router
from .auth import LIMITS, is_order_route, weight_for
from .config import CFG
from .errors import BinanceError
from .market import MARKET
from .orders import ENGINE
from .store import STORE

logging.basicConfig(
    level=getattr(logging, CFG.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("mock")

_PUBLIC = ("/_debug", "/healthz", "/")


def _rate_headers(ip: str, used: int) -> dict[str, str]:
    return {
        "X-MBX-USED-WEIGHT-1M": str(used),
        "X-MBX-ORDER-COUNT-10S": str(LIMITS.used_orders_10s(ip)),
        "X-MBX-ORDER-COUNT-1M": str(LIMITS.used_orders_1m(ip)),
    }


def create_app() -> FastAPI:
    app = FastAPI(
        title="Mock Binance USDM Futures",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(BinanceError)
    async def _binance_error(_: Request, exc: BinanceError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=exc.payload())

    @app.middleware("http")
    async def _limits(request: Request, call_next):
        path = request.url.path
        if path in _PUBLIC or path.startswith("/_debug"):
            return await call_next(request)

        ip = request.client.host if request.client else "0.0.0.0"

        if LIMITS.is_banned(ip):
            resp = JSONResponse(
                status_code=418,
                content={"code": -1003, "msg": "Way too many requests; IP banned until further notice."},
            )
            for k, v in _rate_headers(ip, LIMITS.used_weight(ip)).items():
                resp.headers[k] = v
            return resp

        used, over = LIMITS.hit(ip, weight_for(request.method, path))
        if over:
            banned = LIMITS.register_429(ip)
            status = 418 if banned else 429
            msg = ("Way too many requests; IP banned until further notice."
                   if banned else "Too many requests.")
            resp = JSONResponse(status_code=status, content={"code": -1003, "msg": msg})
            resp.headers["Retry-After"] = "1"
            for k, v in _rate_headers(ip, used).items():
                resp.headers[k] = v
            return resp

        if is_order_route(request.method, path):
            _, _, orders_over = LIMITS.hit_order(ip)
            if orders_over:
                resp = JSONResponse(status_code=429, content={
                    "code": -1003, "msg": "Too many orders."})
                resp.headers["Retry-After"] = "10"
                for k, v in _rate_headers(ip, used).items():
                    resp.headers[k] = v
                return resp

        response = await call_next(request)
        for k, v in _rate_headers(ip, used).items():
            response.headers[k] = v
        return response

    app.include_router(core_router)
    app.include_router(market_router)
    app.include_router(account_router)
    app.include_router(order_router)

    async def _engine_loop() -> None:
        import asyncio
        while True:
            try:
                ENGINE.tick()
            except Exception:  # pragma: no cover
                log.exception("engine tick loi")
            await asyncio.sleep(1.0)

    @app.on_event("startup")
    async def _startup() -> None:
        MARKET.boot()
        STORE.init(CFG.db_path, CFG.initial_balance)
        import asyncio
        app.state.engine_task = asyncio.create_task(_engine_loop())
        log.info(
            "mock started market_mode=%s speed=%s balance=%s auth_strict=%s symbols=%d db=%s",
            CFG.market_mode, CFG.speed, CFG.initial_balance, CFG.auth_strict,
            len(MARKET.symbols()), CFG.db_path,
        )

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        task = getattr(app.state, "engine_task", None)
        if task:
            task.cancel()

    return app


app = create_app()
