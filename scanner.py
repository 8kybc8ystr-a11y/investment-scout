"""Daily, explainable stock screening. Educational research; not investment advice."""
from __future__ import annotations
import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / 'latest.json'


def number(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def pct(value):
    v = number(value)
    return round(100 * v, 2) if v is not None else None


def safe_ratio(info, key):
    return number(info.get(key))


def get_price_history(ticker):
    history = ticker.history(period='1y', auto_adjust=True)
    if history.empty or 'Close' not in history:
        return None
    closes = history['Close'].dropna()
    if len(closes) < 35:
        return None
    now = float(closes.iloc[-1])
    if now <= 0:
        return None
    def change(n):
        if len(closes) <= n:
            return None
        base = float(closes.iloc[-n-1])
        return round(100 * (now / base - 1), 2) if base > 0 else None
    peak = float(closes.max())
    return {
        'price': round(now, 4), 'change_5d': change(5),
        'change_30d': change(21), 'change_90d': change(63),
        'drawdown_1y': round(100 * (now / peak - 1), 2),
        'history': [{'date': idx.strftime('%Y-%m-%d'), 'close': round(float(v), 4)} for idx, v in closes.iloc[-130:].items()],
        'price_as_of': closes.index[-1].strftime('%Y-%m-%d'),
    }


def score_stock(row):
    """Transparent heuristic, 0-100. Missing values earn no points."""
    parts = {}
    dd = row.get('drawdown_1y')
    c30 = row.get('change_30d')
    parts['correction'] = min(25, max(0, (-dd - 10) * 1.25)) if dd is not None else 0
    if c30 is not None and c30 <= -15:
        parts['correction'] = min(25, parts['correction'] + 5)
    dy = row.get('dividend_yield_pct')
    parts['dividend'] = min(15, max(0, dy * 3)) if dy is not None and dy <= 12 else 0
    margin = row.get('profit_margin_pct')
    parts['profitability'] = min(15, max(0, margin * 0.75)) if margin is not None else 0
    roe = row.get('return_on_equity_pct')
    parts['roe'] = min(10, max(0, roe / 2)) if roe is not None and roe <= 100 else 0
    pe = row.get('forward_pe')
    parts['valuation'] = 15 if pe is not None and 0 < pe <= 12 else (10 if pe is not None and pe <= 20 and pe > 0 else (4 if pe is not None and pe <= 30 and pe > 0 else 0))
    fcf = row.get('free_cash_flow')
    parts['cashflow'] = 10 if fcf is not None and fcf > 0 else 0
    debt = row.get('debt_to_equity')
    # Yahoo debtToEquity is often expressed as a percentage (e.g. 80 for 80%).
    parts['debt'] = 10 if debt is not None and 0 <= debt <= 100 else (5 if debt is not None and debt <= 200 else 0)
    row['score_parts'] = {k: round(v, 1) for k, v in parts.items()}
    row['score'] = round(sum(parts.values()), 1)
    row['data_coverage'] = sum(row.get(k) is not None for k in ['drawdown_1y','dividend_yield_pct','profit_margin_pct','return_on_equity_pct','forward_pe','free_cash_flow','debt_to_equity'])
    return row


def explain(row):
    positives, risks = [], []
    dd, c30, dy = row.get('drawdown_1y'), row.get('change_30d'), row.get('dividend_yield_pct')
    if dd is not None and dd <= -20:
        positives.append(f"Kurs {abs(dd):.1f} % unter dem 1-Jahres-Hoch: möglicher Bewertungsanlass, kein Beleg für Unterbewertung.")
    if c30 is not None and c30 <= -15:
        risks.append(f"Starker Kursrückgang von {abs(c30):.1f} % in ca. 30 Handelstagen; Ursache muss geprüft werden.")
    if dy is not None and 2.5 <= dy <= 12:
        positives.append(f"Gemeldete Dividendenrendite von {dy:.1f} %; Ausschüttungsfähigkeit noch nicht verifiziert.")
    if dy is not None and dy > 8:
        risks.append('Hohe Dividendenrendite kann auf Kürzungsrisiken oder einen Kursverfall hindeuten.')
    if row.get('free_cash_flow') is not None:
        (positives if row['free_cash_flow'] > 0 else risks).append('Positiver freier Cashflow.' if row['free_cash_flow'] > 0 else 'Negativer freier Cashflow.')
    pe = row.get('forward_pe')
    if pe is not None and 0 < pe < 15:
        positives.append(f"Forward-KGV von {pe:.1f}; Vergleich mit Wettbewerbern erforderlich.")
    if row.get('debt_to_equity') is not None and row['debt_to_equity'] > 200:
        risks.append('Hoher gemeldeter Verschuldungsgrad; branchenspezifisch prüfen.')
    if row['data_coverage'] < 5:
        risks.append('Fundamentaldaten sind unvollständig; Score nur eingeschränkt belastbar.')
    risks.append('Nachrichten, Bilanzqualität, Dividendenhistorie und Geschäftsmodell sind noch nicht qualitativ geprüft.')
    return positives or ['Kein klares quantitatives Qualitätsargument identifiziert.'], risks


def scan(symbols=None, pause=0.15):
    universe = pd.read_csv(ROOT / 'universe.csv').dropna(subset=['ticker'])
    if symbols:
        universe = universe[universe['ticker'].isin(symbols)]
    stocks, errors = [], []
    for record in universe.to_dict('records'):
        symbol = record['ticker'].strip()
        try:
            ticker = yf.Ticker(symbol)
            price = get_price_history(ticker)
            if not price:
                raise ValueError('No sufficient price history')
            info = ticker.info or {}
            dividend = safe_ratio(info, 'dividendYield')
            # Yahoo data may encode yield as fraction or percent depending on version/feed.
            # Do not silently guess units when ambiguous; use trailing cash dividend / price if available.
            rate = safe_ratio(info, 'trailingAnnualDividendRate')
            dividend_pct = 100 * rate / price['price'] if rate is not None and rate >= 0 else None
            row = {
                'ticker': symbol, 'region': record['region'],
                'name': info.get('shortName') or info.get('longName') or symbol,
                'sector': info.get('sector') or 'Unbekannt',
                'currency': info.get('currency') or 'Unbekannt',
                **price,
                'dividend_yield_pct': round(dividend_pct, 2) if dividend_pct is not None else None,
                'forward_pe': safe_ratio(info, 'forwardPE'),
                'profit_margin_pct': pct(info.get('profitMargins')),
                'return_on_equity_pct': pct(info.get('returnOnEquity')),
                'free_cash_flow': safe_ratio(info, 'freeCashflow'),
                'debt_to_equity': safe_ratio(info, 'debtToEquity'),
                'market_cap': safe_ratio(info, 'marketCap'),
                'data_provider': 'Yahoo Finance via yfinance',
            }
            row = score_stock(row)
            row['positives'], row['risks'] = explain(row)
            stocks.append(row)
        except Exception as exc:
            errors.append({'ticker': symbol, 'error': str(exc)[:180]})
        time.sleep(pause)
    stocks.sort(key=lambda r: (r['score'], r['data_coverage']), reverse=True)
    return {'generated_at_utc': datetime.now(timezone.utc).isoformat(), 'method': 'rules_v1',
            'universe_count': len(universe), 'success_count': len(stocks),
            'stocks': stocks, 'errors': errors}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tickers', nargs='*', help='Optional symbols to scan')
    parser.add_argument('--output', default=str(DATA))
    args = parser.parse_args()
    output = Path(args.output)
    result = scan(args.tickers)
    if not result['stocks']:
        raise SystemExit('No valid stock data; existing snapshot left untouched')
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix('.tmp')
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(output)
    print(f"Scanned {result['success_count']}/{result['universe_count']} symbols; saved {output}")


if __name__ == '__main__':
    main()
