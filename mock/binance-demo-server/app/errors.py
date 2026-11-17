"""Bang ma loi Binance + exception dung chung.

Chi liet ke cac ma ma mock thuc su sinh ra (xem docs/phase0 §3).
"""
from __future__ import annotations


class BinanceError(Exception):
    """Loi tra ve theo dung dinh dang {"code": int, "msg": str}."""

    def __init__(self, code: int, msg: str, http_status: int = 400) -> None:
        super().__init__(msg)
        self.code = code
        self.msg = msg
        self.http_status = http_status

    def payload(self) -> dict:
        return {"code": self.code, "msg": self.msg}


# --- param / request ---
MANDATORY_PARAM_MISSING = (-1102, "Mandatory parameter '{p}' was not sent, was empty/null, or malformed.")
EMPTY_PARAM = (-1105, "Parameter '{p}' was empty.")
UNSUPPORTED_PARAM = (-1106, "Param '{p}' was not sent, was empty/null, or malformed.")
ILLEGAL_CHARS = (-1100, "Illegal characters found in parameter '{p}'.")
PRECISION_OVER_MAX = (-1111, "Precision is over the maximum defined for this asset.")
INVALID_SYMBOL = (-1121, "Invalid symbol.")
INVALID_PARAM = (-1130, "Data sent for parameter '{p}' is not valid.")

# --- auth ---
INVALID_API_KEY = (-2014, "API-key format invalid.")
INVALID_KEY_IP_PERM = (-2015, "Invalid API-key, IP, or permissions for action.")
BAD_SIGNATURE = (-1022, "Signature for this request is not valid.")
TIMESTAMP_OUT_OF_WINDOW = (-1021, "Timestamp for this request was 1000ms ahead of the server's time.")
NO_SIGNATURE = (-1102, "Mandatory parameter 'signature' was not sent.")

# --- order ---
NEW_ORDER_REJECTED = (-2010, "Order rejected.")
CANCEL_REJECTED = (-2011, "Unknown order sent.")
ORDER_NOT_FOUND = (-2013, "Order does not exist.")
BALANCE_INSUFFICIENT = (-2018, "Balance is insufficient.")
MARGIN_INSUFFICIENT = (-2019, "Margin is insufficient.")
WOULD_IMMEDIATELY_TRIGGER = (-2020, "Order would immediately trigger.")
REDUCE_ONLY_REJECT = (-2021, "ReduceOnly Order is rejected.")
PRICE_FILTER_FAIL = (-4014, "Price not increased by tick size.")
QTY_FILTER_FAIL = (-4023, "Quantity less than or equal to zero.")
MIN_NOTIONAL_FAIL = (-4164, "Order's notional must be no smaller than {n} (unless you choose reduce only).")
POST_ONLY_WOULD_TAKE = (-5022, "Due to the order could not be executed as maker, the post-only order will be canceled.")
STOP_ORDER_SWITCH_ALGO = (-4120, "Order type not supported for this endpoint. Please use the Algo Order API endpoints instead.")
POSITION_SIDE_INVALID = (-4061, "Order's position side does not match user's setting.")

# --- algo ---
ALGO_NOT_FOUND = (-2013, "Algo order does not exist.")
CLOSE_POSITION_WITH_QTY = (-1106, "Parameter 'quantity' is not allowed with closePosition=true.")

# --- user stream ---
INVALID_LISTEN_KEY = (-1125, "This listenKey does not exist.")

# --- rate limit ---
TOO_MANY_REQUESTS = (-1003, "Too many requests.")
REQUEST_THROTTLED = (-1008, "Request throttled by system-level protection. Reduce-only/close-position orders are exempt. Please try again.")


def err(tpl: tuple, **kw) -> BinanceError:
    code, msg = tpl
    try:
        msg = msg.format(**kw) if kw else msg
    except KeyError:
        pass
    return BinanceError(code, msg)
