"""On-demand, source-aware AI research. No automated trade recommendations."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from urllib.parse import urlparse
import yfinance as yf
from openai import OpenAI

MODEL = 'gpt-4.1-mini'


def get_news(symbol: str, limit: int = 8) -> list[dict]:
    """Fetch article metadata. Never claim an article was read from its headline alone."""
    result = []
    try:
        items = yf.Ticker(symbol).news or []
    except Exception:
        return result
    for item in items:
        article = item.get('content', item)
        title = article.get('title') or item.get('title')
        provider = article.get('provider') or {}
        source = provider.get('displayName') if isinstance(provider, dict) else str(provider)
        canonical = article.get('canonicalUrl') or article.get('clickThroughUrl') or {}
        url = canonical.get('url') if isinstance(canonical, dict) else canonical
        url = url or item.get('link')
        if not isinstance(url, str) or urlparse(url).scheme not in ('https', 'http'):
            continue
        if not title:
            continue
        published = article.get('pubDate') or item.get('providerPublishTime')
        if isinstance(published, (int, float)):
            published = datetime.fromtimestamp(published, timezone.utc).isoformat()
        result.append({'title': str(title)[:300], 'source': source or 'Unbekannt',
                       'published': str(published or 'Unbekannt'), 'url': url})
        if len(result) >= limit:
            break
    return result


def build_analysis(stock: dict, api_key: str, news: list[dict]) -> str:
    if not api_key:
        raise ValueError('OPENAI_API_KEY fehlt.')
    allowed = ['ticker', 'name', 'region', 'sector', 'currency', 'price', 'price_as_of',
               'change_5d', 'change_30d', 'change_90d', 'drawdown_1y',
               'dividend_yield_pct', 'forward_pe', 'profit_margin_pct',
               'return_on_equity_pct', 'free_cash_flow', 'debt_to_equity',
               'market_cap', 'score', 'data_coverage', 'data_provider']
    facts = {key: stock.get(key) for key in allowed}
    system = '''Du bist ein skeptischer, deutschsprachiger Aktien-Research-Analyst.
Nutze ausschließlich die übermittelten Kennzahlen und Nachrichten-Metadaten.
Du hast KEINEN Volltext von Nachrichten oder Geschäftsberichten gelesen.
Unterscheide strikt belegte Fakten, plausible Hypothesen und offene Fragen.
Niemals Nachrichteninhalte, Gewinnzahlen, Fair Values, Kursziele oder Quellen erfinden.
Ein Kursrückgang ist kein Beleg für Unterbewertung. Kennzahlen können veraltet,
fehlerhaft oder sektorspezifisch ungeeignet sein. Dividend yield ist nicht verifiziert.
Bei fehlenden Belegen: ausdrücklich 'nicht belegt' schreiben.
Antworte auf Deutsch in Markdown, mit genau diesen Abschnitten:
## Kurzfazit
## Belegte quantitative Signale
## Mögliche Ursachen des Kursrückgangs (Hypothesen, keine Feststellungen)
## Dividende und Bilanzqualität
## Bull Case und Bear Case
## Was vor einer Investition geprüft werden muss
## Quellen und Datenlücken
Führe Nachrichten ausschließlich als Überschriften mit Datum und URL an.
Bewerte die Verlässlichkeit der Analyse (niedrig/mittel/hoch) mit Begründung.
Keine persönliche Kaufempfehlung und kein erfundener Fair Value.'''
    payload = {'analysis_time_utc': datetime.now(timezone.utc).isoformat(),
               'stock': facts, 'news_headlines_only': news}
    client = OpenAI(api_key=api_key, timeout=40.0, max_retries=1)
    response = client.chat.completions.create(
        model=MODEL, temperature=0.2, max_tokens=1700,
        messages=[{'role': 'system', 'content': system},
                  {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, default=str)}],
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError('Keine Analyse vom KI-Dienst erhalten.')
    return content
