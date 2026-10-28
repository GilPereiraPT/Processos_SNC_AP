"""Apuramento automático e rastreável do PMP sobre os balancetes SNC-AP importados.

O resultado é indicativo até validação da composição das aquisições onerosas,
regularizações e reconciliação dos valores com o modelo de reporte.
"""
from datetime import date
import re
import pandas as pd
import plotly.express as px
import streamlit as st
from ulsla_branding import period_selectbox

DEBT = {'221':'22.1 Fornecedores','222':'22.2 Fornecedores','225':'22.5 Faturas em receção/conferência','226':'22.6 Factoring','2711':'27.1.1 Fornecedores de investimentos','2712':'27.1.2 Fornecedores de investimentos','278929':'27.8.9.2.9 Outras contas a pagar'}
ACQ = {'31':'31 Compras líquidas','62':'62 Fornecimentos e serviços externos','43':'43 Ativos fixos tangíveis','453':'45.3 Ativos fixos em curso','450':'45.0 Bens de domínio público em curso'}

def terminal_rows(contas, prefix):
    """Selecciona os descendentes terminais, sem somar contas-mãe e contas-filhas."""
    matches = [str(k) for k in contas if re.fullmatch(r'\d+',str(k)) and str(k).startswith(prefix)]
    return [(k,contas[k]) for k in matches if not any(other!=k and other.startswith(k) for other in matches)]

def val(record, field):
    try:
        v=record.get(field)
        return float(v) if v is not None else None
    except (ValueError,TypeError):return None

def metric(contas,prefix,kind):
    leaf=terminal_rows(contas,prefix)
    if not leaf:return None,0,[]
    field='saldo_credor' if kind=='debt' else 'debito_acumulado'
    rows=[]
    for code,account in leaf:
        debit=val(account,'debito_acumulado')
        credit=val(account,'credito_acumulado')
        debtor=val(account,'saldo_devedor')
        creditor=val(account,'saldo_credor')
        if kind=='debt':
            amount=max(0.,(creditor or 0.)-(debtor or 0.)) if creditor is not None and debtor is not None else None
        else:
            amount=(debit-credit) if debit is not None and credit is not None else None
        rows.append({'Conta':code,'Descrição':account.get('descricao',''),'Valor (€)':amount,'Débito acumulado (€)':debit,'Crédito acumulado (€)':credit,'Saldo devedor (€)':debtor,'Saldo credor (€)':creditor})
    values=[r['Valor (€)'] for r in rows]
    return (sum(values) if all(v is not None for v in values) else None),len(leaf),rows

def _quarter(per):return f'{per[:4]}-T{(int(per[5:7])-1)//3+1}'

def quarter_snapshots(data):
    results={}
    for period,rec in sorted(data.items()):
        if not re.fullmatch(r'20\d\d-(0[1-9]|1[0-2])',period):continue
        if rec.get('contas_balancete'):
            quarter=_quarter(period)
            if quarter not in results or period>results[quarter][0]:results[quarter]=(period,rec)
    return results

def extract(data):
    snapshots=quarter_snapshots(data)
    all_records={}
    for quarter,(month,rec) in sorted(snapshots.items()):
        contas=rec['contas_balancete']; debt={};acq={}; detail=[];missing=[]
        for k,label in DEBT.items():
            v,n,rows=metric(contas,k,'debt');debt[k]=v
            # Conta sem correspondência não é interpretada como zero salvo quando confirmada a inexistência.
            if v is None: debt[k]=0.0  # Conta ausente: sem lançamento identificado; evidenciar em auditoria.
            for r in rows:detail.append({'Período':month,'Natureza':'DF','Grupo':label,**r})
        for k,label in ACQ.items():
            v,n,rows=metric(contas,k,'acq');acq[k]=v
            if v is None: acq[k]=0.0  # Conta ausente: sem movimento identificado.
            for r in rows:detail.append({'Período':month,'Natureza':'A','Grupo':label,**r})
        all_records[quarter]={'mes':month,'debt':debt,'acq':acq,'missing':missing,'detail':detail,
           'end_of_quarter':int(month[5:7])%3==0,'absent':[k for k in (*DEBT,*ACQ) if not terminal_rows(contas,k)]}
    return all_records

def summary(data):
    records=extract(data); output=[]
    for period,rec in sorted(records.items()):
        year,quarter=period.split('-T');q=int(quarter); year=int(year)
        d=rec['debt'];acq=rec['acq'];missing=rec['missing']
        debt_total=sum(d.values()) if all(x is not None for x in d.values()) else None
        acq_cum=sum(acq.values()) if all(x is not None for x in acq.values()) else None
        prev=f'{year}-T{q-1}' if q>1 else None
        prior=records.get(prev) if prev else None
        previous_cum=sum(prior['acq'].values()) if prior and all(x is not None for x in prior['acq'].values()) else None
        acq_q=(acq_cum-(previous_cum if prev else 0)) if acq_cum is not None and (not prev or previous_cum is not None) else None
        row={'Período':period,'Fecho contabilístico':rec['mes'],'Dívida DF (€)':debt_total,'Aquisições acumuladas (€)':acq_cum,'Aquisições trimestre (€)':acq_q,'PMP indicativo (dias)':None,'Estado':'','Observações':''}
        issues=[]
        if not rec['end_of_quarter']:issues.append('Falta fecho do último mês do trimestre')
        if missing:issues.append('Contas sem correspondência: '+', '.join(missing))
        if acq_q is not None and acq_q<=0:issues.append('Aquisições trimestrais nulas/negativas')
        if prev and (prior is None or previous_cum is None):issues.append('Falta acumulado do trimestre anterior')
        # Uso sempre 4 trimestres, conforme a janela móvel do modelo a partir de 2024.
        window=[]
        for step in range(3,-1,-1):
            y=year; z=q-step
            while z<=0:y-=1;z+=4
            window.append(f'{y}-T{z}')
        if year==2023:window=[f'2023-T{k}' for k in range(1,q+1)]
        pieces=[]
        for key in window:
            other=records.get(key)
            if not other or not other['end_of_quarter'] or other['missing']:
                issues.append('Janela incompleta: '+key);continue
            oy,oq=key.split('-T');oq=int(oq)
            this_cum=sum(other['acq'].values())
            prevk=f'{oy}-T{oq-1}' if oq>1 else None
            previous=records.get(prevk) if prevk else None
            if prevk and (not previous or previous['missing']):
                issues.append('Falta base de aquisições: '+prevk);continue
            a=this_cum-(sum(previous['acq'].values()) if previous else 0)
            debt=sum(other['debt'].values())
            if a<=0:issues.append('Aquisições não positivas: '+key)
            pieces.append((debt,a))
        if not issues and len(pieces)==len(window) and sum(a for _,a in pieces)>0:
            row['PMP indicativo (dias)']=365*(sum(d for d,_ in pieces)/len(pieces))/sum(a for _,a in pieces)
            row['Estado']='Provisório — requer validação'
        else:row['Estado']='Dados insuficientes'
        row['Observações']='; '.join(dict.fromkeys(issues))
        output.append(row)
    return pd.DataFrame(output),records

def render(data):
    st.subheader('PMP — cálculo automático com balancetes SNC-AP')
    st.caption('Os valores são extraídos dos balancetes analíticos já importados. Não é necessário voltar a carregar os PDF nem introduzir saldos manualmente.')
    st.latex(r'PMP = 365 \times \frac{\operatorname{média}(DF_{trimestre})}{\sum A_{trimestre}}')
    table,records=summary(data)
    if table.empty:
        st.warning('Ainda não existem balancetes analíticos importados. Importa os quatro PDF SNC-AP mensais no menu lateral.');return
    st.info('Apuramento automático **indicativo**: 31/62 usam movimentos líquidos acumulados; 43/45.3/45.0 usam variação dos movimentos contabilísticos acumulados. Estes movimentos podem conter transferências, reclassificações e regularizações que não são aquisições onerosas. Validar com o mapa de investimento antes de reporte oficial.')
    good=table[table['PMP indicativo (dias)'].notna()]
    if len(good):
        last=good.iloc[-1];st.metric('Último PMP indicativo',f"{last['PMP indicativo (dias)']:.1f} dias",help=last['Período'])
    else:st.warning('Não existem ainda quatro trimestres completos e consistentes para produzir um PMP indicativo. Os motivos estão identificados na tabela.')
    fmt={c:'{:,.2f} €' for c in ['Dívida DF (€)','Aquisições acumuladas (€)','Aquisições trimestre (€)']}
    fmt['PMP indicativo (dias)']='{:.1f}'
    st.dataframe(table.style.format(fmt,na_rep='—'),hide_index=True,use_container_width=True)
    if len(good):st.plotly_chart(px.line(good,x='Período',y='PMP indicativo (dias)',markers=True,title='Evolução trimestral do PMP indicativo'),use_container_width=True)
    q=period_selectbox('Auditoria do apuramento — trimestre',sorted(records,reverse=True),key='pmp_audit_quarter')
    rec=records[q]
    st.caption('Balancete utilizado: '+rec['mes']+' · '+('Fecho de trimestre' if rec['end_of_quarter'] else 'Fecho intermédio — trimestre incompleto'))
    if rec['absent']:st.warning('Contas não encontradas (tratadas como zero apenas no cálculo indicativo; confirmar inexistência): '+', '.join(rec['absent']))
    grouped=[]
    for k,label in DEBT.items():grouped.append({'Natureza':'Dívida','Conta SNC-AP':k,'Descrição':label,'Valor (€)':rec['debt'][k]})
    for k,label in ACQ.items():grouped.append({'Natureza':'Aquisições — acumulado','Conta SNC-AP':k,'Descrição':label,'Valor (€)':rec['acq'][k]})
    st.dataframe(pd.DataFrame(grouped).style.format({'Valor (€)':'{:,.2f} €'},na_rep='—'),hide_index=True,use_container_width=True)
    with st.expander('Ver contas terminais incluídas (rastreabilidade)'):
        details=pd.DataFrame(rec['detail'])
        if not details.empty:st.dataframe(details.style.format({c:'{:,.2f} €' for c in details if '(€)' in c},na_rep='—'),hide_index=True,use_container_width=True)
    st.download_button('Exportar apuramento automático (CSV)',table.to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig'),'pmp_automatico_ulsla.csv','text/csv')
    st.caption('A ausência de uma conta no balancete não equivale automaticamente a saldo zero. Não há preenchimento fictício dos meses ou trimestres em falta.')
