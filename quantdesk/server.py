"""QuantDesk API server. Run: .venv/bin/python -m quantdesk.server
or: .venv/bin/uvicorn quantdesk.server:app --port 8600"""
from __future__ import annotations

import datetime as dt
import os

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import config as cfgmod
from .data import bybit, store, yahoo
from .engines import montecarlo as mc
from .engines import screening
from .engines.cointegration import analyze_pair, find_pairs
from .engines.volatility import ewma_vol, har_vol, log_returns
from .backtest.walkforward import backtest_breakout, backtest_pairs

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
PPY_CRYPTO, PPY_CAL = 365, 252

app = FastAPI(title="QuantDesk", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------------ helpers

def is_crypto(symbol: str) -> bool:
    s = symbol.upper()
    return s.endswith("USDT") or s.endswith("USDC") or s.endswith("USD") \
        and "=" not in s and ":X" not in s


def is_fx(symbol: str) -> bool:
    return "=X" in symbol.upper()


def periods_per_year(symbol: str) -> int:
    return PPY_CRYPTO if is_crypto(symbol) else PPY_CAL


def fetch_ohlcv(symbol: str, limit: int = 500) -> pd.DataFrame:
    """Route to right feed, persist to SQLite, return UTC-indexed OHLCV."""
    sym = symbol.upper()
    try:
        if is_crypto(sym):
            df = bybit.fetch_klines(sym, interval="D", limit=min(limit, 1000))
        else:
            df = yahoo.fetch_daily(sym, period="2y")
    except Exception as e:
        df = store.load_ohlcv(sym, "1d", limit)
        if df.empty:
            raise HTTPException(502, f"no data for {sym}: {e}")
        return df
    store.upsert_ohlcv(sym, "1d", df)
    return df.tail(limit)


def atr(df: pd.DataFrame, period: int = 14) -> float:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(),
                    (l - c.shift(1)).abs()], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


def default_barriers(df: pd.DataFrame, side: str,
                     stop: float | None, target: float | None):
    """ATR-anchored barriers when the user doesn't supply them:
    stop = 2xATR, target = 3xATR (1.5R base)."""
    entry = float(df["close"].iloc[-1])
    a = atr(df)
    sign = 1 if side == "long" else -1
    stop = stop if stop is not None else entry - sign * 2 * a
    target = target if target is not None else entry + sign * 3 * a
    return entry, float(stop), float(target)


# ------------------------------------------------------------------- models

class AnalyzeReq(BaseModel):
    symbol: str
    side: str = "long"                 # long | short
    stop: float | None = None
    target: float | None = None
    horizon_days: int | None = None
    engine: str = "student_t"          # gbm | student_t | bootstrap


class RefreshReq(BaseModel):
    symbols: list[str] | None = None


class JournalOpen(BaseModel):
    symbol: str
    side: str
    qty: float
    entry: float
    stop: float | None = None
    target: float | None = None
    p_win: float | None = None
    ev_pct: float | None = None
    notes: str = ""


class JournalClose(BaseModel):
    exit_price: float
    notes: str = ""


# ------------------------------------------------------------------- routes

@app.get("/")
def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


@app.get("/api/config")
def get_config():
    return cfgmod.load()


class ConfigIn(BaseModel):
    bankroll: float | None = None
    kelly_fraction: float | None = None
    max_position_frac: float | None = None
    min_ev_pct: float | None = None
    fee_pct: float | None = None
    slippage_pct: float | None = None
    mc_paths: int | None = None
    horizon_days: int | None = None
    watchlist_crypto: list[str] | None = None
    watchlist_stocks: list[str] | None = None
    watchlist_fx: list[str] | None = None


@app.post("/api/config")
def set_config(c: ConfigIn):
    cur = cfgmod.load()
    updates = {k: v for k, v in c.model_dump().items() if v is not None}
    return cfgmod.save({**cur, **updates})


@app.post("/api/refresh")
def refresh(r: RefreshReq):
    cfg = cfgmod.load()
    syms = r.symbols or (cfg["watchlist_crypto"] + cfg["watchlist_stocks"]
                         + cfg["watchlist_fx"])
    out = {}
    for s in syms:
        try:
            df = fetch_ohlcv(s)
            out[s] = {"ok": True, "bars": len(df),
                      "last": float(df["close"].iloc[-1])}
        except Exception as e:
            out[s] = {"ok": False, "error": str(e)}
    return out


@app.get("/api/quote/{symbol}")
def quote(symbol: str):
    df = fetch_ohlcv(symbol, limit=400)
    r = log_returns(df["close"])
    hv, _ = har_vol(df["close"])
    return {
        "symbol": symbol.upper(), "last": float(df["close"].iloc[-1]),
        "chg_20d_pct": round(float(df["close"].iloc[-1]
                                   / df["close"].iloc[-21] - 1) * 100, 2)
        if len(df) > 21 else None,
        "vol_ewma_ann_pct": round(ewma_vol(r) * np.sqrt(
            periods_per_year(symbol)) * 100, 1),
        "vol_har_ann_pct": round(hv * np.sqrt(periods_per_year(symbol)) * 100, 1),
        "atr14": round(atr(df), 4),
        "bars": len(df),
    }


@app.post("/api/analyze")
def analyze(req: AnalyzeReq):
    cfg = cfgmod.load()
    df = fetch_ohlcv(req.symbol, limit=500)
    if len(df) < 120:
        raise HTTPException(400, f"only {len(df)} bars for {req.symbol}")
    side = req.side if req.side in ("long", "short") else "long"
    entry, stop, target = default_barriers(df, side, req.stop, req.target)

    # validate barrier geometry matches side
    if side == "long" and not (stop < entry < target):
        raise HTTPException(400, "long needs stop < entry < target")
    if side == "short" and not (target < entry < stop):
        raise HTTPException(400, "short needs target < entry < stop")

    horizon = req.horizon_days or cfg["horizon_days"]
    paths = mc.run_engine(req.engine, df["close"], horizon=horizon,
                          n_paths=cfg["mc_paths"],
                          periods_per_year=periods_per_year(req.symbol))
    barriers = mc.barrier_probs(paths, side, stop, target)
    ev_r = mc.ev_in_r(barriers, side, entry, stop, target)
    cone = mc.prob_cone(mc.run_engine(req.engine, df["close"], horizon=30,
                                      n_paths=min(cfg["mc_paths"], 4000),
                                      periods_per_year=periods_per_year(req.symbol)))
    kelly = screening.kelly_stake(
        bankroll=cfg["bankroll"], price=entry, p_win=barriers["p_target_first"],
        entry=entry, stop=stop, target=target,
        kelly_fraction=cfg["kelly_fraction"],
        max_position_frac=cfg["max_position_frac"])

    # net EV% after round-trip costs
    q = 1 if side == "long" else -1
    exp_move = (barriers["p_target_first"] * (target - entry)
                + barriers["p_stop_first"] * (stop - entry)
                + barriers["p_neither"]
                * (barriers["median_exit_if_neither"] - entry)) * q
    cost_pct = 2 * (cfg["fee_pct"] + cfg["slippage_pct"])
    ev_net_pct = exp_move / entry * 100 - cost_pct
    rr = abs(target - entry) / abs(entry - stop)

    verdict = ("TAKE" if ev_net_pct >= cfg["min_ev_pct"]
               and barriers["p_target_first"] >= barriers["p_stop_first"]
               else "WATCH" if ev_net_pct > 0 else "SKIP")

    hv, har_coef = har_vol(df["close"])
    return {
        "symbol": req.symbol.upper(), "side": side, "engine": req.engine,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "entry": round(entry, 6), "stop": round(stop, 6),
        "target": round(target, 6), "risk_reward": round(rr, 2),
        "horizon_days": horizon,
        **barriers,
        "ev_R": ev_r, "ev_net_pct": round(ev_net_pct, 2),
        "cost_roundtrip_pct": cost_pct,
        "kelly": kelly,
        "verdict": verdict,
        "cone": cone,
        "vol": {
            "ewma_daily": round(ewma_vol(log_returns(df["close"])), 5),
            "har_daily": round(hv, 5), "har_coefs": har_coef,
        },
        "price_stats": {
            "last_close": round(float(df['close'].iloc[-1]), 6),
            "dist_20d_high_pct": round(float(
                df["close"].iloc[-1] / df["close"].tail(20).max() - 1) * 100, 2),
            "rsi14": screening.screen_symbol(req.symbol.upper(), df["close"])["rsi14"]
            if screening.screen_symbol(req.symbol.upper(), df["close"]) else None,
        },
    }


@app.get("/api/screen")
def screen(universe: str = "all"):
    cfg = cfgmod.load()
    uni = {
        **{s: "crypto" for s in cfg["watchlist_crypto"]},
        **{s: "stock" for s in cfg["watchlist_stocks"]},
        **{s: "fx" for s in cfg["watchlist_fx"]},
    }
    if universe != "all":
        uni = {k: v for k, v in uni.items() if v == universe}
    closes = {}
    for s in uni:
        try:
            closes[s] = fetch_ohlcv(s)["close"]
        except Exception:
            continue
    rows = screening.screen_all(closes)
    for row in rows:
        row["market"] = uni[row["symbol"]]
    return {"rows": rows}


@app.get("/api/pairs/scan")
def pairs_scan():
    cfg = cfgmod.load()
    groups = {"crypto": cfg["watchlist_crypto"],
              "stock": cfg["watchlist_stocks"]}
    out = []
    for gname, syms in groups.items():
        closes = {}
        for s in syms:
            try:
                closes[s] = fetch_ohlcv(s)["close"]
            except Exception:
                pass
        min_corr = 0.80 if gname == "crypto" else 0.70
        for hit in find_pairs(closes, min_corr=min_corr):
            rep = analyze_pair(closes[hit["a"]], closes[hit["b"]],
                               hit["a"], hit["b"])
            if "error" not in rep:
                out.append({"group": gname, **rep})
    out.sort(key=lambda r: r["eg_pvalue"])
    return {"pairs": out}


@app.get("/api/pairs/report")
def pairs_report(a: str, b: str):
    ca, cb = fetch_ohlcv(a)["close"], fetch_ohlcv(b)["close"]
    rep = analyze_pair(ca, cb, a.upper(), b.upper())
    bt = backtest_pairs(ca, cb)
    return {**rep, "walk_forward": bt}


@app.get("/api/backtest/breakout/{symbol}")
def bt_breakout(symbol: str, lookback: int = 20, hold: int = 10):
    df = fetch_ohlcv(symbol, limit=800)
    return backtest_breakout(df["close"], high=df["high"], low=df["low"],
                             lookback=lookback, hold=hold)


@app.get("/api/journal")
def journal(open_only: bool = False):
    return {"trades": store.journal_list(open_only),
            "stats": store.journal_stats()}


@app.post("/api/journal")
def journal_open(t: JournalOpen):
    rec = t.model_dump()
    rec["opened_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return {"id": store.journal_add(rec)}


@app.post("/api/journal/{jid}/close")
def journal_close(jid: int, body: JournalClose):
    try:
        row = store.journal_close(jid, body.exit_price,
                                  dt.datetime.now(dt.timezone.utc).isoformat(),
                                  body.notes)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return row


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8600)
