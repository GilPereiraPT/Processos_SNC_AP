"""Acompanhamento ACSS: base contratualizada preservada e execução observada."""
from pathlib import Path
import json, math, gzip
from comparador import value
from periodos_snc_ap import normalizar_periodo

VERSION='1.1.0'

def base(root, year):
    path=Path(root)/'contratualizacao'/f'base_{year}.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

def settings(root,year):
    path=Path(root)/'contratualizacao'/f'calendarizacao_{year}.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}

def save_settings(root,year,obj):
    path=Path(root)/'contratualizacao'/f'calendarizacao_{year}.json'
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)

def read_periods(root):
    root=Path(root);out={}
    seed=root/'seed_2026_09.json'
    candidates=[]
    if seed.exists():
        obj=json.loads(seed.read_text(encoding='utf-8'));candidates.append((obj['periodo'],obj))
    path=root/'dados_mensais.json'
    if path.exists():candidates.extend(json.loads(path.read_text(encoding='utf-8')).items())
    from periodos_snc_ap import prioridade_periodo
    for key,record in sorted(candidates,key=lambda x:(normalizar_periodo(x[0]),prioridade_periodo(x[0]))):
        out[normalizar_periodo(key)]=record
    for path in sorted((root/'dados_s3cp_xml').glob('*/*.json.gz')):
        if path.stem.split('.')[0] not in ('DR','BA','BLC','DFC'):continue
        key=normalizar_periodo(path.parent.name)
        record=out.setdefault(key,{'periodo':key})
        if path.name=='DR.json.gz' and not record.get('dr'):
            with gzip.open(path,'rt',encoding='utf-8') as f:obj=json.load(f)
            values={r['RubricaAgregadora']:r['TotalAnoCorrente'] for r in obj.get('resumo',[]) if r.get('RubricaAgregadora')}
            if values.get('DRX04') is not None:record['dr']={'resultado':values['DRX04']}
    return out

def sources(root,period,record):
    """Só carrega os XML do fecho pedido, incluindo P13/P14 em dezembro."""
    root=Path(root);year,month=map(int,period.split('-'));objs={}
    for kind in ('BA','BLC','DFC','DR'):
        for m in ([14,13,12] if month==12 else [month]):
            p=root/'dados_s3cp_xml'/f'{year}-{m:02}'/(kind+'.json.gz')
            if p.exists():
                with gzip.open(p,'rt',encoding='utf-8') as f:objs[kind]=json.load(f)
                break
    ledger=record.get('contas_balancete',{})
    if not ledger and objs.get('BA'):
        ledger={}
        for r in objs['BA']['registos']:
            code=str(r.get('ContaLocal','')).replace('.','').strip()
            if not code.startswith(('6','7','8121')):continue
            d=r.get('detalhes',{}).get('BA03')
            item=ledger.setdefault(code,{'debito_acumulado':0.,'credito_acumulado':0.})
            if d is None or d.get('Debito') is None or d.get('Credito') is None:
                item['debito_acumulado']=item['credito_acumulado']=None
            elif item['debito_acumulado'] is not None:
                item['debito_acumulado']+=d['Debito'];item['credito_acumulado']+=d['Credito']
    tables={}
    for kind,obj in objs.items():
        table={}
        for r in obj.get('registos',[]):
            if r.get('Rubrica'):table[r['Rubrica']]=r.get('ValorAnoCorrente')
        for r in obj.get('resumo',[]):
            key=r.get('RubricaAgregadora') or r.get('MacroRubrica')
            if key:table[key]=r.get('TotalAnoCorrente')
        tables[kind]=table
    return ledger,tables

def account_actual(ledger,prefix):
    rec={'contas_balancete':ledger}
    codes=[k for k in ledger if k.startswith(prefix)]
    if prefix in ledger:codes=[prefix]
    else:codes=[k for k in codes if not any(k.startswith(p) and p!=k for p in codes)]
    if not codes:return None
    vals=[round(ledger[k]['debito_acumulado']-ledger[k]['credito_acumulado'],2) if ledger[k].get('debito_acumulado') is not None and ledger[k].get('credito_acumulado') is not None else value(rec,k,'acumulado') for k in codes]
    if any(v is None for v in vals):return None
    return round(sum(vals)*(-1 if prefix.startswith('7') else 1),2)

def profile_key(row):
    if row['grupo'] in ('Gastos','Rendimentos'):return row['conta'][:2] if len(row['conta'])>1 else row['grupo']
    return 'IRC' if row['id']=='IRC' else 'DFC'

def expected(row,month,profiles):
    if row['grupo'] in ('Ativo','Passivo') or row.get('xml') in ('DFCX07','DFCX10'):return None
    key=profile_key(row)
    weights=profiles.get(key)
    if weights is None and row['grupo'] in ('Gastos','Rendimentos'):weights=profiles.get(row['grupo'])
    if weights is None:
        if key=='DFC':return row['anual'] if month==12 else None
        weights=[1]*12
    if len(weights)!=12 or any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in weights) or sum(weights)<=0:
        raise ValueError(f'Calendarização inválida: {key}')
    return round(row['anual']*sum(weights[:month])/sum(weights),2)

def evaluate(root,data,period):
    year,month=map(int,period.split('-'));contract=base(root,year)
    if not contract:return []
    profiles=settings(root,year);rec=data.get(period,{})
    ledger,tables=sources(root,period,rec);out=[]
    for row in contract['linhas']:
        row=dict(row)
        if row['conta']:actual=account_actual(ledger,row['conta'])
        else:actual=tables.get('BLC' if row['grupo'] in ('Ativo','Passivo') else 'DFC',{}).get(row['xml'])
        # Totais da DR: correspondência explícita aos resultados oficiais.
        if row['id']=='IRC' and actual is None:
            actual=rec.get('dr',{}).get('imposto_rendimento')
            if actual is not None:actual=-actual
            elif tables.get('DR',{}).get('DR24') is not None:actual=-tables['DR']['DR24']
        planned=expected(row,month,profiles)
        delta=round(actual-planned,2) if actual is not None and planned is not None else None
        gap=round(actual-row['anual'],2) if actual is not None else None
        row.update(executado=actual,previsto=planned,desvio=delta,distancia_anual=gap,
                   desvio_pct=100*delta/abs(planned) if delta is not None and planned else None,
                   execucao_pct=100*actual/row['anual'] if actual is not None and row['anual'] and row['grupo'] not in ('Ativo','Passivo') and row.get('xml') not in ('DFCX07','DFCX10') else None,
                   favoravel=(delta<=0 if row['grupo']=='Gastos' or row['id']=='IRC' else delta>=0) if delta is not None and row['grupo'] in ('Gastos','Rendimentos','Resultados') else None)
        out.append(row)
    # Os totais respeitam a calendarização dos grupos de dois dígitos.
    for total in [r for r in out if r.get('conta') in ('6','7')]:
        children=[r for r in out if r.get('conta') and len(r['conta'])==2 and r['conta'].startswith(total['conta'])]
        total['previsto']=round(sum(r['previsto'] for r in children),2)
        total['desvio']=round(total['executado']-total['previsto'],2) if total['executado'] is not None else None
        total['desvio_pct']=100*total['desvio']/abs(total['previsto']) if total['desvio'] is not None and total['previsto'] else None
    if any(str(k).startswith('Pool:') for k in profiles):
        from acss_pools import build_plan, planned_for, cents
        parts,_=build_plan(root,data,year,True)
        for group,code in [('Gastos','6'),('Rendimentos','7')]:
            total=next(r for r in out if r.get('conta')==code)
            total['previsto']=sum(cents(planned_for(p,pool,month,profiles)) for p in parts if p['grupo']==group for pool in p['reparticao'])/100
            total['desvio']=round(total['executado']-total['previsto'],2) if total['executado'] is not None else None
            total['desvio_pct']=100*total['desvio']/abs(total['previsto']) if total['desvio'] is not None and total['previsto'] else None
    return out

def headlines(rows,record):
    lookup={r.get('conta'):r for r in rows if r.get('conta') in ('6','7')}
    result=[]
    for code,label in [('7','Rendimentos'),('6','Gastos')]:
        if code in lookup:result.append(dict(lookup[code],rubrica=label))
    if len(result)==2:
        revenue,cost=result;tax=next(r for r in rows if r['id']=='IRC')
        for label,after_tax in [('Resultado antes de impostos',False),('Resultado líquido',True)]:
            r={'rubrica':label}
            for k in ('anual','previsto','executado'):
                vals=[revenue[k],cost[k]]+([tax[k]] if after_tax else [])
                r[k]=round(vals[0]-sum(vals[1:]),2) if all(v is not None for v in vals) else None
            official=record.get('dr',{}).get('resultado')
            if after_tax and official is not None:r['executado']=official
            r['desvio']=round(r['executado']-r['previsto'],2) if r['executado'] is not None and r['previsto'] is not None else None
            r['favoravel']=r['desvio']>=0 if r['desvio'] is not None else None
            result.append(r)
    return result

def fmt(v):
    if v is None or (isinstance(v,float) and math.isnan(v)):return '—'
    return f'{v/1e6:,.2f} M€'.replace(',','X').replace('.',',').replace('X','.')

def render_summary(root,data,period):
    import streamlit as st
    rows=evaluate(root,data,period)
    if not rows:return
    st.markdown('#### Acompanhamento da contratualização ACSS')
    cards=headlines(rows,data.get(period,{}))
    for col,r in zip(st.columns(len(cards)),cards):
        with col:
            st.metric(r['rubrica'],fmt(r['executado']),fmt(r['desvio'])+' face ao previsto' if r['desvio'] is not None else None,delta_color='inverse' if r['rubrica']=='Gastos' else 'normal')
            st.caption('Previsto até ao mês: '+fmt(r['previsto']))
    st.caption('DR: duodécimos, salvo calendarização guardada no módulo. Valores em M€.')

def render(root,data,period):
    import streamlit as st
    import pandas as pd
    import plotly.express as px
    year,month=map(int,period.split('-'));contract=base(root,year)
    st.subheader('Acompanhamento da Contratualização')
    if not contract:
        st.info(f'Não existe base contratualizada para {year}. A base disponível é de 2026.');return
    rows=evaluate(root,data,period);render_summary(root,data,period)
    from acss_pools import render_pool_analysis
    render_pool_analysis(root,data,period)
    if not st.checkbox('Abrir mapas ACSS completos, balanço e DFC',key='acss_full_maps'):
        return
    tabs=st.tabs(['Resumo','Rendimentos','Gastos','Balanço','Fluxos de caixa','Calendarização e fontes'])
    def table(items,balance=False):
        fields=[('rubrica','Rubrica'),('anual','Objetivo dezembro (€)' if balance else 'Contratualizado anual (€)')]
        if not balance:fields+=[('previsto','Previsto até ao mês (€)')]
        fields += [('executado','Executado (€)'),('distancia_anual' if balance else 'desvio','Distância ao objetivo (€)' if balance else 'Desvio (€)')]
        if not balance:fields += [('desvio_pct','Desvio (%)'),('execucao_pct','Execução anual (%)'),('distancia_anual','Diferença face ao anual (€)')]
        frame=pd.DataFrame([{label:r.get(key) for key,label in fields} for r in items])
        formats={c:(lambda v: '—' if pd.isna(v) else f'{v:,.2f} €'.replace(',','X').replace('.',',').replace('X','.')) for c in frame if '(€)' in c}
        formats.update({c:lambda v:'—' if pd.isna(v) else f'{v:.1f} %'.replace('.',',') for c in frame if '(%)' in c})
        st.dataframe(frame.style.format(formats),hide_index=True,width='stretch')
        return frame
    with tabs[0]:
        st.caption('Desvio = executado − previsto. Nos gastos, um desvio positivo é desfavorável. Percentagens com base zero ficam sem valor.')
        table(headlines(rows,data.get(period,{})))
        chart=[]
        for p in sorted(k for k in data if k.startswith(str(year)) and k<=period):
            for r in headlines(evaluate(root,data,p),data[p])[:2]:
                for field,label in [('executado','Executado'),('previsto','Previsto')]:
                    if r[field] is not None:chart.append({'Mês':p,'Rubrica':r['rubrica'],'Série':label,'M€':r[field]/1e6})
        if chart:st.plotly_chart(px.line(pd.DataFrame(chart),x='Mês',y='M€',color='Série',facet_row='Rubrica',markers=True).update_yaxes(matches=None),width='stretch')
        deviations=[r for r in rows if r['grupo'] in ('Gastos','Rendimentos') and r['conta'] and len(r['conta'])==2 and r['desvio'] is not None]
        st.markdown('##### Maiores desvios por grupo de contas')
        table(sorted(deviations,key=lambda r:abs(r['desvio']),reverse=True)[:8])
    for tab,group in [(tabs[1],'Rendimentos'),(tabs[2],'Gastos'),(tabs[4],'Fluxos de caixa')]:
        with tab:
            if group=='Fluxos de caixa':st.caption('Sem calendarização, a DFC compara com o anual e só apresenta previsão acumulada em dezembro. Os saldos de caixa mantêm-se como referências de saldo.')
            else:st.caption('As contas agregadoras e as subcontas são apresentadas para consulta. Não somar as linhas entre si.')
            if group=='Rendimentos':
                for prefix,label in [('72011','Contrato Programa'),('7201','Serviços de saúde')]:
                    selected=[r for r in rows if r.get('conta')==prefix]
                    if selected:st.markdown('##### '+label);table(selected)
            if group=='Rendimentos':
                total=next((r for r in rows if r.get('conta')=='7'),None)
                cp=next((r for r in rows if r.get('conta')=='72011'),None)
                if total and cp:
                    extra={'rubrica':'Rendimentos extra Contrato Programa'}
                    for field in ('anual','previsto','executado','desvio','distancia_anual'):
                        extra[field]=round(total[field]-cp[field],2) if total.get(field) is not None and cp.get(field) is not None else None
                    st.markdown('##### Restantes rendimentos');table([extra])
            frame=table([r for r in rows if r['grupo']==group])
            st.download_button('Exportar tabela CSV',frame.to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig'),f'ACSS_{year}_{group}_{period}.csv','text/csv',key='acss_csv_'+group)
            if group=='Gastos':st.markdown('##### Imposto sobre o rendimento');table([r for r in rows if r['id']=='IRC'])
    with tabs[3]:
        st.caption('Saldos à data face ao objetivo de dezembro. A distância ao objetivo não representa um desvio a uma previsão mensal.')
        for group in ('Ativo','Passivo'):
            st.markdown('##### '+('Património líquido e passivo' if group=='Passivo' else group));table([r for r in rows if r['grupo']==group],True)
    with tabs[5]:
        st.write('Base ACSS 2026 preservada. Resultado antes de impostos: −28 739 157,00 €. IRC: 250,00 €. Resultado líquido: −28 739 407,00 €.')
        st.caption('DR: movimentos líquidos acumulados das contas 6/7; rendimentos com sinal invertido. XML BA: BA03. Dimensões da mesma conta são agregadas; contas mãe e filhas nunca são somadas em conjunto. Ausências de dados permanecem em branco.')
        profiles=settings(root,year)
        options=['Gastos','Rendimentos','IRC','DFC']+sorted({profile_key(r) for r in rows if r['grupo'] in ('Gastos','Rendimentos') and len(r['conta'])>=2})
        key=st.selectbox('Calendarização por grupo de contas',options)
        st.caption('Pesos relativos mensais: 1 em todos os meses corresponde a duodécimos. As contas de dois dígitos podem ter uma distribuição própria. Os totais são calculados a partir desses grupos. A DFC usa uma distribuição global quando a guardar.')
        weights=profiles.get(key,[1.]*12)
        edited=st.data_editor(pd.DataFrame({'Mês':range(1,13),'Peso':weights}),hide_index=True,disabled=['Mês'],column_config={'Peso':st.column_config.NumberColumn(min_value=0.,format='%.4f')},key='acss_pesos_'+key)
        if st.button('Guardar calendarização',key='acss_save'):
            new=[float(v) for v in edited['Peso']]
            if any(not math.isfinite(v) or v<0 for v in new) or sum(new)<=0:st.error('Preencha pesos válidos e pelo menos um peso positivo.')
            else:profiles[key]=new;save_settings(root,year,profiles);st.rerun()
        if key in profiles and st.button('Repor distribuição por defeito',key='acss_reset'):
            del profiles[key];save_settings(root,year,profiles);st.rerun()
        st.dataframe(pd.DataFrame([{k:r.get(k) for k in ('grupo','rubrica','conta','xml','anual','fonte','celula')} for r in contract['linhas']]),hide_index=True,width='stretch')
