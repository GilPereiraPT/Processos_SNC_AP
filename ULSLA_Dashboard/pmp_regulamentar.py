"""Apuramento trimestral do PMP segundo a estrutura de PMP_Ficheiro de apuramento_(Nuno).xlsx.

O Excel usa média aritmética dos saldos trimestrais / aquisições do mesmo intervalo * 365.
Não confundir com média dos dias das faturas efetivamente pagas.
"""
from pathlib import Path
import json
import pandas as pd
import plotly.express as px
import streamlit as st
from ulsla_branding import period_selectbox

DIVIDAS = {
    '221': '22.1 — Fornecedores',
    '222': '22.2 — Fornecedores',
    '225': '22.5 — Fornecedores',
    '226': '22.6 — Fornecedores',
    '2711': '27.1.1 — Fornecedores de investimentos',
    '2712': '27.1.2 — Fornecedores de investimentos',
    '278929': '27.8.9.2.9 — Outras contas a pagar',
}
AQUISICOES = {
    '31': '31 — Compras líquidas (devoluções, descontos e abatimentos deduzidos)',
    '62': '62 — Fornecimentos e serviços externos',
    '43': '43 — Aquisição onerosa de ativos fixos tangíveis',
    '453': '45.3 — Aquisição onerosa de ativos em curso',
    '450': '45.0 — Aquisição onerosa de bens de domínio público em curso',
}
PATH = Path(__file__).resolve().parent / 'dados_pmp.json'

def _load():
    if not PATH.exists(): return {}
    try:
        data = json.loads(PATH.read_text(encoding='utf-8'))
        return data if isinstance(data,dict) else {}
    except (ValueError,OSError):return {}

def _save(records):
    tmp=PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(records,indent=2,ensure_ascii=False),encoding='utf-8')
    tmp.replace(PATH)

def _num(x):
    if x is None or str(x).strip()=='':return None
    return float(x)

def _summary(records):
    rows=[]
    for per,record in sorted(records.items()):
        values=record.get('valores',{})
        if not all(_num(values.get(k)) is not None for k in (*DIVIDAS,*AQUISICOES)):
            rows.append({'Período':per,'Dívida (€)':None,'Aquisições acumuladas (€)':None,'Aquisições trimestre (€)':None,'PMP (dias)':None,'Estado':'Incompleto'})
            continue
        debt=sum(float(values[k]) for k in DIVIDAS)
        acquisitions=sum(float(values[k]) for k in AQUISICOES)
        rows.append({'Período':per,'Dívida (€)':debt,'Aquisições acumuladas (€)':acquisitions,'Aquisições trimestre (€)':None,'PMP (dias)':None,'Estado':'Pendente'})
    for idx,r in enumerate(rows):
        y,q=map(int,r['Período'].split('-T'))
        prior=f'{y}-T{q-1}' if q>1 else None
        previous=next((x for x in rows if x['Período']==prior),None)
        if r['Aquisições acumuladas (€)'] is None:continue
        if q>1 and (previous is None or previous['Aquisições acumuladas (€)'] is None):
            r['Estado']='Falta trimestre anterior';continue
        a=r['Aquisições acumuladas (€)'] - (previous['Aquisições acumuladas (€)'] if previous else 0)
        r['Aquisições trimestre (€)']=a
        if a<=0:
            r['Estado']='Aquisições não positivas';continue
        periods=[f'{y}-T{k}' for k in range(1,q+1)] if y==2023 else None
        if periods is None:
            # Janela móvel de 4 trimestres, conforme CA_PMP a partir de 2024.
            periods=[]
            for j in range(3,-1,-1):
                yy=y;qq=q-j
                while qq<=0:qq+=4;yy-=1
                periods.append(f'{yy}-T{qq}')
        window=[next((x for x in rows if x['Período']==p),None) for p in periods]
        if any(v is None or v['Dívida (€)'] is None or v['Aquisições trimestre (€)'] is None or v['Aquisições trimestre (€)']<=0 for v in window):
            r['Estado']='Histórico insuficiente';continue
        numerator=sum(v['Dívida (€)'] for v in window)/len(window)
        denominator=sum(v['Aquisições trimestre (€)'] for v in window)
        r['PMP (dias)']=numerator/denominator*365 if denominator>0 else None
        r['Estado']='Calculado' if r['PMP (dias)'] is not None else 'Sem aquisições'
    return pd.DataFrame(rows)

def render():
    st.subheader('PMP contabilístico — metodologia do ficheiro de apuramento')
    st.caption('Fonte metodológica: “PMP_Ficheiro de apuramento_(Nuno).xlsx” (separadores trimestrais e CA_PMP). Os valores são apurados a partir de saldos contabilísticos e aquisições; não correspondem aos dias médios das faturas pagas.')
    st.latex(r'PMP = \frac{\operatorname{media}(DF)}{\sum A}\times 365')
    st.caption('DF: dívidas a fornecedores no fim de cada trimestre. A: aquisições efetuadas no trimestre. Para 2023, o modelo utiliza os trimestres disponíveis desde o início do ano; a partir de 2024 aplica quatro trimestres móveis.')
    records=_load()
    with st.container(border=True):
        st.markdown('**Introdução ou atualização de valores**')
        c1,c2=st.columns(2)
        with c1:year=st.number_input('Ano',min_value=2023,max_value=2100,value=2026,step=1,key='pmp_year')
        with c2:quarter=period_selectbox('Trimestre',[1,2,3,4],key='pmp_quarter')
        period=f'{year}-T{quarter}'
        stored=records.get(period,{}).get('valores',{})
        st.info('Introduzir saldos credores das contas de fornecedores no fecho e **aquisições acumuladas desde 1 de janeiro**. Nos investimentos, introduzir aquisições onerosas do exercício, e não o saldo total de imobilizado. Não incluir contas-mãe e subcontas em simultâneo.')
        with st.form('pmp_entry'):
            c1,c2=st.columns(2)
            values={}
            with c1:
                st.markdown('**DF — Dívida a fornecedores (saldos no fecho)**')
                for key,label in DIVIDAS.items():
                    previous=stored.get(key)
                    values[key]=st.number_input(label,value=float(previous) if previous is not None else 0.,format='%.2f',key=f'pmp_{period}_{key}')
            with c2:
                st.markdown('**A — Aquisições acumuladas do ano**')
                for key,label in AQUISICOES.items():
                    previous=stored.get(key)
                    values[key]=st.number_input(label,value=float(previous) if previous is not None else 0.,format='%.2f',key=f'pmp_{period}_{key}')
            st.metric('DF a gravar',f"{sum(values[k] for k in DIVIDAS):,.2f} €".replace(',','X').replace('.',',').replace('X','.'))
            submitted=st.form_submit_button('Guardar apuramento trimestral',type='primary')
        if submitted:
            records[period]={'valores':values,'fonte':'Introdução manual — confirmar com balancete SNC-AP'}
            _save(records)
            st.success(f'Apuramento {period} guardado em dados_pmp.json.')
    if not records:
        st.warning('Ainda não existem trimestres registados. O Excel fornecido não contém valores de dívida e aquisições preenchidos para calcular um PMP numérico.')
        return
    summary=_summary(records)
    last=summary[summary['PMP (dias)'].notna()]
    if not last.empty:
        latest=last.iloc[-1]
        st.metric('Último PMP calculado',f"{latest['PMP (dias)']:.1f} dias",help=f"Trimestre: {latest['Período']}")
    st.dataframe(summary.style.format({'Dívida (€)':'{:,.2f} €','Aquisições acumuladas (€)':'{:,.2f} €','Aquisições trimestre (€)':'{:,.2f} €','PMP (dias)':'{:.1f}'},na_rep='—'),hide_index=True,use_container_width=True)
    if not last.empty:
        st.plotly_chart(px.line(last,x='Período',y='PMP (dias)',markers=True,title='Evolução trimestral do PMP'),use_container_width=True)
    st.download_button('Exportar apuramento PMP (CSV)',summary.to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig'),'apuramento_pmp.csv','text/csv')
    st.caption('Controlo: fórmula anualizada a 365 dias. O indicador só é apresentado quando os trimestres e respetivos acumulados necessários estão completos. Confirmar a elegibilidade e a classificação SNC-AP dos valores antes da utilização para reporte oficial.')
