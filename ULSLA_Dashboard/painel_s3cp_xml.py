"""Interface de importacao e analise de XML SNC-AP."""
import io,zipfile
import pandas as pd
import streamlit as st
from ulsla_branding import period_selectbox
from importador_s3cp_xml import inspect,catalog,load,save,pmp_ba,series
from datetime import date
from periodos_snc_ap import normalizar_periodo, prioridade_periodo

def import_widget(root):
    st.markdown('### Fechos SNC-AP em XML')
    st.caption('Aceita vários tipos e períodos em simultâneo. Os DR, BLC e DFC importados por PDF permanecem inalterados.')
    uploads=st.file_uploader('Selecionar ficheiros XML SNC-AP ou ZIP com XML',type=['xml','zip'],accept_multiple_files=True,key='s3cp_batch_upload')
    if not uploads:return
    candidates=[];errors=[]
    for up in uploads:
        try:
            contents=up.getvalue()
            if up.name.lower().endswith('.zip'):
                with zipfile.ZipFile(io.BytesIO(contents)) as z:
                    for name in z.namelist():
                        if name.lower().endswith('.xml') and not name.startswith('__MACOSX/'):
                            item=z.getinfo(name)
                            if item.file_size>75*1024*1024: errors.append(f'{name}: excede 75 MB');continue
                            try:candidates.append(inspect(z.read(name),name))
                            except Exception as ex:errors.append(f'{name}: {ex}')
            else:candidates.append(inspect(contents,up.name))
        except Exception as ex:errors.append(f'{up.name}: {ex}')
    for err in errors:st.error(err)
    if not candidates:return
    priority={}
    for obj in candidates:
        key=(obj['periodo'],obj['tipo'])
        rank=prioridade_periodo(obj.get('periodo_original',obj['periodo']))
        if key not in priority or rank>priority[key][0]:priority[key]=(rank,obj)
    candidates=[item[1] for item in priority.values()]
    existing=catalog(root);rows=[];seen={}
    for o in candidates:
        key=o['periodo'],o['tipo']
        prev=existing.get(key)
        if key in seen:
            state='Repetido no lote' if seen[key]==o['hash'] else 'Conflito no lote'
        elif prev and prev['hash']==o['hash']:state='Já importado (idêntico)'
        elif prev:state='Substituição solicitada'
        else:state='Novo'
        seen[key]=o['hash']
        rows.append({'Período':o['periodo'],'Mapa':o['tipo'],'Ficheiro':o['ficheiro'],'Registos':len(o['registos']),'Estado':state})
    st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
    conflict=any(r['Estado']=='Conflito no lote' for r in rows)
    replacements=[r for r in rows if r['Estado']=='Substituição solicitada']
    allow=st.checkbox('Autorizo substituir apenas os mapas assinalados, com cópia de segurança',key='s3cp_replace_confirm') if replacements else False
    if conflict:st.error('Foram encontrados dois ficheiros diferentes para o mesmo mapa e período. Retira um deles antes de importar.')
    if st.button('Guardar XML selecionados',type='primary',disabled=conflict or (bool(replacements) and not allow),key='s3cp_save'):
        count=0;done=set()
        for o in candidates:
            key=o['periodo'],o['tipo']
            if key in done:continue
            done.add(key)
            prev=existing.get(key)
            if prev and prev['hash']==o['hash']:continue
            save(root,o,replace=bool(prev));count+=1
        st.session_state['s3cp_import_feedback'] = {
            'quantidade': count,
            'ignorados': len(done) - count,
            'mapas': [f"{o['periodo']} · {o['tipo']}" for o in candidates if (o['periodo'],o['tipo']) in done],
            'quando': __import__('datetime').datetime.now().strftime('%d/%m/%Y às %H:%M:%S')
        }
        st.rerun()


def render_import_feedback():
    """Confirmacao compacta e persistente, sem desaparecer com rerun."""
    item=st.session_state.get('s3cp_import_feedback')
    if not item:
        return
    amount=int(item.get('quantidade',0))
    ignored=int(item.get('ignorados',0))
    st.markdown(
        '<div class="s3cp-save-ok">'
        '<div class="s3cp-save-title">✔ Gravação concluída</div>'
        f'<div><b>{amount}</b> mapa(s) XML guardado(s) · <b>{ignored}</b> ignorado(s)</div>'
        f'<div class="s3cp-save-date">{item.get("quando", "")}</div>'
        '</div>',unsafe_allow_html=True
    )
    if st.button('Fechar aviso',key='s3cp_dismiss_feedback',use_container_width=True):
        st.session_state.pop('s3cp_import_feedback',None)
        st.rerun()

def render_inventory(root, pdf_data=None):
    from verificacao_dados import render as render_verificacao
    with st.expander('📋 Verificação de dados · Controlo de fechos',expanded=False):
        # Evitar ler SQLite e extratos até o utilizador pedir a verificação.
        if st.checkbox('Abrir verificação de todas as fontes',key='abrir_verificacao_global'):
            render_verificacao(root,compact=True,key='sidebar_verificacao')


def _euro(v):
    try:
        amount=float(v)
        formatted=f'{abs(amount):,.2f}'.replace(',','X').replace('.',',').replace('X','.')+' €'
        return '('+formatted+')' if amount < 0 else formatted
    except:return '—'

def _summary(obj):
    if not obj:return pd.DataFrame()
    return pd.DataFrame(obj.get('resumo',[]))

def _ativos_graficos(root,periodo,tipo,obj):
    """Graficos sob procura; nunca soma resumos e registos no mesmo total."""
    import plotly.express as px
    section='AtivosFixosTangiveis' if tipo=='AFT' else 'AtivosIntangiveis'
    detail=obj.get('especiais',{}).get(section,{})
    rows=detail.get('registos',[])
    if rows:
        frame=pd.DataFrame(rows)
        metric='QuantiaEscrituradaFinal'
        if metric in frame:
            frame[metric]=pd.to_numeric(frame[metric],errors='coerce').fillna(0)
            frame=frame[frame[metric]!=0].sort_values(metric,ascending=False)
            if not frame.empty:
                fig=px.bar(frame,x='Rubrica',y=metric,title='Quantia escriturada por rubrica',labels={metric:'Valor (€)','Rubrica':'Rubrica'})
                fig.update_traces(hovertemplate='%{x}: %{y:,.2f} €<extra></extra>')
                fig.update_layout(yaxis_tickformat=',.2f',margin=dict(t=45,b=30))
                st.plotly_chart(fig,use_container_width=True,key=f'assets_detail_{tipo}_{periodo}')
    totals=detail.get('resumos',[])
    # Primeira linha macro total para AFT; primeira linha total para AI.
    total=next((v for v in totals if 'TotalQuantiaEscrituradaFinal' in v and (tipo=='AI' or v.get('MacroRubrica')=='AFT')),None)
    if total:
        fields=[('Quantia inicial','TotalQuantiaEscrituradaInicial'),('Adições','TotalAdicoes'),('Depreciações/Amortizações','TotalDepreciacoesPeriodo' if tipo=='AFT' else 'TotalAmortizacoesPeriodo'),('Diminuições','TotalDiminuicoes'),('Quantia final','TotalQuantiaEscrituradaFinal')]
        vals=[{'Componente':label,'Valor (€)':float(total.get(key,0))} for label,key in fields]
        cols=st.columns(3)
        for col,item in zip(cols,[vals[0],vals[1],vals[-1]]):col.metric(item['Componente'],_euro(item['Valor (€)']))
        fig=px.bar(pd.DataFrame(vals),x='Componente',y='Valor (€)',title='Movimentos patrimoniais do período acumulado')
        fig.update_traces(hovertemplate='%{x}: %{y:,.2f} €<extra></extra>')
        st.plotly_chart(fig,use_container_width=True,key=f'assets_movements_{tipo}_{periodo}')
    series_rows=[]
    for (per,kind) in sorted(catalog(root)):
        if kind!=tipo:continue
        historic=load(root,per,tipo)
        if not historic:continue
        cand=historic.get('especiais',{}).get(section,{}).get('resumos',[])
        hit=next((v for v in cand if 'TotalQuantiaEscrituradaFinal' in v and (tipo=='AI' or v.get('MacroRubrica')=='AFT')),None)
        if hit:series_rows.append({'Período':per,'Quantia escriturada (€)':float(hit['TotalQuantiaEscrituradaFinal'])})
    if len(series_rows)>1:
        fig=px.line(pd.DataFrame(series_rows),x='Período',y='Quantia escriturada (€)',markers=True,title='Evolução por fecho mensal')
        fig.update_traces(hovertemplate='%{x}: %{y:,.2f} €<extra></extra>')
        st.plotly_chart(fig,use_container_width=True,key=f'assets_evolution_{tipo}_{periodo}')

def render(root,selected):
    inventory=catalog(root)
    if not inventory:
        st.info('Importa os primeiros XML SNC-AP na barra lateral. Não é necessário voltar a importar DR, BLC ou DFC existentes em PDF.')
        return
    periods=sorted({p for p,_ in inventory})
    period=period_selectbox('Fecho XML',periods,index=periods.index(selected) if selected in periods else len(periods)-1,key='s3cp_panel_period')
    kinds=sorted(k for p,k in inventory if p==period)
    st.caption('Mapas disponíveis: '+', '.join(kinds))
    opcoes=['Orçamento de despesa','Orçamento de receita','Ativos e património','PMP — BA por entidade','Mapas e séries históricas']
    secao=st.selectbox('Análise XML',opcoes,key='v615_s3cp_section')
    if secao == 'Orçamento de despesa':
        obj=load(root,period,'DODES')
        if obj:
            table=_summary(obj)
            st.subheader('Execução orçamental da despesa')
            st.dataframe(table,hide_index=True,use_container_width=True)
            vals=obj['resumo']; total={}
            for v in vals:
                for field in ('TotalDotacoesCorrigidas','TotalCabimentos','TotalCompromissos','TotalObrigacoes','TotalGeralDespesasPagasLiquidas'):
                    total[field]=total.get(field,0)+float(v.get(field,0))
            cols=st.columns(4)
            for col,(label,field) in zip(cols,[('Dotação corrigida','TotalDotacoesCorrigidas'),('Compromissos','TotalCompromissos'),('Obrigações','TotalObrigacoes'),('Pagamentos','TotalGeralDespesasPagasLiquidas')]):col.metric(label,_euro(total.get(field)))
            if total.get('TotalDotacoesCorrigidas'):
                st.metric('Compromissos / dotações corrigidas',f"{100*total['TotalCompromissos']/total['TotalDotacoesCorrigidas']:.1f}%")
            st.markdown('**Execução detalhada por classificação económica, atividade e fonte de financiamento**')
            df=pd.DataFrame(obj['registos']);st.dataframe(df,hide_index=True,use_container_width=True)
        else:st.info('Sem DODES para este período.')
    if secao == 'Orçamento de receita':
        obj=load(root,period,'DOREC')
        if obj:
            st.subheader('Execução orçamental da receita')
            st.dataframe(_summary(obj),hide_index=True,use_container_width=True)
            vals=obj['resumo'];tot={}
            for r in vals:
                for field in ('TotalPrevisoesCorrigidas','TotalReceitasLiquidadas','TotalGeralReceitasCobradasLiquidas'):
                    tot[field]=tot.get(field,0)+float(r.get(field,0))
            cols=st.columns(3)
            for col,(label,field) in zip(cols,[('Previsões corrigidas','TotalPrevisoesCorrigidas'),('Receitas liquidadas','TotalReceitasLiquidadas'),('Cobrança líquida','TotalGeralReceitasCobradasLiquidas')]):col.metric(label,_euro(tot.get(field)))
            st.dataframe(pd.DataFrame(obj['registos']),hide_index=True,use_container_width=True)
        else:st.info('Sem DOREC para este período.')
    if secao == 'Ativos e património':
        for tipo,title in [('AFT','Ativos fixos tangíveis'),('AI','Ativos intangíveis'),('DAPL','Alterações no património líquido')]:
            obj=load(root,period,tipo)
            st.subheader(title)
            if not obj:st.info('Sem '+tipo+' para este período.');continue
            if tipo=='DAPL':st.dataframe(pd.DataFrame(obj['registos']),hide_index=True,use_container_width=True)
            else:
                _ativos_graficos(root,period,tipo,obj)
                for section,d in obj['especiais'].items():
                    with st.expander(section,expanded=section in ('AtivosFixosTangiveis','AtivosIntangiveis')):
                        if d['resumos']:st.dataframe(pd.DataFrame(d['resumos']),hide_index=True,use_container_width=True)
                        if d['registos']:st.dataframe(pd.DataFrame(d['registos']),hide_index=True,use_container_width=True)
    if secao == 'PMP — BA por entidade':
        obj=load(root,period,'BA')
        if obj:
            vals=pmp_ba(obj)
            st.subheader('Componentes do PMP a partir do BA')
            st.caption('Filtro NIFEntidadeParceira = 999999990. BA04: saldo final, crédito menos débito para contas de terceiros; débito menos crédito para 62.')
            for name,value in vals.items():st.metric(name,_euro(value))
            st.metric('Dívida total',_euro(sum(vals.get(k,0) for k in ('Fornecedores','Investimentos','Outros credores'))))
            st.success('Estes valores do BA alimentam agora o cálculo do PMP em quatro trimestres. As contas 31/43/45 continuam a ser apuradas pelos extratos sem OD.')
        else:st.info('Sem BA para este período.')
    if secao == 'Mapas e séries históricas':
        st.subheader('Evolução histórica e dados de suporte')
        tipo=st.selectbox('Tipo de mapa',sorted(set(k for _,k in inventory)),key='s3cp_series_type')
        keys={'DR':['ValorAnoCorrente'],'BLC':['ValorAnoCorrente'],'DODES':['TotalCompromissos','TotalDotacoesCorrigidas','TotalGeralDespesasPagasLiquidas'],'DOREC':['TotalGeralReceitasCobradasLiquidas','TotalPrevisoesCorrigidas'],'DFC':['TotalAnoCorrente']}
        options=keys.get(tipo,[])
        if options:
            selected_field=st.selectbox('Campo',options,key='s3cp_series_field')
            points=series(root,tipo,selected_field)
            if points:
                df=pd.DataFrame(points);st.line_chart(df.set_index('Período'))
        obj=load(root,period,tipo)
        if obj:
            st.dataframe(pd.DataFrame(obj.get('registos',[])),hide_index=True,use_container_width=True)
            st.download_button('Exportar registos CSV',pd.DataFrame(obj.get('registos',[])).to_csv(index=False).encode('utf-8-sig'),f'{tipo}_{period}.csv','text/csv',key='s3cp_export')
