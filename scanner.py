"""Daily rules-based scan with rotating discovery candidates. No paid AI calls."""
from __future__ import annotations
import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from datetime import date
import pandas as pd
import yfinance as yf
from discovery import discover
from performance import load_ledger, update_ledger, tracked_missing

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
    returns = closes.pct_change().dropna()
    annual_volatility = float(returns.std() * (252 ** .5) * 100) if len(returns) >= 30 else None
    running_peak = closes.cummax()
    max_drawdown = float(((closes / running_peak) - 1).min() * 100)
    return {
        'price': round(now, 4), 'change_5d': change(5),
        'change_30d': change(21), 'change_90d': change(63),
        'drawdown_1y': round(100 * (now / peak - 1), 2),
        'volatility_1y_pct': round(annual_volatility, 2) if annual_volatility is not None else None,
        'max_drawdown_1y_pct': round(max_drawdown, 2),
        'history': [{'date': idx.strftime('%Y-%m-%d'), 'close': round(float(v), 4)} for idx, v in closes.items()],
        'price_as_of': closes.index[-1].strftime('%Y-%m-%d'),
    }


def score_stock(row):
    parts = {}
    dd, c30 = row.get('drawdown_1y'), row.get('change_30d')
    parts['correction'] = min(25, max(0, (-dd - 10) * 1.25)) if dd is not None else 0
    if c30 is not None and c30 <= -15:
        parts['correction'] = min(25, parts['correction'] + 5)
    dy = row.get('dividend_yield_pct')
    parts['dividend'] = min(15, max(0, dy * 3)) if dy is not None and 0 <= dy <= 12 else 0
    margin = row.get('profit_margin_pct')
    parts['profitability'] = min(15, max(0, margin * 0.75)) if margin is not None else 0
    roe = row.get('return_on_equity_pct')
    parts['roe'] = min(10, max(0, roe / 2)) if roe is not None and 0 <= roe <= 100 else 0
    pe = row.get('forward_pe')
    parts['valuation'] = 15 if pe is not None and 0 < pe <= 12 else (10 if pe is not None and pe <= 20 else (4 if pe is not None and pe <= 30 else 0))
    fcf = row.get('free_cash_flow')
    parts['cashflow'] = 10 if fcf is not None and fcf > 0 else 0
    debt = row.get('debt_to_equity')
    parts['debt'] = 10 if debt is not None and 0 <= debt <= 100 else (5 if debt is not None and 0 <= debt <= 200 else 0)
    row['score_parts'] = {k: round(v, 1) for k, v in parts.items()}
    row['score'] = round(sum(parts.values()), 1)
    row['data_coverage'] = sum(row.get(k) is not None for k in ['drawdown_1y', 'dividend_yield_pct', 'profit_margin_pct', 'return_on_equity_pct', 'forward_pe', 'free_cash_flow', 'debt_to_equity'])
    return row


def score_risk(row):
    """Transparent heuristic risk indicator: 0 low measured risk, 100 high.

    Missing fundamentals receive a neutral partial penalty, not an invented safe score.
    The indicator is not a default-probability model or a forecast.
    """
    parts = {}
    vol = row.get('volatility_1y_pct')
    parts['volatility'] = 10 if vol is None else (0 if vol < 20 else 7 if vol < 35 else 14 if vol < 55 else 20)
    dd = row.get('max_drawdown_1y_pct')
    parts['max_drawdown'] = 10 if dd is None else (0 if dd > -15 else 7 if dd > -30 else 14 if dd > -50 else 20)
    debt = row.get('debt_to_equity')
    parts['leverage'] = 10 if debt is None or debt < 0 else (0 if debt <= 50 else 6 if debt <= 100 else 13 if debt <= 200 else 20)
    margin = row.get('profit_margin_pct')
    parts['profitability'] = 8 if margin is None else (0 if margin >= 15 else 5 if margin >= 5 else 10 if margin >= 0 else 15)
    fcf = row.get('free_cash_flow')
    parts['cashflow'] = 5 if fcf is None else (0 if fcf > 0 else 10)
    dy = row.get('dividend_yield_pct')
    parts['dividend'] = 3 if dy is None else (5 if dy > 8 else 0)
    c30 = row.get('change_30d')
    parts['momentum'] = 5 if c30 is None else (0 if c30 >= -5 else 5 if c30 > -15 else 10)
    row['risk_parts'] = parts
    row['risk_score'] = int(sum(parts.values()))
    # A ranking heuristic, not an estimated expected return or investment recommendation.
    row['opportunity_risk_score'] = round(.7 * row['score'] + .3 * (100 - row['risk_score']), 1)
    return row


def explain(row):
    positives, risks = [], []
    dd, c30, dy = row.get('drawdown_1y'), row.get('change_30d'), row.get('dividend_yield_pct')
    if dd is not None and dd <= -20:
        positives.append(f'Kurs {abs(dd):.1f} % unter dem 1-Jahres-Hoch: möglicher Bewertungsanlass, kein Beleg für Unterbewertung.')
    if c30 is not None and c30 <= -15:
        risks.append(f'Starker Kursrückgang von {abs(c30):.1f} % in ca. 21 Handelstagen; Ursache muss geprüft werden.')
    if dy is not None and 2.5 <= dy <= 12:
        positives.append(f'Gemeldete Dividendenrendite von {dy:.1f} %; Ausschüttungsfähigkeit noch nicht verifiziert.')
    if dy is not None and dy > 8:
        risks.append('Hohe Dividendenrendite kann auf Kürzungsrisiken oder Kursverfall hindeuten.')
    if row.get('free_cash_flow') is not None:
        (positives if row['free_cash_flow'] > 0 else risks).append('Positiver freier Cashflow.' if row['free_cash_flow'] > 0 else 'Negativer freier Cashflow.')
    pe = row.get('forward_pe')
    if pe is not None and 0 < pe < 15:
        positives.append(f'Forward-KGV von {pe:.1f}; Wettbewerbsvergleich erforderlich.')
    if row.get('debt_to_equity') is not None and row['debt_to_equity'] > 200:
        risks.append('Hoher gemeldeter Verschuldungsgrad; branchenspezifisch prüfen.')
    if row['data_coverage'] < 5:
        risks.append('Fundamentaldaten unvollständig; Score nur eingeschränkt belastbar.')
    risks.append('Nachrichten, Bilanzqualität, Dividendenhistorie und Geschäftsmodell sind noch nicht qualitativ geprüft.')
    return positives or ['Kein klares quantitatives Qualitätsargument identifiziert.'], risks


def scan(symbols=None, pause=0.15, discovery_count=15):
    universe = pd.read_csv(ROOT / 'universe.csv').dropna(subset=['ticker'])
    base = []
    for record in universe.to_dict('records'):
        symbol = str(record['ticker']).strip()
        if symbol:
            base.append({'ticker': symbol, 'region': record['region'], 'discovery_source': 'Eigene Liste'})
    existing = {r['ticker'] for r in base}
    discovered, discovery_errors = ([], []) if symbols else discover(existing, per_day=discovery_count)
    records = base + discovered
    if symbols:
        wanted = set(symbols)
        records = [r for r in records if r['ticker'] in wanted]
    # Persist first-seen dates in the existing snapshot, so no additional GitHub file is needed.
    try:
        previous = json.loads(DATA.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        previous = {}
    first_seen = dict(previous.get('first_seen_registry') or {})
    # Upgrade from V3: existing stocks are not incorrectly marked as newly added.
    prior_date = str(previous.get('generated_at_utc', ''))[:10]
    for old in previous.get('stocks', []):
        if old.get('ticker') and old['ticker'] not in first_seen:
            first_seen[old['ticker']] = old.get('first_seen') or prior_date or date.today().isoformat()
    today = datetime.now(timezone.utc).date().isoformat()
    stocks, errors = [], []
    for record in records:
        symbol = record['ticker']
        try:
            ticker = yf.Ticker(symbol)
            price = get_price_history(ticker)
            if not price:
                raise ValueError('No sufficient price history')
            info = ticker.info or {}
            rate = number(info.get('trailingAnnualDividendRate'))
            dividend_pct = 100 * rate / price['price'] if rate is not None and rate >= 0 else None
            row = {
                'ticker': symbol, 'region': record['region'],
                'discovery_source': record['discovery_source'],
                'name': info.get('shortName') or info.get('longName') or symbol,
                'sector': info.get('sector') or 'Unbekannt',
                'currency': info.get('currency') or 'Unbekannt',
                **price,
                'dividend_yield_pct': round(dividend_pct, 2) if dividend_pct is not None else None,
                'forward_pe': number(info.get('forwardPE')),
                'profit_margin_pct': pct(info.get('profitMargins')),
                'return_on_equity_pct': pct(info.get('returnOnEquity')),
                'free_cash_flow': number(info.get('freeCashflow')),
                'debt_to_equity': number(info.get('debtToEquity')),
                'market_cap': number(info.get('marketCap')),
                'data_provider': 'Yahoo Finance via yfinance',
            }
            row['first_seen'] = first_seen.get(symbol, today)
            row['is_new'] = symbol not in first_seen
            first_seen.setdefault(symbol, today)
            if 'discovery_rank_score' in record:
                row['discovery_rank_score'] = record['discovery_rank_score']
                row['avg_daily_dollar_volume'] = record['avg_daily_dollar_volume']
            row = score_risk(score_stock(row))
            row['positives'], row['risks'] = explain(row)
            stocks.append(row)
        except Exception as exc:
            errors.append({'ticker': symbol, 'error': str(exc)[:180]})
        time.sleep(pause)
    stocks.sort(key=lambda r: (r['score'], r['data_coverage']), reverse=True)
    return {'generated_at_utc': datetime.now(timezone.utc).isoformat(), 'method': 'rules_v3_3', 'first_seen_registry': first_seen,
            'universe_count': len(records), 'success_count': len(stocks),
            'discovered_count': len(discovered), 'discovery_errors': discovery_errors,
            'stocks': stocks, 'errors': errors}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tickers', nargs='*')
    parser.add_argument('--output', default=str(DATA))
    parser.add_argument('--discovery-count', type=int, default=15)
    args = parser.parse_args()
    if not 0 <= args.discovery_count <= 100:
        parser.error('--discovery-count must be between 0 and 100')
    output = Path(args.output)
    result = scan(args.tickers, discovery_count=args.discovery_count)
    if not result['stocks']:
        raise SystemExit('No valid stock data; existing snapshot left untouched')
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix('.tmp')
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(output)
    # Maintain historical selections independently of the rotating daily universe.
    ledger_path = ROOT / 'data' / 'top5_history.json'
    ledger = load_ledger(ledger_path)
    additional = {}
    for symbol in tracked_missing(result['stocks'], ledger):
        try:
            h = yf.Ticker(symbol).history(period='5d', auto_adjust=True)
            closes = h['Close'].dropna()
            if not closes.empty:
                additional[symbol] = {'date': closes.index[-1].strftime('%Y-%m-%d'),
                                      'price': float(closes.iloc[-1])}
        except Exception:
            pass  # Missing observations remain missing, never estimated.
        time.sleep(0.05)
    ledger = update_ledger(ledger, result['stocks'], result['generated_at_utc'][:10], additional)
    tmp_ledger = ledger_path.with_suffix('.tmp')
    tmp_ledger.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp_ledger.replace(ledger_path)
    print(f"Scanned {result['success_count']}/{result['universe_count']} symbols; discovered {result['discovered_count']}; saved {output}")


if __name__ == '__main__':
    main()
