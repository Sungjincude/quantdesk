# QuantDesk

Local quantitative analysis & trade-suggestion desk. Classical math only —
Monte Carlo simulation, probability cones, cointegration, fractional Kelly.
**Suggestions only. It never places orders.**

## Install on any computer

**Linux / macOS**

    # 1. copy the quantdesk folder to the target machine (USB, zip, git clone)
    # 2. then:
    ./install.sh     # creates .venv and installs dependencies (uses uv if available)
    ./run.sh         # starts server + opens http://127.0.0.1:8600

**Windows**

    1. install Python from python.org (tick "Add python.exe to PATH")
    2. copy the quantdesk folder over, then double-click:
       install.bat   -> one-time dependency install
       run.bat       -> starts server + opens browser

Requires only Python 3.10+ and internet for the first install and market data.
Everything else (config.json, quantdesk.db) is created automatically on first run.

### Keep machines in sync (optional)

The folder is a git-ready repo (.gitignore already excludes .venv/db/config).
To version it on GitHub:

    cd ~/quantdesk
    git init && git add -A && git commit -m "QuantDesk v0.1"
    # create an empty repo on github.com, then:
    git remote add origin git@github.com:YOU/quantdesk.git
    git push -u origin main

Any other computer then gets it with `git clone` + `./install.sh`.
Your journal/config travel by copying `quantdesk.db` + `config.json`.

## Launch

    cd ~/quantdesk
    .venv/bin/uvicorn quantdesk.server:app --host 127.0.0.1 --port 8600

Then open **http://127.0.0.1:8600** in your browser.
(Or just use `./run.sh`, which does this for you.)

## Modules

| Path | Purpose |
|---|---|
| `quantdesk/data/bybit.py` | Bybit v5 public klines/tickers (crypto, no key needed) |
| `quantdesk/data/yahoo.py` | Yahoo daily bars + Stooq fallback (stocks/ETF/FX) |
| `quantdesk/data/store.py` | SQLite cache (`quantdesk.db`) + trade journal |
| `quantdesk/engines/volatility.py` | EWMA (RiskMetrics) + HAR-RV vol forecasts |
| `quantdesk/engines/montecarlo.py` | GBM / Student-t / block-bootstrap paths, first-passage barrier probabilities, probability cones, EV in R |
| `quantdesk/engines/cointegration.py` | Engle-Granger, Johansen, Kalman dynamic hedge, z-scores, OU half-life |
| `quantdesk/engines/screening.py` | Momentum/breakout screener + Kelly sizing |
| `quantdesk/backtest/walkforward.py` | Walk-forward pair & Donchian backtests incl. costs |
| `quantdesk/server.py` | FastAPI endpoints |
| `web/index.html` | Dashboard UI (self-contained, no CDN) |

## API

    GET  /api/config                 view settings     POST to change
    POST /api/refresh                pull all watchlist symbols
    GET  /api/quote/{sym}            price + vol snapshot
    POST /api/analyze                {symbol, side, stop?, target?, engine} -> probabilities/EV/Kelly
    GET  /api/screen?universe=all    ranked momentum table
    GET  /api/pairs/scan             cointegration candidates in watchlist
    GET  /api/pairs/report?a=&b=     deep pair report + walk-forward backtest
    GET  /api/backtest/breakout/{sym}?lookback=20&hold=10
    GET  /api/journal                list + stats        POST to open
    POST /api/journal/{id}/close     {exit_price}

## Tests

    .venv/bin/python tests/test_engines.py

## Notes

- Kelly slider lives in the top bar (default half-Kelly). Kelly will refuse
  trades where simulated edge is negative — that is intentional.
- EV shown net of round-trip fee+slippage (configurable). At small account
  size this honestly kills many marginal setups.
- Stocks/FX data is end-of-day (free sources); crypto is live Bybit daily bars.
- Phase 2 (sports betting vs Greek bookmakers) plugs in as additional engines
  later — same dashboard, same Kelly core.
