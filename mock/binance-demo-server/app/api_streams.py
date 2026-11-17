"""Endpoint user data stream (SIGNED + WS)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from . import errors as E
from .auth import signed_params
from .streams import HUB

router = APIRouter()


@router.post("/fapi/v1/listenKey")
async def create_listen_key(p: dict = Depends(signed_params)) -> dict:
    return {"listenKey": HUB.create()}


@router.put("/fapi/v1/listenKey")
async def keepalive_listen_key(p: dict = Depends(signed_params)) -> dict:
    HUB.keepalive(p.get("listenKey", ""))
    return {}


@router.delete("/fapi/v1/listenKey")
async def close_listen_key(p: dict = Depends(signed_params)) -> dict:
    HUB.close(p.get("listenKey", ""))
    return {}


async def _ws_endpoint(ws: WebSocket, listen_key: str) -> None:
    if not HUB.is_valid(listen_key):
        await ws.accept()
        await ws.send_json({"e": "error", "code": E.INVALID_LISTEN_KEY[0],
                            "msg": E.INVALID_LISTEN_KEY[1]})
        await ws.close(code=4000)
        return
    try:
        await HUB.attach(ws, listen_key)
    except WebSocketDisconnect:
        pass


@router.websocket("/ws/{listen_key}")
async def ws_user_stream(ws: WebSocket, listen_key: str) -> None:
    await _ws_endpoint(ws, listen_key)


@router.websocket("/private/ws/{listen_key}")
async def ws_user_stream_private(ws: WebSocket, listen_key: str) -> None:
    await _ws_endpoint(ws, listen_key)


@router.get("/_debug/streams")
async def debug_streams() -> dict:
    return HUB.snapshot()
