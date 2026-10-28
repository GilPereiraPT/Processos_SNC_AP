"""Análise comparativa SNC-AP 6.13. Sem inferência de fechos ausentes."""
from io import BytesIO
import pandas as pd
import plotly.express as px
import streamlit as st
from ulsla_branding import period_selectbox

METRICS = [
 ('dr','rendimentos_impostos','Impostos, contribuições e taxas','Rendimentos'),
 ('dr','vendas','Vendas','Rendimentos'),
 ('dr','prestacoes_servicos','Prestações de serviços','Rendimentos'),
 ('dr','transferencias','Transferências correntes','Rendimentos'),
 ('dr','outros_rendimentos','Outros rendimentos','Rendimentos'),
 ('dr','consumos','Consumos','Gastos'),('dr','fse','FSE','Gastos'),
 ('dr','pessoal','Pessoal','Gastos'),('dr','outros_gastos','Outros gastos','Gastos'),
 ('dr','depreciacoes','Depreciações','Gastos'),('dr','ebitda','Resultado antes de depreciações e financeiros','Resultados'),
 ('dr','operacional','Resultado operacional','Resultados'),('dr','resultado','Resultado líquido','Resultados'),
 ('balanco','ativo','Ativo total','Balanço'),('balanco','ativo_corrente','Ativo corrente','Balanço'),
 ('balanco','passivo','Passivo total','Balanço'),('balanco','passivo_corrente','Passivo corrente','Balanço'),
 ('balanco','patrimonio','Património líquido','Balanço'),('balanco','caixa','Caixa e depósitos','Balanço'),
 ('balanco','fornecedores','Fornecedores','Balanço'),('balanco','fornecedores_investimento','Fornecedores de investimento','Balanço'),
 ('dfc','operacional','Fluxos operacionais','Fluxos de caixa'),('dfc','investimento','Fluxos de investimento','Fluxos de caixa'),
 ('dfc','financiamento','Fluxos de financiamento','Fluxos de caixa'),('dfc','fornecedores_pagamentos','Pagamentos a fornecedores','Fluxos de caixa')]
LOOKUP = {(g,k):(name,area) for g,k,name,area in METRICS}

def latest_periods(data, cadence):
    available=sorted(p for p in data if len(p)==7 and p[4]=='-' and p[:4].isdigit())
    if cadence=='Mensal': return [(p,p) for p in available]
    endings={'Trimestral':{'03','06','09','12'},'Anual':{'12'}}[cadence]
    return [(p,p) for p in available if p[-2:] in endings]

def period_amount(data, per, group, key, mode):
    record=data.get(per,{})
    value=record.get(group,{}).get(key)
    if value is None:return None,'Sem rubrica no fecho'
    value=float(value)
    if group=='balanco' or mode=='Acumulado / saldo':return value,'Saldo à data' if group=='balanco' else 'Acumulado do exercício'
    month=int(per[-2:]); year=int(per[:4]); prior_month=month-(1 if mode=='Movimento mensal' else 3)
    if prior_month<1:
        if (mode=='Movimento mensal' and month==1) or (mode=='Movimento trimestral' and month==3):
            return value,'Primeiro período do exercício'
        return None,'Fecho de início de período não disponível'
    preceding=f'{year}-{prior_month:02d}'
    prev=data.get(preceding,{}).get(group,{}).get(key)
    if prev is None:return None,f'Sem fecho base {preceding}'
    return value-float(prev),f'Diferença de acumulados: {preceding} → {per}'

def financial_ratio(data,per,key):
    b=data.get(per,{}).get('balanco',{});dr=data.get(per,{}).get('dr',{})
    a=b.get('ativo');passivo=b.get('passivo');pc=b.get('passivo_corrente');ac=b.get('ativo_corrente');pat=b.get('patrimonio')
    def ratio(n,d,m=1): return n/d*m if n is not None and d not in (None,0) else None
    if key=='Autonomia financeira (%)':return ratio(pat,a,100)
    if key=='Endividamento (%)':return ratio(passivo,a,100)
    if key=='Liquidez corrente (x)':return ratio(ac,pc)
    if key=='Liquidez reduzida (x)':return ratio(ac-b['inventarios'] if ac is not None and b.get('inventarios') is not None else None,pc)
    if key=='Liquidez imediata (x)':return ratio(b.get('caixa'),pc)
    if key=='Fundo de maneio (€)':return ac-pc if ac is not None and pc is not None else None
    if key=='Dívida fornecedores (€)':return b['fornecedores']+b['fornecedores_investimento'] if 'fornecedores' in b and 'fornecedores_investimento' in b else None
    if key=='Margem líquida (%)':
        revenue=sum(dr.get(k,0) for k in ('rendimentos_impostos','vendas','prestacoes_servicos','transferencias','outros_rendimentos'))
        return ratio(dr.get('resultado'),revenue,100)
    return None

def render(data,selected_period,euro):
    st.subheader('Análise económico-financeira comparativa')
    st.caption('Comparação cronológica baseada nos fechos SNC-AP efetivamente importados. Nunca se completam meses em falta por estimativa.')
    a,b,c=st.columns([1,1,1.25])
    with a: cadence=st.radio('Periodicidade',['Mensal','Trimestral','Anual'],horizontal=True,key='v613_cadence')
    available=[p for _,p in latest_periods(data,cadence)]
    if not available:
        st.warning('Não existem fechos disponíveis para esta periodicidade.');return
    upto=selected_period if selected_period in available else max((p for p in available if p<=selected_period),default=available[-1])
    with b:
        ending=period_selectbox('Período mais recente',[p for p in available if p<=upto] or available,index=len([p for p in available if p<=upto] or available)-1,key='v613_end')
    with c:
        analytical=st.selectbox('Tipo de comparação',['Entre dois fechos','Evolução histórica','Homóloga (N-1)'],key='v613_compare_type')
    candidates=[p for p in available if p<ending]
    if analytical=='Entre dois fechos':
        if not candidates:st.info('Só existe um fecho disponível para comparação.');return
        left,right=st.columns(2)
        with left: earlier=period_selectbox('Período anterior',candidates,index=candidates.index(st.session_state.get('v613_top_earlier')) if st.session_state.get('v613_top_earlier') in candidates else len(candidates)-1,key='v613_earlier')
        with right: st.text_input('Período recente',ending,disabled=True)
        periods=[earlier,ending]
    elif analytical=='Homóloga (N-1)':
        previous=f'{int(ending[:4])-1}{ending[4:]}'
        if previous not in data:st.info('O período homólogo não foi importado; quando possível, são utilizados os valores N-1 do documento mais recente, identificados como tal.')
        periods=[previous,ending]
    else:
        amount=st.slider('Número de fechos a apresentar',2,24,12,key='v613_horizon')
        periods=[p for p in available if p<=ending][-amount:]
    groups=sorted(set(area for _,_,_,area in METRICS))
    area=st.selectbox('Área de análise',groups+['Indicadores económico-financeiros','Contas SNC-AP'],key='v613_area')
    if area=='Contas SNC-AP':
        account_names={}
        for p in periods:
            for code,info in data.get(p,{}).get('contas_balancete',{}).items():account_names.setdefault(code,info.get('descricao',''))
        choices=sorted(account_names,key=lambda x:(len(x),x))
        selected=st.multiselect('Contas SNC-AP',choices,default=[x for x in ('61','62','63','22','271') if x in choices],format_func=lambda x:x+' — '+account_names[x],key='v613_accounts')
        measure=st.selectbox('Campo contabilístico',['saldo_devedor','saldo_credor','debito_acumulado','credito_acumulado'],key='v613_field')
        specs=[('contas_balancete',code,code+' — '+account_names[code],'SNC-AP') for code in selected]
    elif area=='Indicadores económico-financeiros':
        choices=['Autonomia financeira (%)','Endividamento (%)','Liquidez corrente (x)','Liquidez reduzida (x)','Liquidez imediata (x)','Fundo de maneio (€)','Dívida fornecedores (€)','Margem líquida (%)']
        selected=st.multiselect('Indicadores',choices,default=choices[:5],key='v613_ratios')
        specs=[('ratio',k,k,area) for k in selected]
    else:
        choices=[(g,k,name,ar) for g,k,name,ar in METRICS if ar==area]
        selected=st.multiselect('Rubricas',[(g,k) for g,k,_,_ in choices],default=[(g,k) for g,k,_,_ in choices][:8],format_func=lambda v:LOOKUP[v][0],key='v613_metrics')
        specs=[(g,k,LOOKUP[(g,k)][0],area) for g,k in selected]
    mode_options=['Acumulado / saldo']
    if cadence=='Mensal':mode_options+=['Movimento mensal']
    if cadence=='Trimestral':mode_options+=['Movimento trimestral']
    mode=st.radio('Base dos valores',mode_options,horizontal=True,key='v613_mode')
    rows=[]
    for per in periods:
        for group,key,name,_ in specs:
            provenance='Fecho SNC-AP'
            if group=='ratio':value=financial_ratio(data,per,key);reason='Rácio calculado com os valores do fecho'
            elif group=='contas_balancete':
                rec=data.get(per,{}).get('contas_balancete',{}).get(key,{})
                value=rec.get(measure);reason='Campo do balancete'
            else:value,reason=period_amount(data,per,group,key,mode)
            if value is None and analytical=='Homóloga (N-1)' and per==periods[0] and group not in ('ratio','contas_balancete') and mode=='Acumulado / saldo':
                value=data.get(ending,{}).get(group+'_n1',{}).get(key)
                if value is not None:provenance='N-1 do documento '+ending;reason='Referência homóloga apresentada no PDF'
            rows.append({'Período':per,'Rubrica':name,'Valor':value,'Fonte':provenance,'Método':reason})
    frame=pd.DataFrame(rows)
    if frame.empty:st.info('Seleciona pelo menos uma rubrica.');return
    nonempty=frame.dropna(subset=['Valor'])
    if nonempty.empty:st.warning('Nenhum valor disponível nos fechos selecionados.');return
    pivot=frame.pivot_table(index='Rubrica',columns='Período',values='Valor',aggfunc='first')
    for p in periods:
        if p not in pivot.columns:pivot[p]=float('nan')
    pivot=pivot[periods]
    if len(periods)==2:
        earlier,latest=periods
        pivot['Δ (€ ou pontos)']=pivot[latest]-pivot[earlier]
        base=pivot[earlier].abs().replace(0,float('nan'))
        pivot['Δ (%)']=100*pivot['Δ (€ ou pontos)']/base
    st.markdown('#### Mapa comparativo')
    display=pivot.reset_index()
    formats={p:(lambda n:euro(n) if pd.notna(n) and area not in ('Indicadores económico-financeiros',) else f'{n:,.2f}'.replace(',','X').replace('.',',').replace('X','.') if pd.notna(n) else '—') for p in periods}
    if 'Δ (€ ou pontos)' in display:formats['Δ (€ ou pontos)']=lambda n:euro(n) if pd.notna(n) and area not in ('Indicadores económico-financeiros',) else f'{n:+.2f}' if pd.notna(n) else '—';formats['Δ (%)']=lambda n:f'{n:+.2f}%' if pd.notna(n) else '—'
    st.dataframe(display.style.format(formats),hide_index=True,use_container_width=True)
    chart=px.bar(nonempty,x='Rubrica',y='Valor',color='Período',barmode='group',category_orders={'Período':periods},color_discrete_map={p:['#078ca3','#ed9b48'][i] if len(periods)==2 else px.colors.qualitative.Safe[i%len(px.colors.qualitative.Safe)] for i,p in enumerate(periods)}) if len(periods)==2 else px.line(nonempty,x='Período',y='Valor',color='Rubrica',markers=True,category_orders={'Período':periods})
    chart.update_layout(height=470,xaxis_title='',yaxis_title='Valor (€, %, ou vezes consoante o indicador)',legend_title='',margin=dict(b=90,t=20))
    if len(periods)==2:chart.update_xaxes(tickangle=-25)
    st.plotly_chart(chart,use_container_width=True)
    st.caption('Balanço: saldos à data. DR/DFC: valores acumulados ou diferenças de acumulados apenas quando existe o fecho base. Δ = período recente − anterior; Δ% usa o valor absoluto do anterior. Aumentos não significam necessariamente melhoria.')
    with st.expander('Proveniência, disponibilidade e regras de cálculo'):
        st.dataframe(frame,hide_index=True,use_container_width=True)
    output=BytesIO()
    with pd.ExcelWriter(output,engine='openpyxl') as writer:
        pivot.reset_index().to_excel(writer,index=False,sheet_name='Comparação')
        frame.to_excel(writer,index=False,sheet_name='Dados e auditoria')
        pd.DataFrame([{'Regra':'Saldo de Balanço','Descrição':'Saldo à data do fecho'}, {'Regra':'DR e DFC','Descrição':'Acumulado ou diferença de acumulados com fecho base existente'}, {'Regra':'Desvio','Descrição':'Recente menos anterior'}, {'Regra':'Percentagem','Descrição':'Desvio / abs(valor anterior) * 100'}]).to_excel(writer,index=False,sheet_name='Metodologia')
    st.download_button('Exportar análise para Excel',output.getvalue(),'ULSLA_analise_economico_financeira.xlsx',mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',key='v613_export')
