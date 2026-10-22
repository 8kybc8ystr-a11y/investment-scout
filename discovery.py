"""Public-index candidate discovery, with deterministic daily rotation and graceful fallback."""
from __future__ import annotations
from datetime import datetime, timezone
from io import StringIO
import pandas as pd
import requests

INDEX_PAGES = [
    ('S&P 500', 'USA', 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', 'Symbol'),
    ('Nasdaq-100', 'USA', 'https://en.wikipedia.org/wiki/Nasdaq-100', 'Ticker'),
]


def discover(existing: set[str], per_day: int = 15) -> tuple[list[dict], list[str]]:
    """Rotate through public index constituents; does not claim to screen all listed shares."""
    candidates: dict[str, dict] = {}
    errors = []
    headers = {'User-Agent': 'InvestmentScoutResearch/3.0 (public index constituents; educational project)'}
    for index, region, url, column in INDEX_PAGES:
        try:
            response = requests.get(url, headers=headers, timeout=18)
            response.raise_for_status()
            tables = pd.read_html(StringIO(response.text))
            table = next((t for t in tables if column in t.columns), None)
            if table is None:
                raise ValueError(f'No {column} column found')
            for symbol in table[column].dropna().astype(str):
                symbol = symbol.strip().replace('.', '-')
                if symbol and symbol not in existing and symbol not in candidates:
                    candidates[symbol] = {'ticker': symbol, 'region': region, 'discovery_source': index}
        except Exception as exc:
            errors.append(f'{index}: {type(exc).__name__}: {str(exc)[:100]}')
    ordered = sorted(candidates.values(), key=lambda r: r['ticker'])
    if not ordered:
        return [], errors
    # Daily deterministic rotation avoids permanently analyzing only alphabetical first tickers.
    day = datetime.now(timezone.utc).date().toordinal()
    start = ((day * per_day) % len(ordered))
    selected = (ordered[start:] + ordered[:start])[:per_day]
    return selected, errors
