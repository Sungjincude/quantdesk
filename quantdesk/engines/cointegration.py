"""Pairs/cointegration engine: Engle-Granger, Johansen, Kalman-filtered dynamic
hedge ratio, spread z-scores, Ornstein-Uhlenbeck half-life. Classical only."""
import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller, coint
from statsmodels.tsa.vector_ar.vecm import coint_johansen


def engle_granger(y: pd.Series, x: pd.Series) -> dict:
    """Step 1: static OLS hedge. Step 2: ADF on residuals (EG two-step).
    p<0.05 => evidence the pair is cointegrated."""
    X = sm.add_constant(x.values)
    ols = sm.OLS(y.values, X).fit()
    alpha, beta = float(ols.params[0]), float(ols.params[1])
    resid = pd.Series(y.values - (alpha + beta * x.values), index=y.index)
    tstat, pval, crit = coint(y, x)
    return {"eg_pvalue": round(float(pval), 4),
            "eg_tstat": round(float(tstat), 3),
            "crit_5pct": round(float(crit[1]), 3),
            "alpha": round(alpha, 6), "beta": round(beta, 5),
            "adf_pvalue_resid": round(float(adfuller(resid)[1]), 4)}


def johansen_rank(df: pd.DataFrame) -> dict:
    """Johansen trace test; returns number of cointegrating relations at 5%."""
    try:
        res = coint_johansen(df.dropna(), det_order=0, k_ar_diff=1)
        trace_stats = res.lr1
        trace_crit = res.cvt[:, 1]          # 5% critical values
        rank = int(np.sum(trace_stats > trace_crit))
        return {"johansen_rank_5pct": rank,
                "trace_stats": trace_stats.round(2).tolist(),
                "trace_crit_5pct": trace_crit.round(2).tolist()}
    except Exception as e:
        return {"johansen_error": str(e)}


def kalman_hedge(y: pd.Series, x: pd.Series, delta: float = 1e-5) -> pd.DataFrame:
    """Recursive least squares (Kalman filter) for time-varying y=a+b*x.
    Standard pairs-trading formulation; delta controls adaptation speed."""
    obs = np.column_stack([np.ones(len(x)), x.values])
    yv = y.values
    theta = np.zeros(2)
    R = np.eye(2)
    out = np.empty((len(yv), 2))
    for t in range(len(yv)):
        H = obs[t]
        pred_var = H @ R @ H
        K = (R @ H) / (pred_var + 1.0)      # measurement noise var = 1
        theta = theta + K * (yv[t] - H @ theta)
        R = R - np.outer(K, H @ R) + (delta / (1 - delta)) * np.eye(2)
        out[t] = theta
    return pd.DataFrame(out, index=y.index, columns=["alpha", "beta"])


def half_life(spread: pd.Series) -> float:
    """OU mean-reversion half-life in bars: regress ds on lag(s)."""
    s = spread.values
    lag, ds = s[:-1], np.diff(s)
    coef = float(np.polyfit(lag, ds, 1)[0])
    if coef >= 0:
        return float("inf")
    return float(-np.log(2) / coef)


def zscore(spread: pd.Series, window: int = 60) -> tuple[float, pd.Series]:
    m = spread.rolling(window).mean()
    sd = spread.rolling(window).std()
    z = (spread - m) / sd
    return float(z.iloc[-1]), z


def analyze_pair(y_close: pd.Series, x_close: pd.Series,
                 y_name: str = "", x_name: str = "",
                 z_window: int = 60) -> dict:
    """Full pair report: alignment, EG, Johansen, Kalman beta, spread state."""
    df = pd.concat([y_close.rename("y"), x_close.rename("x")], axis=1).dropna()
    if len(df) < 250:
        return {"error": f"only {len(df)} common bars; need >=250",
                "y": y_name, "x": x_name}
    y, x = df["y"], df["x"]

    eg = engle_granger(y, x)
    jo = johansen_rank(df)
    kf = kalman_hedge(y, x)
    spread_static = y - (eg["alpha"] + eg["beta"] * x)
    spread_kalman = y - (kf["alpha"] + kf["beta"] * x)

    z_stat, _ = zscore(spread_static, z_window)
    z_kal, z_series_k = zscore(spread_kalman, z_window)
    hl = half_life(spread_kalman)

    corr = float(np.log(y).diff().corr(np.log(x).diff()))
    verdict = "TRADEABLE"
    reasons = []
    if eg["eg_pvalue"] >= 0.10:
        verdict = "REJECT"; reasons.append("EG p>=0.10")
    if not (0.5 <= hl <= 60):
        verdict = "REJECT"; reasons.append(f"half-life {hl:.1f}d outside 0.5-60")
    if abs(z_kal) < 1.8:
        reasons = reasons or [f"|z|={abs(z_kal):.2f} below 1.8 entry"]
        if verdict == "TRADEABLE":
            verdict = "WAIT"
    return {
        "y": y_name or "asset_y", "x": x_name or "asset_x",
        "n_bars": len(df), "log_ret_corr": round(corr, 3),
        **eg, **jo,
        "kalman_beta_now": round(float(kf['beta'].iloc[-1]), 5),
        "kalman_beta_min": round(float(kf['beta'].min()), 5),
        "kalman_beta_max": round(float(kf['beta'].max()), 5),
        "half_life_days": round(hl, 1) if np.isfinite(hl) else None,
        "z_static": round(z_stat, 2), "z_kalman": round(z_kal, 2),
        "z_percentile": round(float((z_series_k < z_kal).mean() * 100), 1),
        "verdict": verdict,
        "notes": "; ".join(reasons),
        "signal_hint": (
            f"SHORT {y_name}/LONG {x_name} (rich)" if z_kal > 1.8 else
            f"LONG {y_name}/SHORT {x_name} (cheap)" if z_kal < -1.8 else "no trade"),
    }


def find_pairs(closes: dict[str, pd.Series], min_corr: float = 0.80,
               top_n: int = 12) -> list[dict]:
    """Screen all combos by log-return correlation first (cheap filter),
    then rank survivors by EG p-value. Returns best candidates to analyze."""
    names = list(closes)
    lg = {k: np.log(v) for k, v in closes.items()}
    cands = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            d = pd.concat([lg[a], lg[b]], axis=1).dropna()
            if len(d) < 250:
                continue
            corr = float(d.iloc[:, 0].diff().corr(d.iloc[:, 1].diff()))
            if corr >= min_corr:
                cands.append({"a": a, "b": b, "corr": round(corr, 3)})
    cands.sort(key=lambda r: -r["corr"])
    return cands[:top_n]
