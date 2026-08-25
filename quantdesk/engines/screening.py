"""Candidate screening + Kelly position sizing. Pure formulas, no ML."""
import numpy as np
import pandas as pd


# ------------------------------------------------------------- screening

def _rsi(close: pd.Series, period: int = 14) -> float:
    d = close.diff().dropna()
    up = d.clip(lower=0).ewm(alpha=1 / period).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / period).mean()
    rs = up / dn.replace(0, np.nan)
    return float((100 - 100 / (1 + rs)).iloc[-1])


def screen_symbol(symbol: str, close: pd.Series) -> dict | None:
    """Composite technical snapshot for one symbol (daily bars).
    Regime filter: SMA50 vs SMA200. Momentum: 60d log return vol-adjusted.
    Breakout: distance to 20d high."""
    c = close.dropna()
    if len(c) < 210:
        return None
    sma50 = float(c.rolling(50).mean().iloc[-1])
    sma200 = float(c.rolling(200).mean().iloc[-1])
    r = np.log(c).diff().dropna()
    mom60 = float(np.log(c.iloc[-1] / c.iloc[-61]))
    vol = float(r.tail(60).std())
    hi20 = float(c.tail(20).max())
    lo20 = float(c.tail(20).min())
    px = float(c.iloc[-1])

    trend_up = sma50 > sma200
    above_sma50 = px > sma50
    mom_score = mom60 / max(vol, 1e-9)            # risk-adjusted momentum
    brkout = (px - hi20) / hi20                   # >=0 means breaking out
    near_high = (px - hi20) / hi20

    score = (2.0 * mom_score
             + (1.0 if trend_up else -1.0)
             + (1.0 if above_sma50 else -1.0)
             + (2.0 if brkout >= 0 else 0.0)
             - 1.0 * abs(near_high) * (brkout < 0))

    return {
        "symbol": symbol, "px": round(px, 4),
        "trend": "UP" if trend_up else "DOWN",
        "above_sma50": above_sma50,
        "mom60_pct": round(mom60 * 100, 1),
        "mom_score": round(mom_score, 2),
        "vol_ann_pct": round(float(vol * np.sqrt(252) * 100), 1),
        "rsi14": round(_rsi(c), 1),
        "dist_20dhigh_pct": round(near_high * 100, 2),
        "breakout": bool(brkout >= 0),
        "score": round(score, 2),
    }


def screen_all(closes: dict[str, pd.Series]) -> list[dict]:
    rows = [r for r in (screen_symbol(k, v) for k, v in closes.items()) if r]
    rows.sort(key=lambda r: -r["score"])
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows


# ------------------------------------------------------------- Kelly sizing

def kelly_star(p_win: float, payoff_ratio: float) -> float:
    """Optimal fraction: f* = (p*b - q)/b with b = payoff ratio W/L.
    Returns raw Kelly fraction (can be negative => no bet)."""
    b = max(payoff_ratio, 1e-9)
    q = 1.0 - p_win
    return (p_win * b - q) / b


def kelly_stake(bankroll: float, price: float, p_win: float,
                entry: float, stop: float, target: float,
                kelly_fraction: float = 0.5,
                max_position_frac: float = 0.25) -> dict:
    """Fractional Kelly sizing from MC probabilities. Side inferred from
    stop/target placement. Qty capped by max_position_frac of bankroll."""
    side = "long" if target > entry else "short"
    risk_per_unit = abs(entry - stop)
    reward_per_unit = abs(target - entry)
    if risk_per_unit <= 0:
        return {"qty": 0.0, "reason": "degenerate barriers"}
    payoff = reward_per_unit / risk_per_unit
    f_raw = kelly_star(p_win, payoff)
    if f_raw <= 0:
        return {"qty": 0.0, "side": side, "kelly_raw": round(f_raw, 4),
                "payoff_ratio": round(payoff, 2),
                "reason": "negative edge at these barriers"}
    f_used = min(f_raw * kelly_fraction, max_position_frac)
    budget = bankroll * f_used
    qty = budget / price if price > 0 else 0.0
    return {
        "side": side, "kelly_raw": round(f_raw, 4),
        "kelly_used_frac": round(f_used, 4),
        "budget": round(budget, 2), "qty": round(qty, 6),
        "risk_amount": round(qty * risk_per_unit, 2),
        "payoff_ratio": round(payoff, 2),
    }
