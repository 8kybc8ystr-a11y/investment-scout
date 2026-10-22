"""Rank a broad index universe with inexpensive price/liquidity signals before fundamental scans."""
from __future__ import annotations
from io import StringIO
import math
import pandas as pd
import requests
import yfinance as yf

INDEX_PAGES = [
    ('S&P 500', 'USA', 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', 'Symbol'),
    ('Nasdaq-100', 'USA', 'https://en.wikipedia.org/wiki/Nasdaq-100', 'Ticker'),
]

def _universe(existing):
    candidates, errors = {}, []
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; InvestmentScout/3.1; personal educational research)'}
    for index, region, url, column in INDEX_PAGES:
        try:
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()
            tables = pd.read_html(StringIO(response.text))
            table = next((t for t in tables if column in t.columns), None)
            if table is None:
                raise ValueError(f'Missing {column} table')
            for raw in table[column].dropna().astype(str):
                symbol = raw.strip().replace('.', '-')
                if symbol and symbol not in existing:
                    candidates.setdefault(symbol, {'ticker': symbol, 'region': region, 'discovery_source': index})
        except Exception as exc:
            errors.append(f'{index}: {type(exc).__name__}: {str(exc)[:120]}')
    return candidates, errors

def discover(existing: set[str], per_day: int = 15):
    """Select high-opportunity price setups, not random rotation. No paid AI calls."""
    candidates, errors = _universe(existing)
    if not candidates or per_day <= 0:
        return [], errors
    tickers = sorted(candidates)
    ranked = []
    # Download in batches to limit requests and avoid one failed symbol stopping discovery.
    for start in range(0, len(tickers), 75):
        batch = tickers[start:start + 75]
        try:
            prices = yf.download(batch, period='1y', interval='1d', group_by='ticker',
                                 auto_adjust=True, threads=True, progress=False, timeout=30)
            for symbol in batch:
                try:
                    frame = prices[symbol] if isinstance(prices.columns, pd.MultiIndex) else prices
                    close = frame['Close'].dropna()
                    volume = frame['Volume'].dropna()
                    if len(close) < 120 or len(volume) < 20:
                        continue
                    now, high = float(close.iloc[-1]), float(close.max())
                    avg_dollar_volume = float((frame['Close'] * frame['Volume']).tail(20).mean())
                    if not all(math.isfinite(v) for v in (now, high, avg_dollar_volume)) or now < 3 or avg_dollar_volume < 5_000_000:
                        continue
                    drawdown = 100 * (now / high - 1)
                    month_change = 100 * (now / float(close.iloc[-22]) - 1)
                    quarter_change = 100 * (now / float(close.iloc[-64]) - 1)
                    # Opportunity heuristic: meaningful pullback, some price stabilization,
                    # and sufficient liquidity. Severe falls are penalized rather than rewarded.
                    pullback = max(0, 25 - abs(drawdown + 22))
                    stabilization = max(0, 15 - abs(month_change - 2))
                    trend = max(0, 10 - abs(quarter_change))
                    liquidity = min(10, math.log10(max(1, avg_dollar_volume / 1_000_000)) * 4)
                    risk_penalty = max(0, -drawdown - 45) * 1.5
                    discovery_score = round(pullback + stabilization + trend + liquidity - risk_penalty, 2)
                    ranked.append((discovery_score, symbol, round(drawdown, 2), round(avg_dollar_volume)))
                except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError):
                    continue
        except Exception as exc:
            errors.append(f'Kursdaten Batch {start // 75 + 1}: {type(exc).__name__}: {str(exc)[:100]}')
    ranked.sort(key=lambda x: (-x[0], x[1]))
    selected = []
    for score, symbol, drawdown, liquidity in ranked[:per_day]:
        selected.append({**candidates[symbol], 'discovery_rank_score': score,
                         'discovery_drawdown_pct': drawdown, 'avg_daily_dollar_volume': liquidity})
    if not selected:
        errors.append('Keine geeigneten Kandidaten aus den verfügbaren Kursdaten; bestehende Liste wird weiter gescannt.')
    return selected, errors
