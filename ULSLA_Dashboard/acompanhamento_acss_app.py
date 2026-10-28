from pathlib import Path
import streamlit as st
from ulsla_branding import period_selectbox
from ulsla_branding import hero
from acompanhamento_acss import read_periods,render
from periodos_snc_ap import periodo_legenda
st.set_page_config(page_title='ULSLA | Contratualização ACSS',layout='wide')
hero('ULSLA | Acompanhamento da Contratualização', 'Execução face ao contratualizado ACSS.', 'Resultados · Balanço · Fluxos de caixa')
ROOT=Path(__file__).resolve().parent
# Assinaturas dos ficheiros: atualizar sem guardar cópias desatualizadas dos dados.
paths=[ROOT/'dados_mensais.json',ROOT/'seed_2026_09.json']+list((ROOT/'dados_s3cp_xml').glob('*/*.json.gz'))
sig=tuple((str(p),p.stat().st_mtime_ns,p.stat().st_size) for p in paths if p.exists())
@st.cache_data(show_spinner=False,max_entries=2)
def load_data(signature):return read_periods(ROOT)
data=load_data(sig)
periods=sorted(k for k in data if (ROOT/'contratualizacao'/f'base_{k[:4]}.json').exists())
if not periods:st.info('Importe execução de um ano com contratualização disponível.')
else:
    period=period_selectbox('Período de referência',periods,index=len(periods)-1,format_func=periodo_legenda)
    render(ROOT,data,period)
