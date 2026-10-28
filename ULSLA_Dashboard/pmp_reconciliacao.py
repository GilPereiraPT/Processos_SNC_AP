"""Auditoria entre o PMP calculado e os mapas oficiais entregues pela ULSLA.
Referências fixas para reconciliação, nunca usadas para alterar o PMP calculado.
"""
import pandas as pd
import streamlit as st
from ulsla_branding import period_selectbox

# Números transcritos dos mapas de PMP enviados, em EUR e dias.
OFICIAL = {
    '2025-T4': {'PMP':112.32,'Fornecedores':11647148.63,'Investimentos':5084623.31,'Outros':2321797.18,'Divida':19053569.12,'31':18569267.45,'62':52212734.39,'43':2419473.00,'45':11245696.78,'Aquisições':84447171.62},
    '2026-T1': {'PMP':99.04,'Fornecedores':5613815.40,'Investimentos':6004638.16,'Outros':2071207.29,'Divida':13689660.85,'31':4357619.47,'62':12744459.59,'43':2051628.32,'45':2083749.28,'Aquisições':21237456.66},
    '2026-T2': {'PMP':89.03,'Fornecedores':9820781.02,'Investimentos':9825981.66,'Outros':2466400.68,'Divida':22113163.36,'31':8501182.41,'62':26863913.41,'43':2832205.65,'45':5643505.77,'Aquisições':43840807.24},
    '2026-T3': {'PMP':83.65,'Fornecedores':16621619.72,'Investimentos':11138968.79,'Outros':2485937.71,'Divida':30246526.22,'31':14211190.38,'62':40906343.83,'43':5212247.19,'45':9669858.05,'Aquisições':69999639.45},
}

def eur(v):
    if pd.isna(v): return '—'
    n=float(v)
    txt=f'{abs(n):,.2f}'.replace(',','@').replace('.',',').replace('@','.')+' €'
    return f'({txt})' if n < 0 else txt

def build_reconciliation(table):
    """Valores BA como saldos; compras/investimentos como acumulados no ano.
    Não presume meses/trimestres não importados.
    """
    if table is None or table.empty: return pd.DataFrame(),pd.DataFrame()
    keyed={r['Período']:r for r in table.to_dict('records')}
    pairs=[('Fornecedores','Fornecedores BA (€)'),('Investimentos','Investimentos BA (€)'),('Outros','Outros credores BA (€)'),('Divida','Dívida (€)'),('31','Compras 31 trimestre (€)'),('62','FSE 62 (€)'),('43','Ativos 43 trimestre (€)'),('45','Investimento 45 trimestre (€)'),('Aquisições','Aquisições totais (€)')]
    detail=[];overview=[]
    for period,off in OFICIAL.items():
        row=keyed.get(period,{})
        year=period[:4]; t=int(period[-1])
        # Só apurar o acumulado quando todos os trimestres relevantes estão presentes.
        cumul={}
        for label,column in [('31','Compras 31 trimestre (€)'),('62','FSE 62 (€)'),('43','Ativos 43 trimestre (€)'),('45','Investimento 45 trimestre (€)'),('Aquisições','Aquisições totais (€)')]:
            vals=[keyed.get(f'{year}-T{k}',{}).get(column) for k in range(1,t+1)]
            cumul[label]=sum(float(v) for v in vals) if all(v is not None and pd.notna(v) for v in vals) else None
        for label,col in pairs:
            val=cumul[label] if label in cumul else row.get(col)
            difference=float(val)-off[label] if val is not None and pd.notna(val) else None
            detail.append({'Trimestre':period,'Componente':label,'Oficial (€)':off[label],'Dashboard (€)':val,'Diferença (€)':difference,'Fonte':('Extrato 31/43/45; sem OD' if label in ('31','43','45') else 'BA; NIF 999999990' if label in ('Fornecedores','Investimentos','Outros','Divida','62') else 'BA + extratos')})
        calc=row.get('PMP (dias)')
        overview.append({'Trimestre':period,'Oficial (dias)':off['PMP'],'Dashboard (dias)':calc,'Desvio (dias)':float(calc)-off['PMP'] if calc is not None and pd.notna(calc) else None,'Estado':row.get('Estado','Dados indisponíveis')})
    return pd.DataFrame(overview),pd.DataFrame(detail)

def render(table):
    with st.expander('Reconciliação PMP oficial · 2025 T4 — 2026 T3',expanded=False):
        st.caption('Referências transcritas dos quatro mapas oficiais enviados. Não corrigem nem substituem os cálculos automáticos. A fórmula segue a RCM n.º 34/2008: média dos saldos de dívida de quatro trimestres / aquisições desses quatro trimestres × 365.')
        overview,detail=build_reconciliation(table)
        st.dataframe(overview.style.format({'Oficial (dias)':'{:.2f}','Dashboard (dias)':'{:.2f}','Desvio (dias)':'{:+.2f}'},na_rep='—'),hide_index=True,use_container_width=True)
        available=[k for k in OFICIAL if k in detail['Trimestre'].values]
        selected=period_selectbox('Trimestre a reconciliar',available,index=len(available)-1,key='pmp_recon_period')
        d=detail[detail['Trimestre']==selected].copy()
        st.dataframe(d.style.format({c:eur for c in ('Oficial (€)','Dashboard (€)','Diferença (€)')}),hide_index=True,use_container_width=True)
        st.caption('A dívida é um saldo de fecho; 31/62/43/45 são acumulados de janeiro até ao trimestre selecionado. Se faltarem trimestres para obter o acumulado, a linha fica sem valor calculado. Diferenças do PMP podem depender também dos quatro fechos anteriores ao período escolhido.')
        st.download_button('Descarregar reconciliação completa (CSV)',detail.to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig'),file_name='pmp_reconciliacao_oficial.csv',mime='text/csv',key='pmp_recon_download')
