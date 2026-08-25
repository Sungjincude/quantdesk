"""Walk-forward backtests for the two core strategies, with explicit costs.
No lookahead: every decision at bar t uses data up to t only."""
import numpy as np
import pandas as pd

from ..engines.cointegration import kalman_hedge, zscore


def _costs(fee_pct: float, slippage_pct: float) -> float:
    """Round-trip cost as fraction of notional (entry + exit legs)."""
    return 2 * (fee_pct + slippage_pct) / 100.0


def backtest_pairs(y_close: pd.Series, x_close: pd.Series,
                   entry_z: float = 2.0, exit_z: float = 0.5,
                   z_window: int = 60, stop_z: float = 3.5,
                   fee_pct: float = 0.10, slippage_pct: float = 0.05,
                   warmup: int = 150) -> dict:
    """Walk-forward pairs trade on the Kalman spread. At each day t>warmup:
    update hedge with data through t, compute z, enter/exit/stop.
    P&L in spread units scaled by beta => approximately market-neutral %."""
    df = pd.concat([y_close.rename("y"), x_close.rename("x")], axis=1).dropna()
    yv, xv = df["y"].values, df["x"].values
    n = len(df)
    if n < warmup + 50:
        return {"error": f"not enough common history ({n} bars)"}

    # precompute full-sample Kalman path but only USE values <= t (no peeking)
    kf = kalman_hedge(df["y"], df["x"])
    a_all, b_all = kf["alpha"].values, kf["beta"].values
    spreads = pd.Series(yv - (a_all + b_all * xv), index=df.index)

    cost = _costs(fee_pct, slippage_pct)
    trades, pos = [], None   # pos: {'dir': +-1, 'entry_px_spread', 'beta'}
    equity = [0.0]

    for t in range(warmup, n):
        s_now = float(spreads.iloc[t])
        _, z_hist_series = zscore(spreads.iloc[max(0, t - z_window - 1):t + 1],
                                  z_window)
        z = float(z_hist_series.iloc[-1])

        if pos is not None:
            # mark-to-market on spread move
            mtm = pos["dir"] * (s_now - pos["entry_s"]) / max(pos["beta"], 1e-9)
            z_entry_signed = pos["dir"] * pos["entry_z"]
            exit_reason = None
            if (pos["dir"] == 1 and z <= exit_z) or \
               (pos["dir"] == -1 and z >= -exit_z):
                exit_reason = "z_target"
            elif abs(z) >= stop_z and np.sign(z) == np.sign(pos["dir"]):
                exit_reason = "stop"
            if exit_reason:
                pnl = mtm - cost * 2          # round trip on both legs approx
                trades.append({**pos, "exit_idx": t, "pnl_pct": round(pnl, 4),
                               "exit_reason": exit_reason})
                equity.append(equity[-1] + pnl)
                pos = None
        else:
            if z >= entry_z:
                pos = {"dir": -1, "entry_s": s_now, "entry_z": z,
                       "beta": float(b_all[t]), "entry_idx": t}
            elif z <= -entry_z:
                pos = {"dir": 1, "entry_s": s_now, "entry_z": z,
                       "beta": float(b_all[t]), "entry_idx": t}

    closed = trades
    wins = [tr for tr in closed if tr["pnl_pct"] > 0]
    pnls = np.array([tr["pnl_pct"] for tr in closed]) if closed else np.array([])
    eq = np.array(equity[1:]) if len(equity) > 1 else np.array([0.0])
    dd = float((np.maximum.accumulate(eq) - eq).max()) if len(eq) else 0.0
    return {
        "n_trades": len(closed),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else None,
        "avg_pnl_pct": round(float(pnls.mean()), 3) if len(pnls) else None,
        "total_return_pct": round(float(eq[-1]) * 100, 2),
        "max_drawdown_pct": round(dd * 100, 2),
        "per_trade_cost_drag_pct": round(cost * 200, 3),
        "trades_tail": [
            {k: tr[k] for k in ("dir", "entry_idx", "exit_idx",
                                "pnl_pct", "exit_reason")}
            for tr in closed[-5:]
        ],
    }


def backtest_breakout(close: pd.Series, high=None, low=None,
                      lookback: int = 20, hold: int = 10,
                      fee_pct: float = 0.10, slippage_pct: float = 0.05,
                      atr_mult: float = 2.0) -> dict:
    """Classic Donchian breakout with ATR stop, fixed horizon exit.
    Long-only swing baseline the MC suggestions can be compared against.
    Uses true range when high/low series supplied, else |Δclose| proxy."""
    c = close.astype(float)
    hi_n = c.shift(1).rolling(lookback).max()     # prior N-day high (no lookahead)
    if high is not None and low is not None:
        h, l = high.astype(float), low.astype(float)
        tr = pd.concat([h - l, (h - c.shift(1)).abs(),
                        (l - c.shift(1)).abs()], axis=1).max(axis=1)
    else:
        tr = c.diff().abs()
    atr = tr.rolling(14).mean()

    cost = _costs(fee_pct, slippage_pct)
    i, trades = 0, []
    idx = c.index
    while i < len(c) - hold - 1:
        px, hh, a = c.iloc[i], hi_n.iloc[i], atr.iloc[i]
        if np.isfinite(hh) and np.isfinite(a) and px > hh:
            entry_i, entry = i, float(px)
            stop = entry - atr_mult * float(a)
            exit_i = min(i + hold, len(c) - 1)
            exit_px = float(c.iloc[exit_i])
            pnl = (exit_px - entry) / entry - cost
            trades.append({"entry_i": int(i), "exit_i": int(exit_i),
                           "pnl_pct": round(pnl, 4),
                           "stopped": bool(
                               float(c.iloc[i + 1:exit_i + 1].min()) < stop)})
            i = exit_i + 1
        else:
            i += 1
    pnls = np.array([t["pnl_pct"] for t in trades])
    eq = np.cumsum(pnls) if len(pnls) else np.array([0.0])
    dd = float((np.maximum.accumulate(eq) - eq).max())
    return {
        "strategy": f"donchian{lookback}/hold{hold}",
        "n_trades": len(trades),
        "win_rate": round(float((pnls > 0).mean() * 100), 1) if len(pnls) else None,
        "avg_pnl_pct": round(float(pnls.mean()) * 100, 3) if len(pnls) else None,
        "total_return_pct": round(float(eq[-1]) * 100, 2),
        "max_drawdown_pct": round(dd * 100, 2),
        "stopped_count": sum(1 for t in trades if t["stopped"]),
    }
