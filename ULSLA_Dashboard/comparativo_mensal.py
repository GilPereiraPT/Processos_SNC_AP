"""Mapas de análise comparativa para dois fechos de XML, sem imputar NC a faturas."""
import pandas as pd
import plotly.express as px
import streamlit as st
from divida_xml import load_snapshot


def _fmt_pct(x):
    return (('▲ ' if x>0 else '▼ ' if x<0 else '● ')+f'{x:+.1f} %') if pd.notna(x) else '—'

def _fmt_delta(x,euro):
    return (('▲ ' if x>0 else '▼ ' if x<0 else '● ')+euro(x)) if pd.notna(x) else '—'

def _delta_style(value):
    if pd.isna(value) or value==0:return ''
    return 'color:#b42318;font-weight:600' if value>0 else 'color:#16803c;font-weight:600'


def _compare(df_a, df_b, keys, pa, pb):
    """Ausência de chave num fecho completo corresponde a saldo zero nesse fecho."""
    def summed(df,p):
        if df.empty or not set(keys+['ValorDoc']).issubset(df.columns):
            return pd.DataFrame(columns=keys+[p])
        return df.groupby(keys,dropna=False,observed=True,as_index=False)['ValorDoc'].sum().rename(columns={'ValorDoc':p})
    both=pd.merge(summed(df_a,pa),summed(df_b,pb),on=keys,how='outer')
    for col in (pa,pb):both[col]=pd.to_numeric(both[col],errors='coerce').fillna(0)
    both['Variação (€)']=both[pb]-both[pa]
    both['Variação (%)']=100*both['Variação (€)']/both[pa].abs().replace(0,float('nan'))
    return both.sort_values('Variação (€)',key=lambda x:x.abs(),ascending=False).reset_index(drop=True)


def _table(df, euro, height=360):
    monetary={c:euro for c in df if c in ('Variação (€)',) or '(€)' in str(c)}
    # Os períodos identificam colunas de montantes, não valores numéricos de datas.
    monetary.update({c:euro for c in df if isinstance(c,str) and len(c)==7 and c[4]=='-' and c[:4].isdigit()})
    monetary.update({c:_fmt_pct for c in df if '(%)' in str(c)})
    if 'Variação (€)' in df.columns: monetary['Variação (€)']=lambda value:_fmt_delta(value,euro)
    delta_cols=[c for c in df.columns if c in ('Variação (€)','Variação (%)')]
    styled=df.style.format(monetary)
    if delta_cols:styled=styled.map(_delta_style,subset=delta_cols)
    st.dataframe(styled,hide_index=True,use_container_width=True,height=height)


def _chart(table,keys,pa,pb,euro,title,limit=15):
    if table.empty:return
    data=table.copy().head(limit)
    data['Elemento']=data[keys].fillna('').astype(str).agg(' · '.join,axis=1)
    shown=data.melt(id_vars='Elemento',value_vars=[pa,pb],var_name='Período',value_name='Valor (€)')
    shown['Euro']=shown['Valor (€)'].map(euro)
    fig=px.bar(shown,x='Valor (€)',y='Elemento',orientation='h',color='Período',barmode='group',category_orders={'Período':[pa,pb]},color_discrete_map={pa:'#0489a2',pb:'#f19b42'},custom_data=['Euro'],title=title)
    fig.update_traces(hovertemplate='%{y}<br>%{customdata[0]}<extra>%{fullData.name}</extra>')
    fig.update_layout(height=max(320,limit*30),yaxis={'categoryorder':'total ascending'})
    st.plotly_chart(fig,use_container_width=True)


def render_comparativo(root, history, pa, pb, tabela_euros, euro, enriched_debt, supplier_summary, payment_days):
    st.subheader('Mapas comparativos de dívida, pagamentos e créditos')
    pa,pb=sorted([pa,pb])
    st.caption(f'Período anterior: {pa} (azul) · período recente: {pb} (laranja). Variação = recente − anterior; percentagem sobre o valor absoluto do período anterior. Aumento ou diminuição não implica necessariamente melhoria ou agravamento.')
    da=load_snapshot(root,pa,'Dividas');db=load_snapshot(root,pb,'Dividas')
    if da.empty or db.empty:
        st.warning('Faltam os detalhes Dividas.xml de um dos períodos. Reimporta o fecho em falta para comparar.')
        return
    def state_totals(df):
        t=df.groupby('TipoDocCentral').ValorDoc.sum()
        p1=float(t.get('P1',0));p2=float(t.get('P2',0));nc=float(t.get('NC',0))
        return {'P1 · Em conferência':p1,'P2 · Conferidas':p2,'NC · Notas de crédito':nc,'P2 líquido de NC':p2+nc,'Total P1 + P2 líquido':p1+p2+nc}
    a=state_totals(da);b=state_totals(db)
    global_rows=[]
    for label in a:
        old=a[label];current=b[label]
        global_rows.append({'Indicador':label,pa:old,pb:current,'Variação (€)':current-old,'Variação (%)':100*(current-old)/abs(old) if old else float('nan')})
    st.markdown('#### Saldos globais e variações')
    _table(pd.DataFrame(global_rows),euro,240)
    st.caption('As notas de crédito mantêm o sinal de origem do XML; P2 líquido = P2 + NC. Não são imputadas a documentos individuais.')
    st.markdown('#### Antiguidade da dívida por vencimento')
    age_a=enriched_debt(da,pa);age_b=enriched_debt(db,pb)
    keys=['Estado vencimento','TipoDocCentral']
    ag=_compare(age_a[age_a.TipoDocCentral.isin(['P1','P2'])],age_b[age_b.TipoDocCentral.isin(['P1','P2'])],keys,pa,pb)
    if not ag.empty:_table(ag,euro,350)
    st.caption('Antiguidade avaliada à data de cada fecho; só são incluídas faturas P1/P2, sem imputação de NC.')
    st.markdown('#### Principais fornecedores · P2')
    supp=_compare(da[da.TipoDocCentral=='P2'],db[db.TipoDocCentral=='P2'],['NifEntidade','NomeEntidade'],pa,pb)
    if not supp.empty:
        _table(supp.head(50),euro)
        _chart(supp,['NomeEntidade'],pa,pb,euro,'Principais fornecedores P2 — comparação')
    st.markdown('#### Dívida por fornecedor, tipo de documento e rubrica')
    grouping=st.radio('Agrupamento',['Fornecedor','Estado P1/P2/NC','Tipo de documento','Rubrica económica','Fornecedor × rubrica'],horizontal=True,key='cmp_global_group')
    keys={'Fornecedor':['NifEntidade','NomeEntidade'],'Estado P1/P2/NC':['TipoDocCentral'],'Tipo de documento':['TipoDoc','TipoDocCentral'],'Rubrica económica':['ClassificadorEconomico'],'Fornecedor × rubrica':['NifEntidade','NomeEntidade','ClassificadorEconomico']}[grouping]
    union=pd.concat([da,db],ignore_index=True)
    types=sorted(union.TipoDocCentral.dropna().astype(str).unique())
    states=st.multiselect('Estado dos documentos',types,default=[x for x in ['P1','P2','NC'] if x in types],key='cmp_global_states')
    l,r=st.columns(2)
    with l:
        sups=union[['NifEntidade','NomeEntidade']].drop_duplicates().fillna('')
        options={str(x.NifEntidade)+' · '+str(x.NomeEntidade):str(x.NifEntidade) for x in sups.itertuples(index=False)}
        chosen_sups=st.multiselect('Filtrar fornecedores',list(options),key='cmp_global_suppliers')
    with r:
        r_options=sorted(union.ClassificadorEconomico.fillna('').astype(str).unique())
        chosen_r=st.multiselect('Filtrar rubricas económicas',r_options,key='cmp_global_rubrics')
    def filter_df(df):
        d=df[df.TipoDocCentral.isin(states)].copy()
        if chosen_sups:d=d[d.NifEntidade.astype(str).isin([options[x] for x in chosen_sups])]
        if chosen_r:d=d[d.ClassificadorEconomico.astype(str).isin(chosen_r)]
        return d
    detail=_compare(filter_df(da),filter_df(db),keys,pa,pb)
    if detail.empty:st.info('Sem documentos para os filtros selecionados.')
    else:
        _table(detail,euro,450)
        _chart(detail,keys,pa,pb,euro,'Comparação dos saldos por '+grouping.lower(),min(12,len(detail)))
        st.download_button('Exportar comparação (CSV)',detail.to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig'),file_name=f'comparacao_divida_{pa}_{pb}.csv',mime='text/csv',key='cmp_global_download')
    st.markdown('#### Pagamentos dos meses selecionados')
    paya=load_snapshot(root,pa,'Pagamentos');payb=load_snapshot(root,pb,'Pagamentos')
    if paya.empty or payb.empty:
        st.info('Para comparar pagamentos, importa Pagamentos.xml de ambos os períodos.')
    else:
        def pay_total(df):return float(df.ValorDoc.sum())
        x=pay_total(paya);y=pay_total(payb)
        pda=payment_days(paya);pdb=payment_days(payb)
        _table(pd.DataFrame([{'Indicador':'Pagamentos (€)',pa:x,pb:y,'Variação (€)':y-x,'Variação (%)':100*(y-x)/abs(x) if x else float('nan')}]),euro,95)
        st.caption(f'Prazo médio observado (emissão → pagamento): {pa}: {pda:.1f} dias' if pda is not None else f'{pa}: prazo indisponível')
        st.caption(f'{pb}: {pdb:.1f} dias' if pdb is not None else f'{pb}: prazo indisponível')
        st.caption('Pagamentos são fluxos de cada mês, não saldos em dívida. O prazo observado não equivale ao PMP oficial.')
        # Comparação de pagamentos por fornecedor e rubrica, se presentes nos XML.
        pay_keys=['NifEntidade','NomeEntidade']
        pays=_compare(paya,payb,pay_keys,pa,pb)
        if not pays.empty:
            st.markdown('##### Pagamentos por fornecedor')
            _table(pays.head(30),euro,280)
    st.markdown('#### Créditos a receber')
    ca=load_snapshot(root,pa,'Creditos');cb=load_snapshot(root,pb,'Creditos')
    if ca.empty or cb.empty:st.info('Para comparar créditos, importa Creditos.xml de ambos os períodos.')
    else:
        credits=_compare(ca,cb,['NifEntidade','NomeEntidade'],pa,pb)
        x=float(ca.ValorDoc.sum());y=float(cb.ValorDoc.sum())
        _table(pd.DataFrame([{'Indicador':'Créditos a receber (€)',pa:x,pb:y,'Variação (€)':y-x,'Variação (%)':100*(y-x)/abs(x) if x else float('nan')}]),euro,95)
        st.markdown('##### Créditos por cliente')
        if not credits.empty:_table(credits.head(30),euro,300)
