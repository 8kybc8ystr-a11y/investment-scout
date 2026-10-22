"""Persistent, no-look-ahead Top-5 observation ledger (not a backtest)."""
from __future__ import annotations
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

MAX_TRACKED = 250
HORIZONS = (7, 30, 90)


def load_ledger(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if isinstance(data, dict) and isinstance(data.get('picks'), list) and isinstance(data.get('prices'), dict):
            return data
    except (OSError, ValueError):
        pass
    return {'schema_version': 1, 'picks': [], 'prices': {}, 'last_updated_utc': None}


def select_top5(stocks):
    eligible = [s for s in stocks if (s.get('data_coverage') or 0) >= 5 and s.get('opportunity_risk_score') is not None]
    return sorted(eligible, key=lambda s: (-s['opportunity_risk_score'], -(s.get('data_coverage') or 0), s['ticker']))[:5]


def update_ledger(ledger, stocks, observation_date, extra_quotes=None):
    """Add one selection per UTC day and closing-price observations.

    A selection is stored only when it first appears, and is never reconstructed
    from historic prices. Re-running the same date does not rewrite its entry.
    """
    extra_quotes = extra_quotes or {}
    picks = ledger.setdefault('picks', [])
    prices = ledger.setdefault('prices', {})
    selected = select_top5(stocks)
    if not any(p.get('selection_date') == observation_date for p in picks):
        for rank, stock in enumerate(selected, 1):
            if not stock.get('price') or not stock.get('price_as_of'):
                continue
            picks.append({
                'selection_date': observation_date, 'rank': rank,
                'ticker': stock['ticker'], 'name': stock.get('name', stock['ticker']),
                'entry_date': stock['price_as_of'], 'entry_price': stock['price'],
                'currency': stock.get('currency', '?'),
                'score': stock.get('score'), 'risk_score': stock.get('risk_score'),
                'opportunity_risk_score': stock['opportunity_risk_score'],
            })
    quotes = {s['ticker']: {'date': s.get('price_as_of'), 'price': s.get('price'), 'currency': s.get('currency')}
              for s in stocks}
    quotes.update(extra_quotes)
    for ticker in {p['ticker'] for p in picks}:
        quote = quotes.get(ticker) or {}
        price, day = quote.get('price'), quote.get('date')
        if not price or not day or price <= 0:
            continue
        series = prices.setdefault(ticker, {})
        # Do not overwrite an already-recorded close, including during re-runs.
        series.setdefault(day, round(float(price), 6))
    ledger['last_updated_utc'] = datetime.now(timezone.utc).isoformat()
    return ledger


def tracked_missing(stocks, ledger):
    present = {s['ticker'] for s in stocks}
    return sorted({p['ticker'] for p in ledger.get('picks', [])} - present)[:MAX_TRACKED]


def performance_rows(ledger, horizon):
    """Only matured picks with an observed close on/after target day.

    To avoid reporting a delayed quote as the target-day price, allow 4 days
    after target (weekends/holidays). No interpolation or invented returns.
    """
    result = []
    for p in ledger.get('picks', []):
        entry_day = p.get('entry_date')
        entry_price = p.get('entry_price')
        if not entry_day or not entry_price or entry_price <= 0:
            continue
        target = date.fromisoformat(entry_day) + timedelta(days=horizon)
        candidates = []
        for day, price in ledger.get('prices', {}).get(p['ticker'], {}).items():
            d = date.fromisoformat(day)
            if target <= d <= target + timedelta(days=4) and price and price > 0:
                candidates.append((d, price))
        if not candidates:
            continue
        day, price = min(candidates)
        result.append({**p, 'horizon_days': horizon, 'exit_date': day.isoformat(),
                       'exit_price': price, 'return_pct': round((price / entry_price - 1) * 100, 2)})
    return result


def daily_cohorts(ledger, horizon):
    rows = performance_rows(ledger, horizon)
    grouped = {}
    for r in rows:
        grouped.setdefault(r['selection_date'], []).append(r)
    # Do not report a Top-5 basket if any constituent lacks an exit observation.
    expected = {}
    for p in ledger.get('picks', []):
        expected[p['selection_date']] = expected.get(p['selection_date'], 0) + 1
    return [{'date': day, 'return_pct': round(sum(r['return_pct'] for r in rs) / len(rs), 2),
             'count': len(rs), 'positive': sum(r['return_pct'] > 0 for r in rs)}
            for day, rs in sorted(grouped.items()) if len(rs) == expected.get(day) and len(rs) == 5]
