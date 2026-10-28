"""Pools ACSS: plano anual reconciliado, repartição explícita e execução mensal."""
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
from html import escape
import json, math
from acompanhamento_acss import base, sources, settings, expected, account_actual, fmt
from pools import read_map, terminal_codes

VERSION='1.1.0'
UNCLASSIFIED='Sem classificação no mapa de Pools'
PENDING='Orçamento por repartir'


def cents(value):
    return int((Decimal(str(value))*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))


def split_amount(amount,weights):
    weights={k:float(v) for k,v in weights.items() if float(v)>0 and math.isfinite(float(v))}
    if not weights:return {}
    total=cents(amount);den=sum(Decimal(str(v)) for v in weights.values())
    out={};used=0
    keys=sorted(weights)
    for key in keys[:-1]:
        n=int((Decimal(total)*Decimal(str(weights[key]))/den).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        out[key]=n/100;used+=n
    out[keys[-1]]=(total-used)/100
    return out


def frontier(ledger):
    return terminal_codes({'contas_balancete':ledger})


def grouped(ledger,mapping,prefix='',excluded=()):
    """Mesma classificação exata de Pool 1 usada no Sumário Executivo."""
    out={}
    for code in frontier(ledger):
        if not code.startswith(('6','7')) or not code.startswith(prefix) or any(code.startswith(p) for p in excluded):continue
        pool=mapping.get(code,{}).get('pool1') or UNCLASSIFIED
        key=('Gastos' if code.startswith('6') else 'Rendimentos',pool)
        amount=account_actual(ledger,code)
        if amount is None:out[key]=None
        elif key not in out or out[key] is not None:out[key]=round(out.get(key,0)+amount,2)
    return out


def partitions(contract,mapping):
    """Particiona os totais em conjuntos disjuntos, preservando os resíduos ACSS."""
    out=[]
    for group,root in [('Gastos','6'),('Rendimentos','7')]:
        rows={r['conta']:r for r in contract['linhas'] if r['grupo']==group and r.get('conta')}
        def emit(prefix,amount,excluded=()):
            if cents(amount)==0:return
            descendants=[code for code,item in mapping.items() if code.startswith(prefix) and item.get('tipo')=='M' and not any(code.startswith(p) for p in excluded)]
            pools=sorted({mapping[c].get('pool1') or UNCLASSIFIED for c in descendants})
            out.append(dict(id=group+':'+prefix+(':'+','.join(sorted(excluded)) if excluded else ''),grupo=group,conta=prefix,excluidas=list(excluded),anual=round(amount,2),rubrica=rows[prefix]['rubrica'],pools=pools,fonte=rows[prefix]['fonte'],celula=rows[prefix]['celula']))
        def walk(prefix):
            row=rows[prefix]
            descendants=[code for code,item in mapping.items() if code.startswith(prefix) and item.get('tipo')=='M']
            ps={mapping[c].get('pool1') or UNCLASSIFIED for c in descendants}
            if len(ps)==1:emit(prefix,row['anual']);return
            kids=[k for k in rows if k!=prefix and k.startswith(prefix) and not any(k.startswith(a) and a!=k and a!=prefix for a in rows if a.startswith(prefix))]
            if not kids:emit(prefix,row['anual']);return
            for kid in sorted(kids):walk(kid)
            residual=(cents(row['anual'])-sum(cents(rows[k]['anual']) for k in kids))/100
            emit(prefix,residual,kids)
        walk(root)
        target=rows[root]['anual']
        if sum(cents(r['anual']) for r in out if r['grupo']==group)!=cents(target):raise ValueError('Falha na reconciliação do plano '+group)
    return out


def overrides(root,year):
    path=Path(root)/'contratualizacao'/f'reparticao_pools_{year}.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def save_overrides(root,year,obj):
    path=Path(root)/'contratualizacao'/f'reparticao_pools_{year}.json'
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)


def build_plan(root,data,year,estimate=True):
    contract=base(root,year)
    if not contract:return [],None
    mapping=read_map(Path(root)/'mapa_pools.tsv');parts=partitions(contract,mapping)
    manual=overrides(root,year)
    candidates=sorted([p for p in data if p.startswith(str(year-1)+'-')],reverse=True)
    prior_period=None;prior_ledger={}
    for p in candidates:
        ledger,_=sources(root,p,data[p])
        if ledger:prior_period=p;prior_ledger=ledger;break
    for part in parts:
        assigned={};method='Por repartir'
        saved=manual.get(part['id'])
        if saved is not None:
            if any(k not in part['pools'] or not isinstance(v,(int,float)) or not math.isfinite(v) or (v<0 if part['anual']>=0 else v>0) for k,v in saved.items()) or sum(cents(v) for v in saved.values())!=cents(part['anual']):
                raise ValueError('Repartição guardada não reconcilia: '+part['rubrica'])
            assigned=saved;method='Repartição manual'
        elif len(part['pools'])==1:
            assigned={part['pools'][0]:part['anual']};method='Correspondência direta ACSS'
        elif estimate and prior_ledger:
            weights=grouped(prior_ledger,mapping,part['conta'],part['excluidas'])
            weights={pool:abs(v) for (group,pool),v in weights.items() if pool in part['pools'] and v is not None and v!=0}
            assigned=split_amount(part['anual'],weights)
            if assigned:method='Repartição técnica por '+prior_period
        if not assigned:assigned={PENDING:part['anual']}
        part.update(reparticao=assigned,metodo=method)
    return parts,prior_period


def plan_totals(parts):
    amounts={}
    for part in parts:
        for pool,v in part['reparticao'].items():
            key=(part['grupo'],pool);amounts[key]=round(amounts.get(key,0)+v,2)
    return amounts


def planned_for(part,pool,month,profiles):
    # O calendário de Pool prevalece sobre a conta e o grupo.
    key='Pool:'+part['grupo']+':'+pool
    if key in profiles:
        profiles=dict(profiles);profiles[part['conta'][:2]]=profiles[key]
    row={'grupo':part['grupo'],'conta':part['conta'],'id':part['id'],'anual':part['reparticao'][pool],'xml':None}
    return expected(row,month,profiles)


def observations(root,data,period,mapping):
    ledger,_=sources(root,period,data.get(period,{}))
    return grouped(ledger,mapping),bool(ledger)


def pool_rows(root,data,period,parts,observed=None):
    year,month=map(int,period.split('-'));mapping=read_map(Path(root)/'mapa_pools.tsv');profiles=settings(root,year)
    current,has_current=observed.get(period) if observed is not None else observations(root,data,period,mapping)
    prev_period=f'{year}-{month-1:02d}'
    previous,has_previous=({},True) if month==1 else (observed.get(prev_period) if observed is not None and prev_period in observed else observations(root,data,prev_period,mapping))
    annual=plan_totals(parts);keys=set(annual)|set(current);out=[]
    for group,pool in sorted(keys):
        contributing=[p for p in parts if p['grupo']==group and pool in p['reparticao']]
        annual_value=annual.get((group,pool))
        # Sem objetivo atribuível ao Pool, não apresentar zero contratualizado.
        target=sum(cents(planned_for(p,pool,month,profiles)) for p in contributing)/100 if contributing else None
        prior_target=sum(cents(planned_for(p,pool,month-1,profiles)) for p in contributing)/100 if contributing and month>1 else (0 if contributing else None)
        monthly_target=round(target-prior_target,2) if target is not None and prior_target is not None else None
        key=(group,pool);actual=current.get(key)
        previous_actual=0 if month==1 else previous.get(key)
        monthly_actual=round(actual-previous_actual,2) if actual is not None and has_previous and previous_actual is not None else None
        delta=round(actual-target,2) if actual is not None and target is not None else None
        month_delta=round(monthly_actual-monthly_target,2) if monthly_actual is not None and monthly_target is not None else None
        methods=sorted({p['metodo'] for p in contributing})
        unresolved=any(p['grupo']==group and pool in p['pools'] and PENDING in p['reparticao'] for p in parts)
        # Um Pool com repartição parcial não deve gerar um desvio falso.
        if unresolved:annual_value=target=monthly_target=delta=month_delta=None
        out.append(dict(grupo=group,pool=pool,anual=annual_value,previsto=target,executado=actual,desvio=delta,
            mensal_previsto=monthly_target,mensal_executado=monthly_actual,mensal_desvio=month_delta,
            execucao_pct=100*actual/annual_value if actual is not None and annual_value else None,
            desvio_pct=100*delta/abs(target) if delta is not None and target else None,
            mensal_desvio_pct=100*month_delta/abs(monthly_target) if month_delta is not None and monthly_target else None,
            metodos=methods,estimado=any('técnica' in x for x in methods),parcial=unresolved))
    return out


def card_html(row,view):
    monthly=view=='Mês';actual=row['mensal_executado'] if monthly else row['executado'];planned=row['mensal_previsto'] if monthly else row['previsto'];delta=row['mensal_desvio'] if monthly else row['desvio']
    favorable=delta is not None and (delta<=0 if row['grupo']=='Gastos' else delta>=0)
    color='#168363' if favorable else '#b23c49' if delta is not None else '#66788a'
    scale=max(abs(actual or 0),abs(planned or 0),1)
    def bar(label,v,color):
        width=100*abs(v or 0)/scale
        return f'<div class="acss-bar-label"><span>{label}</span><b>{fmt(v)}</b></div><div class="acss-track"><div style="width:{width:.3f}%;background:{color};height:7px;border-radius:5px"></div></div>'
    method='Repartição técnica de 2025' if row['estimado'] else 'Objetivo parcial por repartir' if row['parcial'] else 'Repartição manual' if 'Repartição manual' in row['metodos'] else 'Correspondência direta ACSS' if row['metodos'] else 'Sem objetivo atribuído'
    pct='—' if row['execucao_pct'] is None else f"{row['execucao_pct']:.1f} %".replace('.',',')
    return f'''<div class="acss-pool-card"><div class="acss-pool-title">{escape(row['pool'])}</div>
<div class="acss-annual">Objetivo anual atribuído <b>{fmt(row['anual'])}</b></div>
{bar('Previsto do mês' if monthly else 'Previsto acumulado',planned,'#a7bbcf')}
{bar('Executado do mês' if monthly else 'Executado acumulado',actual,'#2477af')}
<div class="acss-pool-delta" style="color:{color}">Desvio {fmt(delta)}</div>
<div class="acss-pool-foot">Execução do anual: {pct} <span>Acumulado: {fmt(row['executado'])}</span></div>
<div class="acss-pool-foot">Mês: {fmt(row['mensal_executado'])} <span>Previsto: {fmt(row['mensal_previsto'])}</span></div>
<div class="acss-pool-method">{escape(method)}</div></div>'''


def table(root_rows,view):
    import pandas as pd
    monthly=view=='Mês';prefix='mensal_' if monthly else ''
    cols={'pool':'Pool 1','anual':'Objetivo anual atribuído (€)',prefix+'previsto':'Previsto do mês (€)' if monthly else 'Previsto acumulado (€)',prefix+'executado':'Executado do mês (€)' if monthly else 'Executado acumulado (€)',prefix+'desvio':'Desvio (€)',prefix+'desvio_pct':'Desvio (%)','execucao_pct':'Execução anual (%)'}
    data=[]
    for r in root_rows:
        item={label:r.get(k) for k,label in cols.items()};item['Base do objetivo']='; '.join(r['metodos']) if r['metodos'] else 'Sem objetivo atribuído'
        data.append(item)
    return pd.DataFrame(data,columns=list(cols.values())+['Base do objetivo'])


def render_pool_analysis(root,data,period):
    import streamlit as st
    import pandas as pd
    import plotly.express as px
    year,month=map(int,period.split('-'));root=Path(root)
    st.markdown('### Principais gastos e rendimentos por Pool')
    st.caption('Pool 1 e classificação de contas iguais aos do Sumário Executivo. Valores em M€.')
    mode=st.radio('Objetivos por Pool',['Repartição técnica pelas contas de 2025','Só correspondências diretas ACSS'],horizontal=True,key='acss_pool_mode')
    estimate=mode.startswith('Repartição técnica')
    parts,prior=build_plan(root,data,year,estimate)
    if estimate:
        st.caption(f'Nos valores ACSS que abrangem vários Pools, o anual é repartido pelo peso absoluto das contas de {prior or "2025 indisponível"}. Esta repartição é uma estimativa interna e pode ser ajustada abaixo. Os totais anuais ACSS mantêm-se.')
    rows=pool_rows(root,data,period,parts)
    view=st.radio('Comparação',['Acumulado','Mês'],horizontal=True,key='acss_pool_view')
    st.caption('Mês = diferença entre dois fechos acumulados consecutivos. Sem fecho anterior, o executado mensal fica indisponível. Desvio = executado − previsto.')
    st.markdown('''<style>.acss-pool-card{border:1px solid #d7e1ec;border-top:3px solid #2477af;border-radius:12px;padding:18px;background:#fff;color:#18344e;margin-bottom:14px;min-height:260px}.acss-pool-title{font-size:16px;font-weight:700;min-height:45px}.acss-annual{font-size:12px;color:#596f83;padding:7px 0 13px;display:flex;justify-content:space-between;gap:8px}.acss-bar-label{font-size:12px;display:flex;justify-content:space-between;margin-top:9px}.acss-track{background:#edf2f7;border-radius:5px;margin-top:4px;height:7px}.acss-pool-delta{font-size:17px;font-weight:700;margin-top:15px}.acss-pool-foot{font-size:11px;color:#536b81;margin-top:7px;display:flex;justify-content:space-between;gap:6px}.acss-pool-method{font-size:10px;color:#6c7f90;margin-top:10px}</style>''',unsafe_allow_html=True)
    tabs=st.tabs(['Principais gastos','Contrato Programa','Rendimentos extra Contrato Programa','Evolução mensal','Repartição e calendarização'])
    def show(items,group,key):
        items=sorted(items,key=lambda r:max(abs(r.get('executado') or 0),abs(r.get('anual') or 0)*month/12),reverse=True)
        limit=st.select_slider('Pools em destaque',[6,9,12,18,30],value=12,key=key+'_limit') if len(items)>6 else 6
        columns=st.columns(3)
        for i,r in enumerate(items[:limit]):
            with columns[i%3]:st.markdown(card_html(r,view),unsafe_allow_html=True)
        frame=table(items,view)
        formatters={c:(lambda v:'—' if pd.isna(v) else fmt(v)) for c in frame.columns if '(€)' in c}
        formatters.update({c:(lambda v:'—' if pd.isna(v) else f'{v:.1f} %'.replace('.',',')) for c in frame.columns if '(%)' in c})
        st.dataframe(frame.style.format(formatters),hide_index=True,width='stretch')
        st.download_button('Exportar acompanhamento CSV',frame.to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig'),f'ACSS_Pools_{key}_{period}.csv','text/csv',key=key+'_csv')
    with tabs[0]:show([r for r in rows if r['grupo']=='Gastos' and r['pool']!=PENDING],'Gastos','gastos')
    with tabs[1]:
        st.caption('Inclui todas as contas classificadas neste Pool pelo mapa existente, incluindo financiamento vertical quando assim classificado.')
        show([r for r in rows if r['grupo']=='Rendimentos' and 'Contrato Programa' in r['pool']],'Rendimentos','cp')
    with tabs[2]:show([r for r in rows if r['grupo']=='Rendimentos' and 'Contrato Programa' not in r['pool'] and r['pool']!=PENDING],'Rendimentos','extra')
    with tabs[3]:
        available=[r for r in rows if r['pool']!=PENDING]
        keys=[(r['grupo'],r['pool']) for r in available]
        chosen=st.selectbox('Pool a acompanhar',keys,format_func=lambda v:v[0]+' — '+v[1],key='acss_pool_evolution')
        if chosen:
            mapping=read_map(root/'mapa_pools.tsv')
            observed={f'{year}-{m:02d}':observations(root,data,f'{year}-{m:02d}',mapping) for m in range(1,month+1)}
            points=[]
            for m in range(1,13):
                p=f'{year}-{m:02d}'
                current_rows=pool_rows(root,data,p,parts,observed) if m<=month else []
                rr=next((r for r in current_rows if (r['grupo'],r['pool'])==chosen),None)
                profiles=settings(root,year)
                own=[part for part in parts if part['grupo']==chosen[0] and chosen[1] in part['reparticao']]
                target=sum(cents(planned_for(part,chosen[1],m,profiles))-cents(planned_for(part,chosen[1],m-1,profiles)) for part in own)/100 if own else None
                if any(part['grupo']==chosen[0] and chosen[1] in part['pools'] and PENDING in part['reparticao'] for part in parts):target=None
                actual=rr['mensal_executado'] if rr else None
                points.extend([{'Mês':p,'Série':'Previsto','M€':target/1e6 if target is not None else None},{'Mês':p,'Série':'Executado','M€':actual/1e6 if actual is not None else None}])
            frame=pd.DataFrame(points)
            st.plotly_chart(px.bar(frame,x='Mês',y='M€',color='Série',barmode='group',color_discrete_map={'Previsto':'#b7c9dc','Executado':'#2477af'}),width='stretch')
            st.caption('O previsto cobre o ano. O executado só é apresentado até ao fecho selecionado e com dois fechos consecutivos disponíveis.')
    with tabs[4]:
        annual=plan_totals(parts)
        for group,rootcode in [('Gastos','6'),('Rendimentos','7')]:
            total=sum(cents(v) for (g,p),v in annual.items() if g==group)/100
            official=next(r['anual'] for r in base(root,year)['linhas'] if r.get('conta')==rootcode)
            st.write(f'{group}: total repartido {fmt(total)} · total ACSS {fmt(official)} · diferença {fmt(round(total-official,2))}')
        st.caption('A soma dos Pools reconcilia com o ACSS. A repartição técnica usa contas do ano anterior, sem usar a execução de 2026 para definir o seu próprio objetivo.')
        splits=[p for p in parts if len(p['pools'])!=1]
        if splits:
            chosen=st.selectbox('Rubrica ACSS a repartir',list(range(len(splits))),format_func=lambda i:splits[i]['conta']+' — '+splits[i]['rubrica']+' ('+fmt(splits[i]['anual'])+')',key='acss_pool_split')
            part=splits[chosen]
            st.caption('Montante a repartir: '+fmt(part['anual'])+'. Pode corresponder ao remanescente depois de retirar as sub-rubricas contratualizadas. A soma deve coincidir ao cêntimo.')
            data_edit=pd.DataFrame([{'Pool 1':pool,'Anual atribuído (€)':part['reparticao'].get(pool,0.)} for pool in part['pools']])
            edited=st.data_editor(data_edit,hide_index=True,disabled=['Pool 1'],column_config={'Anual atribuído (€)':st.column_config.NumberColumn(format='%.2f')},key='acss_split_edit_'+part['id']+'_'+str(estimate))
            if st.button('Guardar repartição desta rubrica',key='acss_split_save'):
                values={r['Pool 1']:float(r['Anual atribuído (€)']) if pd.notna(r['Anual atribuído (€)']) else float('nan') for _,r in edited.iterrows()}
                if any(not math.isfinite(v) or (v<0 if part['anual']>=0 else v>0) for v in values.values()) or sum(cents(v) for v in values.values())!=cents(part['anual']):st.error('A soma da repartição deve coincidir com o montante ACSS, ao cêntimo.')
                else:
                    obj=overrides(root,year);obj[part['id']]=values;save_overrides(root,year,obj);st.rerun()
            if part['id'] in overrides(root,year) and st.button('Repor método automático',key='acss_split_reset'):
                obj=overrides(root,year);del obj[part['id']];save_overrides(root,year,obj);st.rerun()
        choices=[(r['grupo'],r['pool']) for r in rows if r['pool']!=PENDING]
        pick=st.selectbox('Calendarização do Pool',choices,format_func=lambda x:x[0]+' — '+x[1],key='acss_pool_calendar')
        if pick:
            profiles=settings(root,year);key='Pool:'+pick[0]+':'+pick[1]
            st.caption('Por defeito, cada parcela herda os pesos da conta ou do grupo. Guardar aqui cria uma distribuição específica para este Pool. Os duodécimos usam peso 1 em todos os meses.')
            edit=st.data_editor(pd.DataFrame({'Mês':range(1,13),'Peso':profiles.get(key,[1.]*12)}),hide_index=True,disabled=['Mês'],column_config={'Peso':st.column_config.NumberColumn(min_value=0.,format='%.4f')},key='acss_pool_cal_'+key)
            if st.button('Guardar calendário do Pool',key='acss_pool_cal_save'):
                weights=[float(v) if pd.notna(v) else float('nan') for v in edit['Peso']]
                if any(not math.isfinite(v) or v<0 for v in weights) or sum(weights)<=0:st.error('Preencha pesos não negativos e pelo menos um peso positivo.')
                else:
                    from acompanhamento_acss import save_settings
                    profiles[key]=weights;save_settings(root,year,profiles);st.rerun()
            if key in profiles and st.button('Repor calendário herdado',key='acss_pool_cal_reset'):
                from acompanhamento_acss import save_settings
                del profiles[key];save_settings(root,year,profiles);st.rerun()
        audit=pd.DataFrame([{'Conta':p['conta'],'Rubrica':p['rubrica'],'Anual (€)':p['anual'],'Método':p['metodo'],'Pools':', '.join(p['reparticao']),'Fonte':p['fonte'],'Célula':p['celula'],'Excluir contas':', '.join(p['excluidas'])} for p in parts])
        st.dataframe(audit,hide_index=True,width='stretch')
    return rows,parts
