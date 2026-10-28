"""Simulação de gestão: produção acumulada valorizada ao CP 2023.
Não reconhece rendimentos contabilísticos e não distribui produção por CC filhos.
"""
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import pandas as pd


def carregar_fontes(root):
    production=pd.read_csv(Path(root)/'producao_cp_2026_03.csv',sep=';',dtype={'cc_producao':str}).fillna('')
    links=pd.read_csv(Path(root)/'correspondencia_cc_producao.csv',sep=';',dtype=str).fillna('')
    if production.duplicated(['ano','mes','cc_producao']).any():
        raise ValueError('Produção duplicada por período e CC; agregar as linhas antes de importar.')
    if links['cc_lancamento'].duplicated().any():
        raise ValueError('Um CC de lançamento não pode ter duas correspondências de produção.')
    unknown=set(links.loc[links.cc_producao.ne(''),'cc_producao'])-set(production.cc_producao)
    if unknown:raise ValueError('Correspondência para CC sem produção: '+', '.join(sorted(unknown)))
    return production,links


def valor_cent(row):
    if str(row['preco_eur']).strip()=='' or str(row['icm']).strip()=='':
        return None
    value=Decimal(str(row['quantidade']))*Decimal(str(row['preco_eur']))*Decimal(str(row['icm']))*100
    return int(value.quantize(Decimal('1'),rounding=ROUND_HALF_UP))


def apurar(production,links,costs,scope_ids,complete=True,all_scope=False):
    """Uma linha por CC de produção; todos os seus CC M entram nos gastos uma só vez.

    costs contém o acumulado de TODOS os CC M para o mesmo ano/mês.
    Uma seleção parcial de um agregado expande-se à totalidade desse agregado.
    """
    scope_ids=set(map(str,scope_ids))
    selected=links.loc[links.cc_lancamento.isin(scope_ids)]
    targets=set(selected.loc[selected.cc_producao.ne(''),'cc_producao'])
    if all_scope:targets=set(production.cc_producao)
    cost_by_cc=costs.groupby('cc')['cent'].sum().to_dict() if not costs.empty else {}
    records=[]
    for _,r in production.loc[production.cc_producao.isin(targets)].iterrows():
        members=links.loc[links.cc_producao.eq(r.cc_producao),'cc_lancamento'].tolist()
        income=valor_cent(r)
        cost=sum(int(cost_by_cc.get(x,0)) for x in members) if complete and members else None
        margin=income-cost if income is not None and cost is not None else None
        records.append({'CC produção':r.cc_producao,'Designação':r.designacao,'Unidade':r.unidade,
          'Produção':r.quantidade,'Preço (€)':r.preco_eur,'ICM':r.icm,
          'Rendimento_cent':income,'Gasto_cent':cost,'Saldo_cent':margin,
          'Estado':r.criterio if members else 'Sem correspondência de gastos',
          'Observação':r.observacao,'CC de lançamento':', '.join(members),
          'Âmbito alargado':bool(set(members)-scope_ids)})
    # CC sem produção permanecem visíveis e nunca recebem rendimento zero fictício.
    for _,r in selected.loc[selected.cc_producao.eq('')].iterrows():
        if not int(cost_by_cc.get(r.cc_lancamento,0)):continue
        records.append({'CC produção':r.cc_lancamento,'Designação':r.designacao,'Unidade':'',
          'Produção':None,'Preço (€)':'','ICM':'','Rendimento_cent':None,
          'Gasto_cent':int(cost_by_cc.get(r.cc_lancamento,0)) if complete else None,'Saldo_cent':None,
          'Estado':'Rendimento não apurável','Observação':'Sem produção associada a este CC.',
          'CC de lançamento':r.cc_lancamento,'Âmbito alargado':False})
    return pd.DataFrame(records)


def render_cp(st,cx,available,mapping,scope,label,chosen,cost_frame,euro,root):
    st.markdown('#### Rendimentos simulados · valorização do CP')
    st.caption('Base: preços e ICM do CP 2023, sem atualização. Estimativa de gestão; não corresponde a rendimentos contabilizados. Produção acumulada de janeiro a março de 2026.')
    try:production,links=carregar_fontes(root)
    except (ValueError,OSError) as exc:
        st.error('Não foi possível carregar a simulação: '+str(exc));return
    # Nunca transportar um acumulado de março para outro período, nem deduzir meses.
    if chosen!='2026-03':
        st.info('Rendimento não apurável neste período. A produção disponível corresponde ao acumulado até março de 2026. Seleciona março de 2026 para consultar a simulação.');return
    ids=mapping['Centro de Custos'].astype(str).tolist()
    periods=['2026-01','2026-02','2026-03']
    missing=sorted(set(periods)-set(available))
    costs=cost_frame(cx,[p for p in periods if p in set(available)],ids)
    if missing:st.warning('Gastos acumulados e saldos indisponíveis: faltam os meses '+', '.join(missing)+'. Os rendimentos simulados mantêm-se disponíveis.')
    scope_ids=scope['Centro de Custos'].astype(str).tolist()
    data=apurar(production,links,costs,scope_ids,not missing,label=='Total ULSLA')
    if data.empty:
        st.info('Rendimento não apurável: não há produção associada aos CC selecionados.');return
    if data['Âmbito alargado'].any():
        st.info('A produção está num CC de acumulação. Os gastos abaixo incluem todos os CC de lançamento associados a esse agregado, mesmo quando a seleção inicial contém apenas um deles. O detalhe das correspondências está disponível abaixo.')
    options=['Todos']+[f'{r["CC produção"]} — {r["Designação"]}' for _,r in data.iterrows()]
    key='cp_production_scope'
    if key in st.session_state and st.session_state[key] not in options:del st.session_state[key]
    selected=st.selectbox('CC de produção / acumulação',options,key=key)
    if selected!='Todos':data=data.loc[data['CC produção'].eq(selected.split(' — ',1)[0])].copy()
    valued=data['Rendimento_cent'].notna()
    comparable=valued & data['Gasto_cent'].notna()
    a,b,c=st.columns(3)
    a.metric('Rendimento simulado — parcelas valorizadas',euro(round(data.loc[valued,'Rendimento_cent'].sum())) if valued.any() else 'Não apurável')
    b.metric('Gastos diretos — mesmo âmbito de produção',euro(round(data['Gasto_cent'].sum())) if data['Gasto_cent'].notna().all() else 'Indisponível')
    c.metric('Saldo — apenas parcelas comparáveis',euro(round(data.loc[comparable,'Saldo_cent'].sum())) if comparable.any() else 'Não apurável')
    st.caption(f'{int(valued.sum())} de {len(data)} CC apresentados com rendimento simulado. O saldo só inclui linhas com rendimento e gastos apurados; não representa o resultado global da ULSLA.')
    display=data.drop(columns=['Âmbito alargado']).copy()
    for source,dest in [('Rendimento_cent','Rendimento simulado (€)'),('Gasto_cent','Gastos diretos acumulados (€)'),('Saldo_cent','Saldo comparável (€)')]:
        display[dest]=display[source].map(lambda x:euro(round(x)) if pd.notna(x) else 'Não apurável')
        display=display.drop(columns=source)
    st.dataframe(display.drop(columns=['CC de lançamento']),hide_index=True,use_container_width=True)
    export=data.copy()
    for col in ['Rendimento_cent','Gasto_cent','Saldo_cent']:
        export[col.replace('_cent',' (€)')]=export[col]/100
        export=export.drop(columns=col)
    st.download_button('Exportar simulação CP',export.to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig'),file_name='ULSLA_Rendimentos_CP2023_2026-03.csv',mime='text/csv')
    with st.expander('CC de lançamento incluídos nos gastos e pressupostos'):
        selected_targets=set(data['CC produção'])
        relevant=links.loc[links.cc_producao.isin(selected_targets)|links.cc_lancamento.isin(selected_targets)]
        st.dataframe(relevant,hide_index=True,use_container_width=True)
        st.caption('Cada CC de lançamento tem uma única correspondência. Os gastos mantêm-se diretos, sem novas imputações. Não é feita distribuição fictícia de rendimentos pelos CC filhos. As correspondências constam do CSV editável correspondencia_cc_producao.csv; ascendentes intermédios usam a estrutura hierárquica dos códigos do mapa.')
        st.caption('Consultas: preço base 45 €, paliativos 54 €, sem majorações. Medicina do Trabalho sem valorização por elegibilidade não confirmada. Ambulatório cirúrgico: UO2 × 3 120 € × ICM 0,5926. Urgência: hipótese proporcional 54,50 €/atendimento. HD imuno-hemoterapia: 321 €/sessão. Sem limites anuais, incentivos ou deduções. CP fonte: ULSLA_AM_2023_signed.pdf, Apêndice I, páginas 6–7.')
