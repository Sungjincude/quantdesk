"""Engine smoke tests: run with .venv/bin/python tests/test_engines.py"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from quantdesk.engines import montecarlo as mc
from quantdesk.engines import cointegration as cg
from quantdesk.engines.screening import screen_all, kelly_star, kelly_stake

rng = np.random.default_rng(11)
idx = pd.date_range("2024-01-01", periods=500, freq="D")


def _mk_series(vals):
    return pd.Series(vals, index=idx)


def make_cointegrated():
    """x: random walk; y = 2 + 0.8x + OU noise => cointegrated by construction."""
    x = np.cumsum(rng.normal(0.0003, 0.01, 500)) + 50
    ou = np.zeros(500)
    for t in range(1, 500):
        ou[t] = 0.92 * ou[t - 1] + rng.normal(0, 0.008)   # fast mean reversion
    y = 2 + 0.8 * x + ou
    return _mk_series(y * 100 + 200), _mk_series(x)


def make_independent_rw():
    a = np.cumsum(rng.normal(0, 0.012, 500)) + 100
    b = np.cumsum(rng.normal(0, 0.012, 500)) + 100
    return _mk_series(a), _mk_series(b)


def test_cointegration():
    y, x = make_cointegrated()
    rep = cg.analyze_pair(y, x, "SYNTH_Y", "SYNTH_X")
    print("--- cointegrated pair:", {k: rep[k] for k in
          ("eg_pvalue", "johansen_rank_5pct", "half_life_days",
           "z_kalman", "verdict")})
    assert rep["eg_pvalue"] < 0.05, f"EG failed on true cointegrated pair: {rep}"
    assert rep["half_life_days"] is not None and rep["half_life_days"] < 30

    ya, xb = make_independent_rw()
    rep2 = cg.analyze_pair(ya, xb, "RW_A", "RW_B")
    print("--- independent RWs:", {k: rep2[k] for k in
          ("eg_pvalue", "verdict", "notes")})
    assert rep2["eg_pvalue"] > 0.10, "false positive on independent walks!"

    # correlation finder should pick up the cointegrated pair
    hits = cg.find_pairs({"Y": y, "X": x, "A": ya}, min_corr=-1.0, top_n=5)
    print("--- find_pairs:", hits[:3])
    top = {(h["a"], h["b"]) for h in hits[:1]}
    assert ("Y", "X") in top or ("X", "Y") in top, "finder missed true pair"
    print("COINTEGRATION TESTS PASSED")


def test_screening_and_kelly():
    # Strong drift vs weak vol so the trend ordering is statistically
    # unambiguous even on a fixed seed (engine should rank by true trend).
    closes = {}
    for name, drift, vol in [("UPSTOCK", 0.004, 0.006),
                             ("DOWNSTOCK", -0.004, 0.006),
                             ("FLATSTOCK", 0.0, 0.004)]:
        r = rng.normal(drift, vol, 500)
        closes[name] = _mk_series(100 * np.exp(np.cumsum(r)))
    rows = screen_all(closes)
    print("--- screen:")
    for row in rows:
        print("   ", {k: (v if not isinstance(v, np.floating) else float(v))
                      for k, v in row.items()})
    syms = [r["symbol"] for r in rows]
    assert syms.index("UPSTOCK") < syms.index("DOWNSTOCK")

    # Kelly closed-form checks
    assert abs(kelly_star(0.6, 1.0) - 0.20) < 1e-9      # classic 60/40 coin
    assert abs(kelly_star(0.55, 2.0) - 0.325) < 1e-9
    neg = kelly_stake(10000, 100, p_win=0.35, entry=100,
                      stop=97, target=103, kelly_fraction=0.5)
    assert neg["qty"] == 0.0, "should refuse negative-edge trade"
    pos = kelly_stake(10000, 100, p_win=0.60, entry=100,
                      stop=98, target=106, kelly_fraction=0.5)
    print("--- kelly stake:", pos)
    assert pos["qty"] > 0 and pos["risk_amount"] < 10000 * 0.25
    # cap test: huge edge must still respect max_position_frac
    cap = kelly_stake(10000, 50, p_win=0.95, entry=50, stop=49.9,
                      target=52, kelly_fraction=1.0, max_position_frac=0.25)
    assert cap["budget"] <= 2500.01
    print("SCREENING + KELLY TESTS PASSED")


if __name__ == "__main__":
    test_cointegration()
    test_screening_and_kelly()
    print("\nALL TESTS PASSED")
