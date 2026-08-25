"""Volatility forecasting: EWMA (RiskMetrics-style) and HAR-RV. Classical only."""
import numpy as np
import pandas as pd


def log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift(1)).dropna()


def ewma_vol(returns: pd.Series, lam: float = 0.94) -> float:
    """Next-period daily vol from exponentially weighted variance (RiskMetrics)."""
    r = returns.to_numpy(dtype=float)
    var = float(r[:50].var()) if len(r) > 50 else float(r.var())
    for x in r[-500:]:
        var = lam * var + (1 - lam) * x * x
    return float(np.sqrt(var))


def har_vol(close: pd.Series) -> tuple[float, dict]:
    """HAR-RV: regress next-day squared return on daily/weekly/monthly realized
    components, then project forward. Returns (forecast_daily_vol, coefs)."""
    r = log_returns(close)
    sq = (r ** 2).to_numpy()
    if len(sq) < 120:
        raise ValueError("need >=120 bars for HAR")
    d = pd.Series(sq)
    feats = np.column_stack([
        np.ones(len(d)),
        d.shift(1),                      # daily component
        d.shift(1).rolling(5).mean(),    # weekly
        d.shift(1).rolling(22).mean(),   # monthly
    ])
    y = sq
    mask = ~np.isnan(feats).any(axis=1)
    X, yy = feats[mask], y[mask]
    coef, *_ = np.linalg.lstsq(X, yy, rcond=None)
    last = np.array([1.0, sq[-1], sq[-5:].mean(), sq[-22:].mean()])
    fc_var = max(float(last @ coef), 1e-12)
    return float(np.sqrt(fc_var)), {
        "alpha": float(coef[0]), "b_daily": float(coef[1]),
        "b_weekly": float(coef[2]), "b_monthly": float(coef[3]),
    }


def annualize(daily_vol: float, periods_per_year: int) -> float:
    """252 for stocks/FX, 365 for crypto."""
    return daily_vol * np.sqrt(periods_per_year)


def daily_drift(close: pd.Series, lookback: int = 120,
                shrink: float = 0.5) -> float:
    """Sample mean daily log return, shrunk toward zero (drift is noisy)."""
    r = log_returns(close).to_numpy()[-lookback:]
    return float(np.mean(r) * shrink)
