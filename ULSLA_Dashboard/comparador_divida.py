"""Comparações de snapshots mensais de dívida, por contraparte, situação, documento e classificação."""
from functools import reduce
import pandas as pd
import plotly.express as px
import streamlit as st
from ulsla_branding import period_selectbox
from divida_xml import load_snapshot

STATUS={'P1':'P1 · Em conferência','P2':'P2 · Conferida','NC':'NC · Nota de crédito'}

def eur(v):
    if pd.isna(v):return '—'
    return f'{v:,.2f} €'.replace(',','X').replace('.',',').replace('X','.')

def delta_style(value):
    if pd.isna(value) or value==0:return ''
    return 'color:#b42318;font-weight:600' if value>0 else 'color:#16803c;font-weight:600'

def delta_eur(v):
    return (('▲ ' if v>0 else '▼ ' if v<0 else '● ')+eur(v)) if pd.notna(v) else '—'

def delta_pct(v):
    return (('▲ ' if v>0 else '▼ ' if v<0 else '● ')+f'{v:+.1f} %') if pd.notna(v) else '—'

def compare_tables(dfs, periods, dims, allowed_types=None, supplier=None, rubric=None):
    """Outer-join por chave uniforme; ausência num snapshot completo equivale a zero.

    Todos os filtros aplicam-se antes da soma e nunca misturam P1 com P2.
    """
    values=[]
    for period,raw in zip(periods,dfs):
        df=raw.copy()
        if df.empty:continue
        df['ValorDoc']=pd.to_numeric(df.ValorDoc,errors='coerce').fillna(0)
        if allowed_types is not None:df=df[df.TipoDocCentral.isin(allowed_types)]
        if supplier:df=df[df.NifEntidade.astype(str).isin(supplier)]
        if rubric:df=df[df.ClassificadorEconomico.astype(str).isin(rubric)]
        val=df.groupby(dims,dropna=False,as_index=False)['ValorDoc'].sum().rename(columns={'ValorDoc':period})
        values.append(val)
    if not values:return pd.DataFrame(columns=dims+periods)
    result=reduce(lambda x,y:pd.merge(x,y,on=dims,how='outer'),values).fillna({p:0 for p in periods})
    for p in periods:
        if p not in result:result[p]=0.0
    result['Total selecionado']=result[periods].abs().sum(axis=1)
    return result.sort_values('Total selecionado',ascending=False).drop(columns='Total selecionado').reset_index(drop=True)

def all_status_metrics(dfs, periods):
    entries=[]
    for p,df in zip(periods,dfs):
        s=df.groupby('TipoDocCentral').ValorDoc.sum()
        p1=float(s.get('P1',0));p2=float(s.get('P2',0));nc=float(s.get('NC',0))
        entries.extend([{'Período':p,'Indicador':i,'Valor (€)':v} for i,v in [('P1 — Em conferência',p1),('P2 — Conferidas',p2),('NC — Notas de crédito',nc),('P2 líquido de NC',p2+nc),('Total P1 + P2 líquido',p1+p2+nc)]])
    return pd.DataFrame(entries)

def render(root, history, initial_period=None):
    st.subheader('Comparação de dívida entre períodos')
    st.caption('Compara até 3 fechos XML por valor global, fornecedor, estado P1/P2/NC, tipo de documento e classificação económica. Os valores são saldos à data de cada fecho, não fluxos do mês.')
    full_periods=sorted([p for p,h in history.items() if 'Dividas' in h.get('tipos',[])],reverse=True)
    if len(full_periods)<2:
        st.info('Está disponível apenas um fecho de dívida. Para obter desvios, importa também o ficheiro Dividas.xml de outro mês. O histórico existente será mantido.')
        if not full_periods:return
    count=period_selectbox('Número de períodos',options=[1,2,3] if len(full_periods)>=3 else ([1,2] if len(full_periods)>=2 else [1]),index=1 if len(full_periods)>=2 else 0,key='compare_debt_count')
    cols=st.columns(count)
    choices=[]
    for i,col in enumerate(cols):
        with col:
            choices.append(period_selectbox(f'Período {i+1}',full_periods,index=min(i,len(full_periods)-1),key=f'compare_debt_period_{i}'))
    if len(set(choices))!=len(choices):
        st.warning('Seleciona fechos diferentes para uma comparação válida.')
        return
    choices=sorted(choices)
    dfs=[load_snapshot(root,p,'Dividas') for p in choices]
    if any(x.empty for x in dfs):
        st.warning('Existem períodos selecionados sem detalhe de dívida guardado. Reimporta o XML desse fecho.')
        return
    st.caption('Períodos ordenados do mais antigo para o mais recente. Δ = recente − anterior; ▲ aumento (vermelho), ▼ diminuição (verde), sem pressupor que a variação é favorável.')
    indicators=all_status_metrics(dfs,choices)
    indicators_wide=indicators.pivot(index='Indicador',columns='Período',values='Valor (€)').reset_index()
    indicators_wide=indicators_wide[['Indicador']+choices]
    if count>1:
        for period in choices[1:]:
            indicators_wide[f'Δ {period} vs {choices[0]} (€)']=indicators_wide[period]-indicators_wide[choices[0]]
            denom=indicators_wide[choices[0]].replace(0,float('nan')).abs()
            indicators_wide[f'Δ {period} vs {choices[0]} (%)']=100*(indicators_wide[period]-indicators_wide[choices[0]])/denom
    st.markdown('#### Saldos globais e evolução')
    fmt={c:(delta_pct if '(%)' in str(c) else delta_eur if str(c).startswith('Δ ') else eur) for c in indicators_wide.columns if c!='Indicador'}
    delta_cols=[c for c in indicators_wide if str(c).startswith('Δ ')]
    st.dataframe(indicators_wide.style.format(fmt).map(delta_style,subset=delta_cols) if delta_cols else indicators_wide.style.format(fmt),hide_index=True,use_container_width=True)
    st.plotly_chart(px.bar(indicators[indicators.Indicador.isin(['P1 — Em conferência','P2 líquido de NC'])],x='Período',y='Valor (€)',color='Indicador',barmode='group',category_orders={'Período':choices},custom_data=['Valor (€)'],color_discrete_sequence=['#e79c45','#2176a6'],title='Dívida em conferência e dívida conferida líquida').update_traces(hovertemplate='%{x}<br>%{customdata[0]:,.2f} €<extra>%{fullData.name}</extra>'),use_container_width=True)
    st.markdown('#### Comparar por fornecedor, tipo de documento ou rubrica')
    mode=st.radio('Agrupamento', ['Fornecedor','Estado P1/P2/NC','Tipo de documento','Rubrica económica','Fornecedor × rubrica'],horizontal=True,key='debt_cmp_dimension')
    joined=pd.concat(dfs,ignore_index=True)
    states=sorted(joined.TipoDocCentral.dropna().astype(str).unique())
    chosen_states=st.multiselect('Estados incluídos',states,default=[x for x in ['P1','P2','NC'] if x in states],key='debt_cmp_states')
    left,right=st.columns(2)
    with left:
        supp=joined[['NifEntidade','NomeEntidade']].drop_duplicates().fillna('')
        supplier_options={str(r.NifEntidade)+' · '+str(r.NomeEntidade):str(r.NifEntidade) for r in supp.itertuples(index=False)}
        suppliers=st.multiselect('Filtrar fornecedores (facultativo)',list(supplier_options),key='debt_cmp_suppliers')
    with right:
        rubrics=sorted(joined.ClassificadorEconomico.fillna('').astype(str).unique().tolist())
        selected_rubrics=st.multiselect('Filtrar classificações económicas (facultativo)',rubrics,key='debt_cmp_rubrics')
    dims={'Fornecedor':['NifEntidade','NomeEntidade'], 'Estado P1/P2/NC':['TipoDocCentral'], 'Tipo de documento':['TipoDoc','TipoDocCentral'], 'Rubrica económica':['ClassificadorEconomico'], 'Fornecedor × rubrica':['NifEntidade','NomeEntidade','ClassificadorEconomico']}[mode]
    table=compare_tables(dfs,choices,dims,chosen_states,[supplier_options[s] for s in suppliers] if suppliers else None,selected_rubrics or None)
    if table.empty:
        st.info('Não há documentos para os filtros selecionados.')
        return
    for p in choices[1:]:
        table[f'Δ {p} vs {choices[0]} (€)']=table[p]-table[choices[0]]
        table[f'Δ {p} vs {choices[0]} (%)']=100*(table[p]-table[choices[0]])/table[choices[0]].abs().replace(0,float('nan'))
    amount_columns=[c for c in table if c in choices or ('Δ ' in c and '(€)' in c)]
    percent_columns=[c for c in table if 'Δ ' in c and '(%)' in c]
    formatting={c:(delta_eur if str(c).startswith('Δ ') else eur) for c in amount_columns}
    formatting.update({c:delta_pct for c in percent_columns})
    delta_cols=[c for c in table if str(c).startswith('Δ ')]
    st.dataframe(table.style.format(formatting).map(delta_style,subset=delta_cols) if delta_cols else table.style.format(formatting),hide_index=True,use_container_width=True,height=460)
    keycol=dims[0]
    if len(dims)>1:
        table['Descrição']=table[dims].astype(str).agg(' · '.join,axis=1)
        keycol='Descrição'
    chart=table.head(12).melt(id_vars=[keycol],value_vars=choices,var_name='Período',value_name='Valor (€)')
    chart['Valor formatado']=chart['Valor (€)'].map(eur)
    fig=px.bar(chart,x=keycol,y='Valor (€)',color='Período',barmode='group',custom_data=['Valor formatado'],category_orders={'Período':choices},color_discrete_map={p:['#0489a2','#f19b42','#526a98'][i] for i,p in enumerate(choices)},title='Principais rubricas ou fornecedores nos períodos selecionados')
    fig.update_traces(hovertemplate='%{x}<br>Valor: %{customdata[0]}<extra>%{fullData.name}</extra>')
    fig.update_layout(xaxis_tickangle=-25)
    st.plotly_chart(fig,use_container_width=True)
    st.download_button('Exportar comparação de dívida (CSV)',table.drop(columns=['Descrição'],errors='ignore').to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig'),file_name='comparacao_divida_'+ '_'.join(choices)+'.csv',mime='text/csv',key='export_debt_compare')
    st.caption('As notas de crédito são apresentadas com o sinal do XML. O agregado P2 líquido de NC é global e não atribui automaticamente cada NC a uma fatura P2; totais por fornecedor são somas dos documentos nos estados selecionados. Para comparar períodos, importa os respetivos ficheiros Dividas.xml.')
