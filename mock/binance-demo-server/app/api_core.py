"""Router loi core: ping, time, healthz, trang debug."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from . import state
from .debug_page import HTML

router = APIRouter()


@router.get("/fapi/v1/ping")
async def ping() -> dict:
    return {}


@router.get("/fapi/v1/time")
async def server_time() -> dict:
    return {"serverTime": state.now_ms()}


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "uptime_s": state.uptime_s()}


@router.get("/_debug", response_class=HTMLResponse)
async def debug_page() -> str:
    return HTML


@router.get("/_debug/json")
async def debug_json() -> dict:
    return state.snapshot()


@router.get("/")
async def index() -> HTMLResponse:
    return HTMLResponse(
        '<meta charset="utf-8"><body style="font:13px monospace;background:#0f1115;color:#dfe4ec;padding:24px">'
        "<h3>Mock Binance USDⓈ-M Futures</h3>"
        '<p>Trang trạng thái: <a style="color:#58a6ff" href="/_debug">/_debug</a></p>'
        "<p>REST: /fapi/v1/* · WS: /ws/&lt;listenKey&gt;</p></body>"
    )
