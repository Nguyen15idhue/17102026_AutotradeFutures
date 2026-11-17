"""Router loi core: ping, time, healthz, trang debug."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from . import state
from .auth import LIMITS
from .chaos import CHAOS
from .debug_page import HTML

router = APIRouter()


@router.post("/_admin/chaos")
async def admin_chaos(body: dict) -> dict:
    return CHAOS.configure(body)


@router.post("/_admin/reset")
async def admin_reset() -> dict:
    LIMITS.reset()
    CHAOS.reset()
    return {"status": "reset"}


@router.get("/_admin/state")
async def admin_state() -> dict:
    return {"chaos": CHAOS.snapshot(), "limits": LIMITS.snapshot("127.0.0.1")}


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
    from . import account as A
    from .num import fmt
    from .store import STORE

    d = state.snapshot()
    d["account"] = {"wallet": fmt(A.wallet()), "available": fmt(A.available())}
    d["positions"] = [
        {"symbol": p["symbol"], "amt": p["positionAmt"], "entry": p["entryPrice"],
         "upnl": p["unRealizedProfit"]}
        for p in A.position_risk_view() if p["positionAmt"] != "0"
    ]
    d["orders"] = [
        {"symbol": o["symbol"], "side": o["side"], "type": o["type"],
         "qty": o["orig_qty"], "price": o["price"], "status": o["status"]}
        for o in STORE.orders(status="NEW")
    ]
    d["algo_orders"] = [
        {"symbol": a["symbol"], "type": a["type"], "trigger": a["trigger_price"],
         "status": a["status"]}
        for a in STORE.algos(status="NEW")
    ]
    d["events"] = [
        {"ts": e["ts_ms"], "text": f"[{e['kind']}] {e['text']}"}
        for e in STORE.events(10)
    ]
    return d


@router.get("/")
async def index() -> HTMLResponse:
    return HTMLResponse(
        '<meta charset="utf-8"><body style="font:13px monospace;background:#0f1115;color:#dfe4ec;padding:24px">'
        "<h3>Mock Binance USDⓈ-M Futures</h3>"
        '<p>Trang trạng thái: <a style="color:#58a6ff" href="/_debug">/_debug</a></p>'
        "<p>REST: /fapi/v1/* · WS: /ws/&lt;listenKey&gt;</p></body>"
    )
