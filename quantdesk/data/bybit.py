"""Bybit v5 public market data (no API key needed for klines/tickers)."""
import time

import httpx
import pandas as pd

BASE = "https://api.bybit.com"


def _get(path: str, params: dict) -> dict:
    r = httpx.get(BASE + path, params=params, timeout=15)
    r.raise_for_status()
    j = r.json()
    if j.get("retCode") != 0:
        raise RuntimeError(f"Bybit error {j.get('retCode')}: {j.get('retMsg')}")
    return j["result"]


def fetch_klines(symbol: str, interval: str = "60", limit: int = 200) -> pd.DataFrame:
    """interval minutes: 60=1h, 240=4h, D=daily. Returns UTC-indexed OHLCV."""
    out, end = [], None
    while len(out) < limit:
        params = {"category": "spot", "symbol": symbol.upper(), "interval": interval,
                  "limit": min(1000, limit - len(out))}
        if end:
            params["end"] = end
        res = _get("/v5/market/kline", params)
        rows = res.get("list", [])
        if not rows:
            break
        out.extend(rows)
        end = int(rows[-1][0]) - 1
        if len(rows) < int(params["limit"]):
            break
        time.sleep(0.05)
    if not out:
        return pd.DataFrame()
    df = pd.DataFrame(out, columns=["ts", "open", "high", "low", "close",
                                    "volume", "turnover"])
    df[["open", "high", "low", "close", "volume"]] = \
        df[["open", "high", "low", "close", "volume"]].astype(float)
    # Bybit returns newest first; flip and index by UTC time
    df["ts"] = pd.to_datetime(df["ts"].astype("int64"), unit="ms", utc=True)
    df = df.set_index("ts").sort_index().loc[:, ["open", "high", "low", "close", "volume"]]
    return df[~df.index.duplicated(keep="last")]


def fetch_ticker(symbol: str) -> dict:
    lst = _get("/v5/market/tickers", {"category": "spot", "symbol": symbol.upper()})["list"]
    t = lst[0]
    return {"symbol": t["symbol"], "last": float(t["lastPrice"]),
            "pct_24h": float(t["price24hPcnt"]) * 100,
            "volume_usd": float(t["turnover24h"])}


def validate_symbol(symbol: str) -> bool:
    try:
        return bool(fetch_ticker(symbol))
    except Exception:
        return False
