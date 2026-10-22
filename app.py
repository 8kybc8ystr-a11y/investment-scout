import json
from pathlib import Path
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title='Investment Scout V1', page_icon='📈', layout='wide')
ROOT = Path(__file__).resolve().parent
st.title('📈 Investment Scout')
st.caption('Globaler Dividenden- & Kursrückgang-Screener · Research, keine Anlageberatung')

snapshot = ROOT / 'data' / 'latest.json'
if not snapshot.exists():
    st.warning('Noch keine Marktdaten vorhanden. Bitte zunächst `python scanner.py` ausführen oder den geplanten GitHub-Scan abwarten.')
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

df = pd.DataFrame([{k:v for k,v in s.items() if k not in ('history','positives','risks','score_parts')} for s in stocks])
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

c1,c2,c3,c4 = st.columns(4)
c1.metric('Analysierte Aktien', data.get('success_count',len(stocks)))
c2.metric('Treffer nach Filtern',len(filtered))
c3.metric('Höchster Score', f"{filtered['score'].max():.0f}/100" if len(filtered) else '–')
c4.metric('Datenstand (UTC)', data.get('generated_at_utc','?')[:16].replace('T',' '))
if data.get('errors'):
    st.caption(f"{len(data['errors'])} Aktien konnten nicht verarbeitet werden. Details unten.")

st.subheader('Investment-Ranking')
cols = ['ticker','name','region','sector','score','price','currency','change_30d','drawdown_1y','dividend_yield_pct','forward_pe','data_coverage']
st.dataframe(filtered[cols].rename(columns={'ticker':'Symbol','name':'Unternehmen','region':'Region','sector':'Sektor','score':'Score','price':'Kurs','currency':'Währung','change_30d':'30T %','drawdown_1y':'Abstand Hoch %','dividend_yield_pct':'Dividende %','forward_pe':'Forward-KGV','data_coverage':'Datenfelder / 7'}), use_container_width=True, hide_index=True)

if len(filtered):
    selected = st.selectbox('Aktie im Detail untersuchen', filtered['ticker'].tolist(), format_func=lambda t: f"{t} · {df.loc[df.ticker==t,'name'].iloc[0]}")
    stock = next(s for s in stocks if s['ticker']==selected)
    st.subheader(f"{stock['name']} ({selected})")
    x,y,z = st.columns(3)
    x.metric('Kurs',f"{stock['price']:.2f} {stock['currency']}")
    y.metric('Score',f"{stock['score']:.0f}/100")
    z.metric('Dividendenrendite',f"{stock['dividend_yield_pct']:.2f} %" if stock.get('dividend_yield_pct') is not None else 'Keine Daten')
    hist = pd.DataFrame(stock.get('history',[]))
    if not hist.empty:
        fig = px.line(hist, x='date', y='close', title='Kursverlauf (adjustiert, bis zu 130 Handelstage)', labels={'date':'Datum','close':stock['currency']})
        st.plotly_chart(fig, use_container_width=True)
    left,right = st.columns(2)
    with left:
        st.markdown('#### Quantitative Chancen')
        for p in stock['positives']: st.write('• '+p)
    with right:
        st.markdown('#### Risiken und offene Fragen')
        for r in stock['risks']: st.write('• '+r)
    st.markdown('#### Score-Zerlegung')
    st.bar_chart(pd.Series(stock['score_parts'],name='Punkte'))
    st.info('Wichtig: Dies ist eine regelbasierte Vorprüfung, **keine KI-generierte Fundamentalanalyse und kein berechneter Fair Value**. Vor einer Entscheidung müssen Quartalsbericht, aktuelle Nachrichten, Dividendenhistorie, Bilanz und Bewertung mit Branchenvergleich geprüft werden.')
    st.caption(f"Kursdatum: {stock['price_as_of']} · Quelle: {stock['data_provider']} · Abdeckung: {stock['data_coverage']}/7 Felder")
    st.link_button('Kurs- und Nachrichtenansicht öffnen',f"https://finance.yahoo.com/quote/{selected}/")
with st.expander('Scan-Fehler'):
    st.json(data.get('errors',[]))
st.caption('Scores sind heuristisch und zwischen Branchen nur begrenzt vergleichbar. Hohe Dividendenrendite und Kursrückgang können Warnsignale sein. Keine automatische Orderausführung.')
