"""QuantDesk configuration: persisted settings + runtime defaults."""
import json
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config.json")

DEFAULTS = {
    "bankroll": 1500.0,
    "kelly_fraction": 0.5,
    "max_position_frac": 0.25,
    "min_ev_pct": 1.0,
    "fee_pct": 0.10,
    "slippage_pct": 0.05,
    "mc_paths": 10000,
    "horizon_days": 10,
    "watchlist_crypto": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    "watchlist_stocks": ["AAPL", "MSFT", "NVDA", "SPY"],
    "watchlist_fx": ["EURUSD=X"],
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


def save(cfg: dict) -> dict:
    merged = dict(DEFAULTS)
    merged.update(cfg)
    with open(CONFIG_PATH, "w") as f:
        json.dump(merged, f, indent=2)
    return merged
