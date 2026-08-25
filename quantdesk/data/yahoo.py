"""Yahoo Finance daily bars via yfinance with Stooq CSV fallback."""
import io

import httpx
import pandas as pd


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize yfinance output (possible MultiIndex columns) to flat OHLCV."""
    if isinstance(df.columns, pd.MultiIndex):
        lvl0 = df.columns.get_level_values(0)
        if set(lvl0) >= {"Open", "High", "Low", "Close"}:
            df = df.copy()
            df.columns = lvl0
        else:
            df = df.droplevel(1, axis=1) if df.columns.nlevels > 1 else df
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    df.index = pd.to_datetime(df.index, utc=True)
    df.index.name = "date"
    return df.dropna(how="all").dropna(subset=["close"])


def fetch_yahoo(symbol: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(symbol, period=period, interval=interval,
                     progress=False, auto_adjust=True)
    if df is None or df.empty:
        raise RuntimeError(f"yahoo returned no data for {symbol}")
    return _norm(df)


def fetch_stooq(symbol: str) -> pd.DataFrame:
    sym = symbol.replace("=X", "=x").lower()
    if not sym.endswith(".us") and "=" not in sym:
        sym += ".us"
    url = f"https://stooq.com/q/d/l/?s={sym}&i=d"
    r = httpx.get(url, timeout=15, follow_redirects=True)
    r.raise_for_status()
    from io import StringIO
    df = pd.read_csv(StringIO(r.text), parse_dates=["Date"], index_col="Date")
    if df.empty or "Close" not in df.columns:
        raise RuntimeError(f"stooq returned no data for {sym}")
    df = df.rename(columns=str.lower)
    df.index = df.index.tz_localize("UTC")
    df.index.name = "date"
    return df.astype(float)


def fetch_daily(symbol: str, period: str = "2y") -> pd.DataFrame:
    """Yahoo first, Stooq fallback."""
    try:
        return fetch_yahoo(symbol, period=period)
    except Exception:
        return fetch_stooq(symbol)
