"""SQLite OHLCV store: local cache keyed by (symbol, interval, timestamp)."""
import os
import sqlite3
import threading

import pandas as pd

# project root = two levels above this file's package (…/quantdesk/quantdesk/store.py)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(_PROJECT_ROOT, "quantdesk.db")
_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ohlcv (
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    ts INTEGER NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (symbol, interval, ts)
);
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opened_at TEXT, closed_at TEXT,
    symbol TEXT, side TEXT, qty REAL, entry REAL, exit_price REAL,
    stop REAL, target REAL, p_win REAL, ev_pct REAL, kelly_qty REAL,
    pnl REAL, notes TEXT
);
"""


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.executescript(_SCHEMA)
    return c


def upsert_ohlcv(symbol: str, interval: str, df: pd.DataFrame) -> int:
    """df index: UTC datetime; columns: open high low close volume."""
    if df is None or df.empty:
        return 0
    rows = [
        (symbol.upper(), interval, int(pd.Timestamp(ts).value // 10**6),
         float(r["open"]), float(r["high"]), float(r["low"]),
         float(r["close"]), float(r.get("volume", 0) or 0))
        for ts, r in df.iterrows()
    ]
    with _lock, _conn() as c:
        c.executemany(
            "INSERT OR REPLACE INTO ohlcv VALUES (?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def load_ohlcv(symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
    with _lock, _conn() as c:
        df = pd.read_sql_query(
            "SELECT ts, open, high, low, close, volume FROM ohlcv "
            "WHERE symbol=? AND interval=? ORDER BY ts DESC LIMIT ?",
            c, params=(symbol.upper(), interval, limit))
    if df.empty:
        return df
    df = df.iloc[::-1]
    df.index = pd.to_datetime(df.pop("ts"), unit="ms", utc=True)
    df.index.name = "date"
    return df.astype(float)


def journal_add(rec: dict) -> int:
    cols = ("opened_at", "closed_at", "symbol", "side", "qty", "entry",
            "exit_price", "stop", "target", "p_win", "ev_pct", "kelly_qty",
            "pnl", "notes")
    vals = [rec.get(k) for k in cols]
    with _lock, _conn() as c:
        cur = c.execute(
            f"INSERT INTO journal ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})",
            vals)
        return cur.lastrowid


def journal_list(open_only: bool = False) -> list[dict]:
    q = "SELECT * FROM journal"
    if open_only:
        q += " WHERE exit_price IS NULL"
    q += " ORDER BY id DESC"
    with _lock, _conn() as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute(q)]


def journal_close(jid: int, exit_price: float, closed_at: str, notes: str = "") -> dict:
    with _lock, _conn() as c:
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT * FROM journal WHERE id=?", (jid,)).fetchone()
        if row is None:
            raise ValueError(f"journal id {jid} not found")
        direction = 1 if row["side"] == "long" else -1
        pnl = direction * (exit_price - row["entry"]) * row["qty"]
        c.execute("UPDATE journal SET exit_price=?, closed_at=?, pnl=?, notes=? WHERE id=?",
                  (exit_price, closed_at, pnl, notes, jid))
        row = c.execute("SELECT * FROM journal WHERE id=?", (jid,)).fetchone()
        return dict(row)


def journal_stats() -> dict:
    with _lock, _conn() as c:
        n, wins, pnl = c.execute(
            "SELECT COUNT(*), SUM(pnl>0), COALESCE(SUM(pnl),0) "
            "FROM journal WHERE exit_price IS NOT NULL").fetchone()
    return {"closed_trades": n or 0, "wins": wins or 0,
            "win_rate": round((wins or 0) / n * 100, 1) if n else 0.0,
            "total_pnl": round(pnl or 0.0, 2)}
