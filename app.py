import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from ai_research import get_news, build_analysis
from security import require_login, check_ai_limit, register_ai_request
from performance import load_ledger, performance_rows, daily_cohorts

st.set_page_config(page_title='Investment Scout V3.4', page_icon='📈', layout='wide')
require_login()

ROOT = Path(__file__).resolve().parent
st.markdown("""<style>
.block-container {padding-top: 1.4rem; max-width: 1500px}
[data-testid="stMetric"] {background: rgba(127,127,127,.055); border: 1px solid rgba(127,127,127,.17); border-radius: 13px; padding: 15px}
h1 {letter-spacing: -.035em}
</style>""", unsafe_allow_html=True)
st.title('Investment Scout  |  Marktübersicht')
st.caption('V3.4 · Regelbasiertes Aktien-Screening · Manuelle KI-Recherche · Keine Kaufempfehlung')

snapshot = ROOT / 'data' / 'latest.json'
if not snapshot.exists():
    st.warning('Noch keine Marktdaten vorhanden. Bitte zunächst `python scanner.py` ausführen oder den GitHub-Scan abwarten.')
    st.code('pip install -r requirements.txt\npython scanner.py\nstreamlit run app.py', language='bash')
    st.stop()
try:
    data = json.loads(snapshot.read_text(encoding='utf-8'))
except (ValueError, OSError) as exc:
    st.error(f'Daten konnten nicht geladen werden: {exc}')
    st.stop()

stocks = data.get('stocks', [])
if not stocks:
    st.warning('Der letzte Scan enthält keine gültigen Aktien.')
    st.stop()

df = pd.DataFrame([{k: v for k, v in s.items() if k not in ('history', 'positives', 'risks', 'score_parts')} for s in stocks])
with st.sidebar:
    st.header('Filter')
    regions = st.multiselect('Region', sorted(df['region'].dropna().unique()), default=sorted(df['region'].dropna().unique()))
    min_score = st.slider('Mindest-Score', 0, 100, 40)
    min_dividend = st.slider('Mindestrendite (%)', 0.0, 10.0, 0.0, 0.5)
    only_corrections = st.checkbox('Mindestens 15 % unter 1-Jahres-Hoch', False)
    source_filter = st.selectbox('Aktienquelle', ['Alle', 'Eigene Liste', 'Automatisch entdeckt'])
    search = st.text_input('Aktienname / Symbol')
    st.divider()
    st.caption('Datenanbieter: Yahoo Finance (inoffizielle Schnittstelle). Kennzahlen können fehlen, verzögert oder falsch sein. Kein Echtzeit-Feed.')

filtered = df[df['region'].isin(regions) & (df['score'] >= min_score)].copy()
filtered = filtered[filtered['dividend_yield_pct'].fillna(-1) >= min_dividend]
if only_corrections:
    filtered = filtered[filtered['drawdown_1y'].fillna(0) <= -15]
if source_filter != 'Alle' and 'discovery_source' in filtered.columns:
    if source_filter == 'Eigene Liste':
        filtered = filtered[filtered['discovery_source'] == 'Eigene Liste']
    else:
        filtered = filtered[filtered['discovery_source'] != 'Eigene Liste']
if search:
    filtered = filtered[filtered['ticker'].str.contains(search, case=False, regex=False) | filtered['name'].str.contains(search, case=False, regex=False)]

c1, c2, c3, c4 = st.columns(4)
c1.metric('Analysierte Aktien', data.get('success_count', len(stocks)))
c2.metric('Treffer nach Filtern', len(filtered))
c3.metric('Höchster Score', f"{filtered['score'].max():.0f}/100" if len(filtered) else '–')
c4.metric('Datenstand (UTC)', data.get('generated_at_utc', '?')[:16].replace('T', ' '))
if data.get('errors'):
    st.caption(f"{len(data['errors'])} Aktien konnten nicht verarbeitet werden. Details unten.")

# Top 5 aus dem gesamten heutigen Scan, unabhängig von den persönlichen Tabellenfiltern.
if 'risk_score' not in df.columns or 'opportunity_risk_score' not in df.columns:
    st.warning('Die Risiko-Scores fehlen noch. Bitte zuerst den neuen V3.3-Scanner über GitHub Actions ausführen.')
    st.stop()

# Für eine Mindestzuverlässigkeit werden Aktien mit sehr lückenhaften Fundamentaldaten ausgeschlossen.
st.subheader('Top 5 · Chancen-Risiko-Ranking')
st.caption('Die fünf besten Werte des kombinierten Rankings mit mindestens 5 von 7 Fundamentaldaten. 70 % Attraktivität und 30 % niedrigeres gemessenes Risiko. Keine Kaufempfehlung.')
top_candidates = df[df['data_coverage'].fillna(0) >= 5].sort_values(
    ['opportunity_risk_score', 'data_coverage', 'ticker'], ascending=[False, False, True]
).head(5)
if top_candidates.empty:
    st.warning('Heute gibt es keine Kandidaten mit ausreichend vollständigen Fundamentaldaten (mindestens 5/7).')
else:
    cards = st.columns(len(top_candidates))
    for pos, (_, candidate) in enumerate(top_candidates.iterrows(), start=1):
        with cards[pos-1]:
            with st.container(border=True):
                ticker_name = str(candidate['ticker'])
                new_mark = ' 🆕' if candidate.get('is_new', False) else ''
                st.markdown(f'**#{pos} · {ticker_name}{new_mark}**')
                st.caption(str(candidate.get('name', ticker_name))[:42])
                st.metric('Ranking-Index', f"{candidate['opportunity_risk_score']:.0f}/100")
                st.caption(f"Attraktivität: {candidate['score']:.0f}/100 · Risiko: {candidate['risk_score']:.0f}/100 (hoch = riskanter)")
                st.caption(f"Datenqualität: {int(candidate['data_coverage'])}/7 · {candidate.get('region','–')}")
                if st.button('Details ansehen', key=f'top_{ticker_name}', use_container_width=True):
                    st.session_state['selected_stock'] = ticker_name
st.info('Ein hoher Score zeigt nur, dass eine Aktie die gewählten quantitativen Kriterien erfüllt. '
        'Ein Kursrückgang oder eine hohe Dividende kann auch ein Warnsignal sein. '
        'Vor einem Kauf sollten Bewertung, Nachrichten, Bilanz und persönliche Risikotoleranz geprüft werden.')
with st.expander('Wie werden die Top 5 ermittelt?', expanded=False):
    st.markdown('**Tägliche Auswahl:** Der Scanner untersucht die eigene Aktienliste und zusätzliche automatisch gefundene Kandidaten. Für die Top 5 werden nur Aktien mit mindestens fünf von sieben Fundamentaldatenfeldern berücksichtigt. Danach entscheidet der **Chancen-Risiko-Index**; bei Gleichstand gewinnt die höhere Datenabdeckung.\n\n**Punkteverteilung:** Kursrückgang 25 · Dividendenrendite 15 · Gewinnmarge 15 · Eigenkapitalrendite 10 · Forward-KGV 15 · positiver freier Cashflow 10 · Verschuldung 10.\n\n**Kombination:** 70 % Attraktivitäts-Score + 30 % (100 − Risiko-Score). Beim Risiko-Score bedeuten 100 Punkte hohe Risiken. Fehlende Risikodaten werden vorsichtig mit Teilpunkten berücksichtigt. Der Index ist kein Renditeversprechen.\n\n**Grenzen:** Der Score ist heuristisch, branchenübergreifend nur eingeschränkt vergleichbar und berücksichtigt keine vollständige Unternehmensbewertung. Die Top 5 sind die attraktivsten **innerhalb der tatsächlich gescannten Auswahl**, nicht des gesamten Aktienmarkts.')

st.divider()
st.subheader('📊 Historie der täglichen Top 5')
st.caption('Ab V3.4 werden die tatsächlichen Tagesauswahlen gespeichert. Keine rückwirkend konstruierten Treffer und kein historischer Backtest.')
ledger_path = ROOT / 'data' / 'top5_history.json'
if not ledger_path.exists():
    st.info('Noch keine Auswahlhistorie vorhanden. Starte den V3.4-Scan; ab dann werden die täglichen Top 5 protokolliert.')
else:
    ledger = load_ledger(ledger_path)
    selections = pd.DataFrame(ledger.get('picks', []))
    if selections.empty:
        st.info('Noch keine Top-5-Auswahlen gespeichert.')
    else:
        dates = sorted(selections['selection_date'].unique(), reverse=True)
        chosen_date = st.selectbox('Top-5-Auswahl vom', dates, key='history_day')
        chosen = selections[selections['selection_date'] == chosen_date].sort_values('rank')
        show_cols = ['rank', 'ticker', 'name', 'entry_date', 'entry_price', 'currency', 'opportunity_risk_score', 'risk_score']
        st.dataframe(chosen[show_cols].rename(columns={
            'rank':'Rang', 'ticker':'Symbol', 'name':'Unternehmen', 'entry_date':'Kursdatum',
            'entry_price':'Startkurs', 'currency':'Währung', 'opportunity_risk_score':'Ranking-Index',
            'risk_score':'Risiko'}), hide_index=True, use_container_width=True)
        horizon = st.radio('Beobachtungszeitraum (Kalendertage)', [7, 30, 90], horizontal=True, index=0)
        completed = performance_rows(ledger, horizon)
        selected_returns = [r for r in completed if r['selection_date'] == chosen_date]
        if selected_returns:
            st.dataframe(pd.DataFrame(selected_returns)[['ticker', 'entry_price', 'exit_price', 'exit_date', 'return_pct']].rename(columns={
                'ticker':'Symbol', 'entry_price':'Startkurs', 'exit_price':'Vergleichskurs',
                'exit_date':'Vergleichsdatum', 'return_pct':'Kursänderung %'}), hide_index=True, use_container_width=True)
        else:
            st.caption('Für diesen Tag liegen noch keine ausreichend alten und vollständig beobachteten Vergleichskurse vor.')
        cohorts = daily_cohorts(ledger, horizon)
        if cohorts:
            cohort_df = pd.DataFrame(cohorts)
            st.metric(f'Durchschnitt aller vollständigen Top-5-Tagesgruppen nach {horizon} Tagen',
                      f"{cohort_df['return_pct'].mean():+.2f} %")
            st.line_chart(cohort_df.set_index('date')['return_pct'], y_label='Durchschnittliche Kursänderung (%)')
            st.caption(f'{len(cohorts)} vollständig beobachtete Tagesgruppen. Jede Aktie wird innerhalb ihres Tages gleich gewichtet; wiederkehrende Aktien können mehrfach zählen.')
        else:
            st.caption('Noch keine vollständigen Top-5-Tagesgruppen für diesen Zeitraum verfügbar.')
    st.caption('Vergleich mit dem ersten gespeicherten Schlusskurs am/kurz nach dem Zieltag (max. 4 Kalendertage später). Fehlende Kurse werden nicht geschätzt. Keine Gebühren, Steuern oder Währungsumrechnung; historische Adjustierungen und Dividenden können die Vergleichbarkeit beeinflussen. Kein Benchmark oder Nachweis einer Überrendite.')

st.divider()
st.subheader('Alle Aktien im Ranking')
st.caption('Risiko: 0 = niedrigeres gemessenes Risiko, 100 = höheres gemessenes Risiko. Die Werte sind heuristisch und keine Ausfallwahrscheinlichkeiten.')
if 'discovery_source' in df.columns:
    new_count = int((df['discovery_source'] != 'Eigene Liste').sum())
    st.info(f'🔎 Intelligente Vorauswahl: {new_count} zusätzliche Aktien nach Kursrückgang, Stabilisierung und Liquidität analysiert. Kandidaten aus S&P 500 und Nasdaq-100; kein vollständiger Weltmarkt-Scan.')
    if data.get('discovery_errors'):
        with st.expander('Hinweise zur Kandidatensuche'):
            st.write(data['discovery_errors'])
else:
    st.caption('Noch ein V2-Datensnapshot geladen. Nach dem nächsten V3-GitHub-Scan erscheint hier die automatische Kandidatensuche.')
cols = ['ticker', 'name', 'region', 'sector', 'score', 'risk_score', 'opportunity_risk_score', 'price', 'currency', 'change_30d', 'drawdown_1y', 'dividend_yield_pct', 'forward_pe', 'data_coverage']
if 'discovery_source' in filtered.columns:
    cols.insert(3, 'discovery_source')
if 'is_new' in filtered.columns:
    cols.insert(0, 'is_new')
if 'first_seen' in filtered.columns:
    cols.insert(1, 'first_seen')
table_data = filtered[cols].copy()
if 'is_new' in table_data:
    table_data['is_new'] = table_data['is_new'].map({True: '🆕 Neu', False: '–'}).fillna('–')
st.dataframe(table_data.rename(columns={'ticker':'Symbol','name':'Unternehmen','region':'Region','discovery_source':'Quelle','is_new':'Neu','first_seen':'Seit','sector':'Sektor','score':'Attraktivität','risk_score':'Risiko (hoch = riskant)','opportunity_risk_score':'Chancen-Risiko-Index','price':'Kurs','currency':'Währung','change_30d':'30T %','drawdown_1y':'Abstand Hoch %','dividend_yield_pct':'Dividende %','forward_pe':'Forward-KGV','data_coverage':'Datenfelder / 7'}), use_container_width=True, hide_index=True)

if len(filtered):
    available_tickers = filtered['ticker'].tolist()
    if st.session_state.get('selected_stock') not in available_tickers:
        st.session_state['selected_stock'] = available_tickers[0]
    selected = st.selectbox('Aktie im Detail untersuchen', available_tickers, key='selected_stock',
                            format_func=lambda t: f"{t} · {df.loc[df.ticker==t,'name'].iloc[0]}")
    stock = next(s for s in stocks if s['ticker'] == selected)
    st.subheader(f"{stock['name']} ({selected})")
    if stock.get('is_new'):
        st.success('🆕 Neu im heutigen Scan')
    if stock.get('first_seen'):
        st.caption(f"Erstmals erfasst: {stock['first_seen']}")
    if stock.get('discovery_source') and stock['discovery_source'] != 'Eigene Liste':
        st.caption(f"🔎 Automatisch entdeckt über {stock['discovery_source']}")
    x, y, z, w = st.columns(4)
    x.metric('Kurs', f"{stock['price']:.2f} {stock['currency']}")
    y.metric('Attraktivität', f"{stock['score']:.0f}/100")
    z.metric('Risiko (hoch = riskant)', f"{stock['risk_score']:.0f}/100")
    w.metric('Chancen-Risiko-Index', f"{stock['opportunity_risk_score']:.0f}/100")
    st.caption('Index = 70 % Attraktivität + 30 % (100 − Risiko). Keine Prognose, kein Kauf- oder Verkaufssignal.')
    hist = pd.DataFrame(stock.get('history', []))
    if not hist.empty:
        fig = px.line(hist, x='date', y='close', title='Kursverlauf der letzten 12 Monate (dividenden- und splitbereinigt)', labels={'date':'Datum','close':stock['currency']})
        st.plotly_chart(fig, use_container_width=True)
    left, right = st.columns(2)
    with left:
        st.markdown('#### Quantitative Chancen')
        for p in stock.get('positives', []):
            st.write('• ' + p)
    with right:
        st.markdown('#### Risiken und offene Fragen')
        for r in stock.get('risks', []):
            st.write('• ' + r)
    with st.expander('🧮 So setzt sich der Score zusammen (maximal 100 Punkte)', expanded=False):
        st.caption('Je höher der Wert, desto mehr Punkte vergibt das regelbasierte Modell. Die Gewichtungen sind fest und keine statistisch validierte Prognose. Fehlende Daten ergeben 0 Punkte.')
        weights = [
            ('correction', 'Kursrückgang', 25, '10–30 % unter Jahreshoch; starker Monatsverlust kann Bonus bringen.'),
            ('dividend', 'Dividendenrendite', 15, '3 Punkte je Prozent Rendite, maximal 15.'),
            ('profitability', 'Gewinnmarge', 15, '0,75 Punkte je Prozent Gewinnmarge.'),
            ('roe', 'Eigenkapitalrendite', 10, '0,5 Punkte je Prozent ROE.'),
            ('valuation', 'Forward-KGV', 15, 'Bis 12: 15 P.; bis 20: 10 P.; bis 30: 4 P.'),
            ('cashflow', 'Freier Cashflow', 10, 'Positiver freier Cashflow: 10 P.'),
            ('debt', 'Verschuldung', 10, 'Debt/Equity bis 100: 10 P.; bis 200: 5 P.'),
        ]
        parts = stock.get('score_parts') or {}
        for key, label, maximum, explanation in weights:
            points = float(parts.get(key, 0))
            a, b = st.columns([3, 1])
            a.markdown(f'**{label}**')
            b.markdown(f'**{points:g} / {maximum}**')
            st.progress(min(1.0, max(0.0, points / maximum)))
            st.caption(explanation)
        st.markdown(f"**Gesamt: {stock['score']:.1f} / 100 Punkte**")
    with st.expander('🛡️ Risiko-Score verstehen (0 = niedriger, 100 = höher)', expanded=False):
        st.caption('Heuristische Risikoeinschätzung auf Basis historischer Kurse und verfügbarer Finanzkennzahlen. Fehlende Daten werden neutral bis vorsichtig bewertet; 0 bedeutet nicht risikofrei.')
        risk_factors = [
            ('volatility', 'Kursschwankungen (annualisiert)', 20, 'Unter 20 %: 0 · 20–35 %: 7 · 35–55 %: 14 · ab 55 %: 20'),
            ('max_drawdown', 'Größter 1-Jahres-Kursverlust', 20, 'Bis 15 %: 0 · 15–30 %: 7 · 30–50 %: 14 · über 50 %: 20'),
            ('leverage', 'Verschuldung (Debt/Equity)', 20, 'Bis 50: 0 · bis 100: 6 · bis 200: 13 · darüber: 20'),
            ('profitability', 'Gewinnmarge', 15, 'Ab 15 %: 0 · 5–15 %: 5 · 0–5 %: 10 · negativ: 15'),
            ('cashflow', 'Freier Cashflow', 10, 'Positiv: 0 · negativ/0: 10'),
            ('dividend', 'Extrem hohe Dividendenrendite', 5, 'Über 8 %: 5 · sonst: 0'),
            ('momentum', 'Kurzfristiger Kursrückgang', 10, '30T ab −5 %: 0 · −5 bis −15 %: 5 · unter −15 %: 10'),
        ]
        for key, label, maximum, explanation in risk_factors:
            points = float(stock.get('risk_parts', {}).get(key, 0))
            a, b = st.columns([3, 1])
            a.markdown(f'**{label}**')
            b.markdown(f'**{points:g} / {maximum}**')
            st.progress(min(1.0, max(0.0, points / maximum)))
            st.caption(explanation)
        st.caption('Die Punkteschwellen sind Modellannahmen, nicht statistisch kalibrierte Ausfallwahrscheinlichkeiten. Branchenunterschiede und Nachrichtenrisiken bleiben unberücksichtigt.')
    st.caption('Gewichtung: Kursrückgang 25 % · Dividende 15 % · Gewinnmarge 15 % · ROE 10 % · Bewertung 15 % · Cashflow 10 % · Verschuldung 10 %.')
    st.info('**Einordnung:** Screening-Score ≠ Kaufempfehlung. Kein verifizierter fairer Wert, kein Kursziel und keine persönliche Anlageberatung.')
    st.caption(f"Kursdatum: {stock.get('price_as_of', '?')} · Quelle: {stock.get('data_provider', '?')} · Abdeckung: {stock.get('data_coverage', '?')}/7 Felder")
    st.link_button('Kurs- und Nachrichtenansicht öffnen', f'https://finance.yahoo.com/quote/{selected}/')

    st.divider()
    st.subheader('🧠 KI-Investmentanalyse')
    st.caption('Analyse auf Knopfdruck. Nutzt die gespeicherten Kennzahlen und abrufbare Nachrichtenüberschriften; liest keine vollständigen Geschäftsberichte oder Artikel.')
    try:
        api_key = st.secrets.get('OPENAI_API_KEY', '')
    except Exception:
        api_key = ''
    if not api_key:
        st.warning('Für die KI-Analyse muss OPENAI_API_KEY in Streamlit Secrets hinterlegt werden. Der restliche Screener funktioniert weiterhin.')

    allowed, limit_message = check_ai_limit()
    st.caption(limit_message)
    if st.button('KI-Investmentanalyse erstellen', type='primary', disabled=not bool(api_key) or not allowed, key=f'ai_{selected}'):
        register_ai_request()
        with st.spinner('Nachrichten abrufen und Analyse erstellen …'):
            try:
                news = get_news(selected)
                report = build_analysis(stock, api_key, news)
                st.session_state['research_result'] = {'ticker': selected, 'report': report, 'news': news, 'snapshot': data.get('generated_at_utc')}
            except Exception as exc:
                st.error(f'Analyse fehlgeschlagen: {type(exc).__name__}. Prüfe API-Key, Guthaben und Verbindung. Details: {str(exc)[:250]}')
    result = st.session_state.get('research_result')
    if result and result['ticker'] == selected and result['snapshot'] == data.get('generated_at_utc'):
        st.markdown(result['report'])
        if result['news']:
            st.markdown('#### Abrufbare Nachrichtenlinks')
            for n in result['news']:
                st.markdown(f"- [{n['title']}]({n['url']}) — {n['source']} ({n['published']})")
        else:
            st.caption('Keine Nachrichten-Metadaten abrufbar. Ursachen des Kursrückgangs bleiben ungeprüft.')
        st.download_button('Analyse als Markdown herunterladen', result['report'], file_name=f'{selected.replace("/", "_")}_research.md', mime='text/markdown')

with st.expander('Scan-Fehler'):
    st.json(data.get('errors', []))
st.caption('Scores sind heuristisch und zwischen Branchen nur begrenzt vergleichbar. Keine automatische Orderausführung.')
