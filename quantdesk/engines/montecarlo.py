"""Monte Carlo price engines: GBM, Student-t shocks, circular block bootstrap.
Plus first-passage barrier probabilities and options-style probability cones.
Pure classical math — no ML anywhere."""
import numpy as np


# ---------------------------------------------------------------- simulators

def simulate_gbm(s0: float, mu_d: float, sig_d: float, horizon: int,
                 n_paths: int, seed: int | None = None) -> np.ndarray:
    """Geometric Brownian Motion. Returns array (n_paths, horizon+1); col 0 = S0."""
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((n_paths, horizon))
    inc = (mu_d - 0.5 * sig_d ** 2) + sig_d * z
    steps = s0 * np.exp(np.cumsum(inc, axis=1))
    return np.hstack([np.full((n_paths, 1), s0), steps])


def simulate_student_t(s0: float, mu_d: float, sig_d: float, horizon: int,
                       n_paths: int, nu: float = 5.0,
                       seed: int | None = None) -> np.ndarray:
    """GBM with fat-tailed (standardized Student-t) shocks — closer to real
    asset behavior than Gaussian; captures crash/jump risk."""
    rng = np.random.default_rng(seed)
    t = rng.standard_t(nu, size=(n_paths, horizon))
    t /= np.sqrt(nu / (nu - 2))          # unit-variance shocks
    inc = (mu_d - 0.5 * sig_d ** 2) + sig_d * t
    steps = s0 * np.exp(np.cumsum(inc, axis=1))
    return np.hstack([np.full((n_paths, 1), s0), steps])


def simulate_block_bootstrap(s0: float, hist_returns: np.ndarray, horizon: int,
                             n_paths: int, block: int = 10,
                             seed: int | None = None) -> np.ndarray:
    """Circular block bootstrap: resamples contiguous chunks of real history,
    preserving volatility clustering that iid models destroy."""
    rng = np.random.default_rng(seed)
    r = np.asarray(hist_returns, dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < block * 3:
        raise ValueError("not enough history for block bootstrap")
    out = np.empty((n_paths, horizon))
    starts = rng.integers(0, len(r), size=(n_paths, horizon // block + 2))
    for i in range(n_paths):
        buf = []
        for j, st in enumerate(starts[i]):
            idx = (st + np.arange(block)) % len(r)
            buf.append(r[idx])
            if sum(len(b) for b in buf) >= horizon:
                break
        out[i] = np.concatenate(buf)[:horizon]
    steps = s0 * np.exp(np.cumsum(out, axis=1))
    return np.hstack([np.full((n_paths, 1), s0), steps])


def run_engine(engine: str, close, horizon: int, n_paths: int,
               periods_per_year: int, seed: int | None = None) -> np.ndarray:
    """Dispatch on engine name using fitted EWMA vol + shrunk drift."""
    from .volatility import daily_drift, ewma_vol, log_returns
    r = log_returns(close)
    sig = ewma_vol(r)
    mu = daily_drift(close)
    s0 = float(close.iloc[-1])
    if engine == "gbm":
        return simulate_gbm(s0, mu, sig, horizon, n_paths, seed)
    if engine == "student_t":
        return simulate_student_t(s0, mu, sig, horizon, n_paths, seed=seed)
    if engine == "bootstrap":
        return simulate_block_bootstrap(s0, r.to_numpy(), horizon, n_paths,
                                        seed=seed)
    raise ValueError(f"unknown engine {engine!r}")


# ------------------------------------------------------- barrier / cone math

def barrier_probs(paths: np.ndarray, side: str, stop: float,
                  target: float) -> dict:
    """First-passage statistics from simulated paths (long or short).
    Returns P(target first), P(stop first), P(neither), plus terminal stats.
    This is the options-style 'probability of touching' math applied to spot."""
    body = paths[:, 1:]
    if side == "long":
        tgt_hit = body >= target
        stp_hit = body <= stop
    else:
        tgt_hit = body <= target
        stp_hit = body >= stop
    ht, hs = tgt_hit.any(axis=1), stp_hit.any(axis=1)

    def _first(a: np.ndarray) -> np.ndarray:
        """Index of first True per row; horizon if never True."""
        any_hit = a.any(axis=1)
        return np.where(any_hit, a.argmax(axis=1), a.shape[1])

    ft, fs = _first(tgt_hit), _first(stp_hit)
    n = paths.shape[0]
    p_tgt_first = float(((ht & ~hs) | ((ht & hs) & (ft < fs))).mean())
    p_stp_first = float(((hs & ~ht) | ((ht & hs) & (fs < ft))).mean())
    p_neither = float((~ht & ~hs).mean())
    term = paths[:, -1]

    # value the 'neither' branch at its median simulated outcome
    neither_mask = ~ht & ~hs
    if neither_mask.sum() > 30:
        med_exit = float(np.median(term[neither_mask]))
    else:
        med_exit = float(np.median(term))

    return {
        "p_target_first": round(p_tgt_first, 4),
        "p_stop_first": round(p_stp_first, 4),
        "p_neither": round(p_neither, 4),
        "median_exit_if_neither": round(med_exit, 6),
        "terminal_mean": round(float(term.mean()), 6),
        "terminal_p05": round(float(np.percentile(term, 5)), 6),
        "terminal_p50": round(float(np.percentile(term, 50)), 6),
        "terminal_p95": round(float(np.percentile(term, 95)), 6),
        "n_paths": n,
    }


def ev_in_r(barriers: dict, side: str, entry: float, stop: float,
            target: float) -> float:
    """Expected value of the trade in R-multiples (R = |entry-stop|).
    Neither-branch is marked at the median simulated exit."""
    r_unit = abs(entry - stop)
    if r_unit <= 0:
        return 0.0
    if side == "long":
        neither_r = (barriers["median_exit_if_neither"] - entry) / r_unit
    else:
        neither_r = (entry - barriers["median_exit_if_neither"]) / r_unit
    return round(barriers["p_target_first"] * 1.0
                 - barriers["p_stop_first"] * 1.0
                 + barriers["p_neither"] * neither_r, 4)


def prob_cone(paths: np.ndarray) -> dict:
    """Options-style cone: percentile bands per day ahead."""
    qs = [5, 25, 50, 75, 95]
    bands = {f"p{q}": np.percentile(paths, q, axis=0).round(4).tolist()
             for q in qs}
    up = float((paths[:, -1] > paths[:, 0]).mean())
    touch_up = float((paths.max(axis=1) > paths[:, 0]).mean())
    touch_dn = float((paths.min(axis=1) < paths[:, 0]).mean())
    return {"bands": bands, "p_end_above_start": round(up, 4),
            "p_touch_above": round(touch_up, 4), "p_touch_below": round(touch_dn, 4)}
