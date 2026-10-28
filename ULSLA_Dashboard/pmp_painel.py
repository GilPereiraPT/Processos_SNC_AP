"""Única fonte do PMP: extratos 31/43/45, balancetes 62 e terceiros."""
import pandas as pd
import streamlit as st

def combine(data, reference_month):
    from pmp_extratos import all_stored, reconcile_pmp
    try:
        frame=reconcile_pmp(all_stored(),data)
        limit=f"{reference_month[:4]}-T{(int(reference_month[5:7])-1)//3+1}"
        return frame[frame['Período']<=limit].sort_values('Período'),None
    except Exception as e:
        return pd.DataFrame(),str(e)

def render_cards(data, reference_month):
    table,error=combine(data,reference_month)
    if error:st.error('Erro no apuramento PMP: '+error)
    if table.empty:
        st.info('PMP por apurar: faltam extratos e/ou balancetes trimestrais.')
        return
    quarters=table.tail(4).to_dict('records')
    columns=st.columns(4)
    previous=None
    for col,row in zip(columns,quarters):
        value=row.get('PMP (dias)')
        valid=pd.notna(value)
        delta=f'{value-previous:+.1f} dias' if valid and previous is not None else None
        col.metric(row['Período'].replace('-T','T '),f'{value:.1f} dias' if valid else 'Por apurar',
                   delta=delta,delta_color='inverse',help=row.get('Estado','')+' | '+row.get('Observações',''))
        col.caption('Provisório · extratos + BA XML' if valid else 'Dados insuficientes')
        previous=float(value) if valid else None
    st.caption('PMP único: média da dívida dos 4 fechos trimestrais / aquisições 31+43+45 (todos os documentos exceto OD) + 62 (BA XML · NIF 999999990) dos 4 trimestres × 365. Sujeito a validação contabilística.')
    from pmp_reconciliacao import render as render_reconciliacao
    render_reconciliacao(table)
    with st.expander('Auditoria do PMP — composição e períodos',expanded=False):
        currency=[c for c in ['Aquisições 31/43/45 (€)','FSE 62 (€)','Aquisições totais (€)','Dívida (€)'] if c in table]
        st.dataframe(table.style.format({c:'{:,.2f} €' for c in currency}|{'PMP (dias)':'{:.1f}'},na_rep='—'),
                     hide_index=True,use_container_width=True)
        st.download_button('Exportar auditoria PMP (CSV)',table.to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig'),
                           'pmp_ulsla_auditoria.csv','text/csv',key='pmp_audit_top_export')
