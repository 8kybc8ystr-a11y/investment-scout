import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from ai_research import get_news, build_analysis
from security import require_login, check_ai_limit, register_ai_request

st.set_page_config(page_title='Investment Scout V2', page_icon='📈', layout='wide')
require_login()

ROOT = Path(__file__).resolve().parent
st.title('📈 Investment Scout')
st.caption('Globaler Dividenden- & Kursrückgang-Screener · KI-Research auf Abruf · Keine Anlageberatung')

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
    search = st.text_input('Aktienname / Symbol')
    st.divider()
    st.caption('Datenanbieter: Yahoo Finance (inoffizielle Schnittstelle). Kennzahlen können fehlen, verzögert oder falsch sein. Kein Echtzeit-Feed.')

filtered = df[df['region'].isin(regions) & (df['score'] >= min_score)].copy()
filtered = filtered[filtered['dividend_yield_pct'].fillna(-1) >= min_dividend]
if only_corrections:
    filtered = filtered[filtered['drawdown_1y'].fillna(0) <= -15]
if search:
    filtered = filtered[filtered['ticker'].str.contains(search, case=False, regex=False) | filtered['name'].str.contains(search, case=False, regex=False)]

c1, c2, c3, c4 = st.columns(4)
c1.metric('Analysierte Aktien', data.get('success_count', len(stocks)))
c2.metric('Treffer nach Filtern', len(filtered))
c3.metric('Höchster Score', f"{filtered['score'].max():.0f}/100" if len(filtered) else '–')
c4.metric('Datenstand (UTC)', data.get('generated_at_utc', '?')[:16].replace('T', ' '))
if data.get('errors'):
    st.caption(f"{len(data['errors'])} Aktien konnten nicht verarbeitet werden. Details unten.")

st.subheader('Investment-Ranking')
cols = ['ticker', 'name', 'region', 'sector', 'score', 'price', 'currency', 'change_30d', 'drawdown_1y', 'dividend_yield_pct', 'forward_pe', 'data_coverage']
st.dataframe(filtered[cols].rename(columns={'ticker':'Symbol','name':'Unternehmen','region':'Region','sector':'Sektor','score':'Score','price':'Kurs','currency':'Währung','change_30d':'30T %','drawdown_1y':'Abstand Hoch %','dividend_yield_pct':'Dividende %','forward_pe':'Forward-KGV','data_coverage':'Datenfelder / 7'}), use_container_width=True, hide_index=True)

if len(filtered):
    selected = st.selectbox('Aktie im Detail untersuchen', filtered['ticker'].tolist(), format_func=lambda t: f"{t} · {df.loc[df.ticker==t,'name'].iloc[0]}")
    stock = next(s for s in stocks if s['ticker'] == selected)
    st.subheader(f"{stock['name']} ({selected})")
    x, y, z = st.columns(3)
    x.metric('Kurs', f"{stock['price']:.2f} {stock['currency']}")
    y.metric('Score', f"{stock['score']:.0f}/100")
    z.metric('Dividendenrendite', f"{stock['dividend_yield_pct']:.2f} %" if stock.get('dividend_yield_pct') is not None else 'Keine Daten')
    hist = pd.DataFrame(stock.get('history', []))
    if not hist.empty:
        fig = px.line(hist, x='date', y='close', title='Kursverlauf (adjustiert, bis zu 130 Handelstage)', labels={'date':'Datum','close':stock['currency']})
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
    st.markdown('#### Score-Zerlegung')
    st.bar_chart(pd.Series(stock.get('score_parts', {}), name='Punkte'))
    st.info('Die quantitative Bewertung ist regelbasiert. Es liegt **kein verifizierter Fair Value** vor.')
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
