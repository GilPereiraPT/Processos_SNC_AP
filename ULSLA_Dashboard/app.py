from pathlib import Path
from periodos_snc_ap import periodo_legenda, periodo_curto, referencia, mes_civil, normalizar_periodo, prioridade_periodo
import json, io
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from ulsla_branding import period_selectbox
from ulsla_branding import hero
from importador_pdf import validate_bundle, NEEDED
from painel_s3cp_xml import import_widget as import_s3cp_xml, render as render_s3cp_xml, render_import_feedback, render_inventory
from importador_s3cp_xml import catalog as catalog_s3cp, as_dashboard_period
from comparador import account_names, series as account_series, compare as account_compare, COLUMNS
from pools import read_map, pool_details, pool_series
from divida_xml import parse_xml, summary, write_snapshot, snapshots, load_snapshot, enriched_debt, supplier_summary, payment_days
from comparador_divida import render as render_comparacao_divida
from comparativo_mensal import render_comparativo

ROOT=Path(__file__).resolve().parent
STORE=ROOT/'dados_mensais.json'
SEED=ROOT/'seed_2026_09.json'
GROUPS=['dr','balanco','dfc','balancete']
LABELS={
'dr':{'rendimentos_impostos':'Impostos, contribuições e taxas','vendas':'Vendas','prestacoes_servicos':'Prestações de serviços','transferencias':'Transferências correntes','outros_rendimentos':'Outros rendimentos','imparidade_inventarios':'Imparidade de inventários','imparidade_receber':'Imparidade de dívidas a receber','provisoes':'Provisões','imparidade_investimentos_nao_depreciaveis':'Imparidade de investimentos não depreciáveis','justo_valor':'Variações de justo valor','imparidade_investimentos_depreciaveis':'Imparidade de investimentos depreciáveis','imposto_rendimento':'Imposto sobre o rendimento','consumos':'Consumos','fse':'Fornecimentos e serviços externos','pessoal':'Gastos com pessoal','outros_gastos':'Outros gastos','ebitda':'Resultado antes de depreciações e financeiros','depreciacoes':'Depreciações e amortizações','operacional':'Resultado operacional','financeiros':'Resultado financeiro (líquido)','resultado':'Resultado líquido'},
'balanco':{'ativo':'Ativo total','ativo_corrente':'Ativo corrente','ativo_nao_corrente':'Ativo não corrente','inventarios':'Inventários','clientes':'Clientes, contribuintes e utentes','outras_contas_receber':'Outras contas a receber','caixa':'Caixa e depósitos','passivo':'Passivo total','passivo_corrente':'Passivo corrente','passivo_nao_corrente':'Passivo não corrente','fornecedores':'Fornecedores','fornecedores_investimento':'Fornecedores de investimentos','adiantamentos_clientes':'Adiantamentos de clientes','outras_contas_pagar':'Outras contas a pagar','patrimonio':'Património líquido','ativos_fixos':'Ativos fixos tangíveis'},
'dfc':{'clientes_recebimentos':'Recebimentos de clientes','utentes_recebimentos':'Recebimentos de utentes','fornecedores_pagamentos':'Pagamentos a fornecedores','pessoal_pagamentos':'Pagamentos ao pessoal','operacional':'Fluxo operacional','investimento':'Fluxo investimento','financiamento':'Fluxo financiamento','cobertura_prejuizos':'Cobertura de prejuízos','variacao_caixa':'Variação de caixa','caixa_inicial':'Caixa inicial','caixa_final':'Caixa final','subsidios_investimento':'Subsídios ao investimento'},
'balancete':{'igcp_aumento_capital':'IGCP — Aumento de capital','igcp_prr':'IGCP — PRR','igcp_hla':'IGCP — HLA','fornecedores_factoring':'Fornecedores — factoring','fornecedores_recepcao':'Faturas em receção/conferência','acrescimos_rendimentos_acss':'Acréscimos de rendimentos ACSS','adiantamentos_cp_2026':'Adiantamentos CP 2026','investimentos_curso':'Investimentos em curso','servicos_medicos_empresas':'Serviços médicos — empresas','honorarios_medicos':'Honorários médicos','transporte_doentes':'Transporte de doentes','medicamentos_farmacias':'Medicamentos — farmácias','medicamentos_consumo':'Medicamentos — consumo','subcontratos_saude':'Subcontratos — serviços de saúde'}}

def _dados_assinatura():
    """Invalida o cache quando muda o histórico ou um ficheiro XML importado."""
    paths = [SEED, STORE]
    pasta_xml = ROOT / 'dados_s3cp_xml'
    if pasta_xml.exists():
        paths.extend(pasta_xml.glob('*/*.json.gz'))
    resultado = []
    for path in paths:
        try:
            meta = path.stat()
            resultado.append((str(path), meta.st_mtime_ns, meta.st_size))
        except OSError:
            continue
    return tuple(sorted(resultado))

@st.cache_data(show_spinner=False, max_entries=4)
def _read_all_cached(assinatura):
    return _read_all_uncached()

def read_all():
    return _read_all_cached(_dados_assinatura())

def _read_all_uncached():
    seed=json.loads(SEED.read_text(encoding='utf8')) if SEED.is_file() else {}
    out={}
    # Consolidar versoes antigas 12/13/14 em dezembro; prevalece o ultimo fecho.
    candidates=[(seed['periodo'],seed)] if seed.get('periodo') else []
    if STORE.exists():
        try:candidates.extend(json.loads(STORE.read_text(encoding='utf8')).items())
        except Exception as ex:st.warning(f'Não foi possível ler dados_mensais.json: {ex}')
    for old,obj in sorted(candidates,key=lambda t:(normalizar_periodo(t[0]),prioridade_periodo(t[0]))):
        key=normalizar_periodo(old)
        if isinstance(obj,dict):
            current=dict(obj);current['periodo']=key
            out[key]=current
    # PDF previamente guardado tem prioridade sobre os mapas XML correspondentes.
    try:
        for key in sorted({normalizar_periodo(period) for period, kind in catalog_s3cp(ROOT)}):
            parsed=as_dashboard_period(ROOT,key)
            target=out.setdefault(key,{'periodo':key,'origem':'XML SNC-AP'})
            for group in ('dr','balanco','dfc'):
                if not target.get(group) and parsed.get(group):target[group]=parsed[group]
    except Exception as ex:st.warning(f'Falha ao consultar catálogo XML: {ex}')
    return out

def save_all(data):
    temp=STORE.with_suffix('.tmp');temp.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf8');temp.replace(STORE)

def euro(v,small=False):
    if v is None:return '—'
    s=f'{v/1e6:,.2f} M€' if small else f'{v:,.2f} €'
    return s.replace(',','X').replace('.',',').replace('X','.')

def tabela_euros(df, colunas=None):
    """Formata valores monetários em tabelas mantendo os números para cálculo/ordenação."""
    colunas = colunas or []
    candidatas = {'valor', 'valordoc', 'total', 'saldo', 'credito', 'crédito',
                  'n', 'n-1', 'debito', 'débito', 'movimento mensal',
                  'saldo inicial', 'saldo final', 'acumulado', 'movimento',
                  'saldo_devedor', 'saldo_credor', 'debito_periodo', 'credito_periodo',
                  'debito_acumulado', 'credito_acumulado'}
    formatacao = {}
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            continue
        nome = str(col).strip().lower()
        moeda = (col in colunas or nome in candidatas or '(€)' in nome or
                 nome.endswith(' (€)') or nome.startswith('valor ') or
                 nome.startswith('saldo ') or nome.startswith('crédito ') or
                 nome.startswith('divida ') or nome.startswith('dívida '))
        if moeda and '%' not in nome and 'dias' not in nome and 'prazo' not in nome:
            formatacao[col] = lambda valor: euro(valor) if pd.notna(valor) else '—'
    return df.style.format(formatacao) if formatacao else df

def get(d,g,k):return d.get(g,{}).get(k)
def calc(d):
    dr=d.get('dr',{});b=d.get('balanco',{});f=d.get('dfc',{});bal=d.get('balancete',{})
    rec=sum(dr.get(k,0) for k in ('rendimentos_impostos','vendas','prestacoes_servicos','transferencias','outros_rendimentos'))
    gastos=sum(dr.get(k,0) for k in ('consumos','fse','pessoal','outros_gastos','depreciacoes'))
    return {'rendimentos':rec,'gastos':gastos,'divida_fornecedores':b.get('fornecedores',0)+b.get('fornecedores_investimento',0),
    'fundo_maneio':b.get('ativo_corrente',0)-b.get('passivo_corrente',0),
    'liquidez_corrente':b.get('ativo_corrente',0)/b.get('passivo_corrente',1) if b.get('passivo_corrente') else None,
    'caixa_sem_capital':b.get('caixa',0)-bal.get('igcp_aumento_capital',0) if bal else None}

def checks(d):
    b=d.get('balanco',{});f=d.get('dfc',{});dr=d.get('dr',{});results=[]
    tests=[('Equação patrimonial',b.get('ativo'),b.get('passivo',0)+b.get('patrimonio',0)),
           ('Resultado da DR × Balanço',dr.get('resultado'),b.get('patrimonio_resultado')),
           ('Saldo de caixa Balanço × DFC',b.get('caixa'),f.get('caixa_final')),
           ('Fluxos DFC × variação de caixa',sum(f.get(k,0) for k in ['operacional','investimento','financiamento']) if f else None,f.get('variacao_caixa')),
           ('Caixa inicial + variação',f.get('caixa_inicial',0)+f.get('variacao_caixa',0) if f else None,f.get('caixa_final')),
           ('Resultado DR × composição',sum(dr.get(k,0) for k in ['rendimentos_impostos','vendas','prestacoes_servicos','transferencias','outros_rendimentos'])-sum(dr.get(k,0) for k in ['consumos','fse','pessoal','outros_gastos','depreciacoes'])+dr.get('financeiros',0)+sum(dr.get(k,0) for k in ['imparidade_inventarios','imparidade_receber','provisoes','imparidade_investimentos_nao_depreciaveis','justo_valor','imparidade_investimentos_depreciaveis','imposto_rendimento']) if dr else None,dr.get('resultado'))]
    for n,a,c in tests:
        delta=round(a-c,2) if a is not None and c is not None else None
        results.append({'Controlo':n,'Diferença (€)':delta,'Estado':'OK' if delta is not None and abs(delta)<0.02 else ('Por validar' if delta is None else 'Divergência')})
    return pd.DataFrame(results)

VERSAO_DASHBOARD = '6.15.4 — Navegação rápida e cálculos sob pedido'
st.set_page_config(page_title='ULSLA | Dashboard Financeiro v6.15.4',page_icon='🏥',layout='wide')
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap');
html,body,[class*="css"],.stApp{font-family:'DM Sans',system-ui,sans-serif}
.stApp{background:linear-gradient(155deg,#f5f8fc 0%,#edf3f8 100%);color:#203049}
.block-container{padding-top:1.15rem;padding-bottom:3rem;max-width:1630px}
section[data-testid="stSidebar"]{background:#11263e;color:#ebf4ff}
section[data-testid="stSidebar"] *{color:inherit}
section[data-testid="stSidebar"] input{color:#18293e!important}
section[data-testid="stSidebar"] [data-testid="stFileUploader"]{background:#ffffff!important;border-radius:14px;padding:10px;color:#1c324b!important}
section[data-testid="stSidebar"] [data-testid="stFileUploader"] *{color:#1c324b!important}
section[data-testid="stSidebar"] [data-testid="stFileUploaderFileName"], section[data-testid="stSidebar"] [data-testid="stFileUploaderFileName"] *{color:#163a60!important;font-weight:700!important}
section[data-testid="stSidebar"] [data-testid="stFileUploader"] small{color:#4d6279!important}
section[data-testid="stSidebar"] [data-testid="stFileUploader"] button{background:#e4edf6!important;color:#18334e!important}

div[data-testid="stMetric"]{background:white;border:1px solid #dbe5ef;border-radius:18px;padding:18px 20px;box-shadow:0 6px 22px rgba(24,52,87,.065)}
div[data-testid="stMetricLabel"]{font-size:.87rem;font-weight:650;color:#53667f}
div[data-testid="stMetricValue"]{font-size:1.55rem;color:#19334e;letter-spacing:-.05em}
h1,h2,h3{letter-spacing:-.045em;color:#19334e}h1{font-size:2rem!important}h3{font-size:1.22rem!important}
div[data-testid="stTabs"] button[role="tab"]{font-weight:700;border-radius:10px 10px 0 0;padding:.7rem 1.1rem}
div[data-testid="stTabs"] button[aria-selected="true"]{color:#007d98;border-bottom:3px solid #078ca3}
div[data-testid="stPlotlyChart"],div[data-testid="stDataFrame"]{border:1px solid #e1e8f0;border-radius:15px;background:#fff;padding:7px;box-shadow:0 5px 20px rgba(24,52,87,.035)}
.hero-ulsla{border-radius:20px;background:linear-gradient(120deg,#102940,#154d67 68%,#158c9a);padding:24px 30px;margin-bottom:20px;color:white;box-shadow:0 16px 32px rgba(15,48,80,.12)}
.hero-ulsla h2{color:#fff!important;font-size:1.75rem;margin:0 0 4px}.hero-ulsla p{color:#c9e8ed;margin:0}
.insight-note{padding:12px 16px;border-left:4px solid #e9a935;background:#fff8e9;border-radius:10px;color:#79581c;margin:8px 0}

/* Barra lateral: evitar texto claro sobre botoes, seletores e expanders claros. */
section[data-testid="stSidebar"] [data-testid="stExpander"] details summary,
section[data-testid="stSidebar"] [data-testid="stExpander"] details summary * {color:#ecf5ff!important;background:transparent!important;font-weight:650!important}
section[data-testid="stSidebar"] [data-testid="stExpander"] {background:#1b3551!important;border:1px solid #3e5871!important;border-radius:12px!important}
section[data-testid="stSidebar"] [data-testid="stExpander"] details {background:transparent!important}
section[data-testid="stSidebar"] [data-testid="stButton"] button {background:#e5f1fa!important;color:#15324d!important;border:1px solid #a6c5dc!important;font-weight:750!important;min-height:38px}
section[data-testid="stSidebar"] [data-testid="stButton"] button *,section[data-testid="stSidebar"] [data-testid="stButton"] button p {color:#15324d!important}
section[data-testid="stSidebar"] [data-testid="stButton"] button:hover {background:#b9e4f0!important;color:#0a273b!important}
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] *,
section[data-testid="stSidebar"] [data-testid="stSelectbox"] [data-baseweb="select"] input {color:#17344e!important}
section[data-testid="stSidebar"] [data-testid="stDataFrame"]{background:#ffffff!important;padding:3px!important}
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"],section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] * {color:#c9d9e8!important}
section[data-testid="stSidebar"] .s3cp-save-ok {background:#143f49;border:1px solid #43a9a3;border-radius:12px;padding:12px 14px;margin:0 0 9px;line-height:1.6;color:#f0fbfd!important;font-size:.9rem}
section[data-testid="stSidebar"] .s3cp-save-title {font-weight:800;color:#ecfff8!important;font-size:1rem;margin-bottom:3px}
section[data-testid="stSidebar"] .s3cp-save-date {font-size:.77rem;color:#c5e4e5!important;margin-top:3px}
</style>""",unsafe_allow_html=True)
data=read_all(); periods=sorted(data.keys());
with st.sidebar:
    st.title('ULSLA | Financeiro')
    st.caption(VERSAO_DASHBOARD + ' | Porta automática')
    st.caption('SNC-AP · Importações · histórico mensal')
    st.divider()
    render_import_feedback()
    render_inventory(ROOT, data)
    st.divider()
    st.write('**Importação SNC-AP por XML — principal**')
    import_s3cp_xml(ROOT)
    st.divider()
    with st.expander('Importação histórica por PDF (alternativa)',expanded=False):
        st.caption('Os fechos antigos por PDF são conservados. Não precisas de reenviar DR, BLC ou DFC.')
    st.write('**Importação antiga por PDF**')
    pdfs=st.file_uploader('Carregar os 4 PDF do mesmo fecho',type=['pdf'],accept_multiple_files=True,key='pdf_snc_ap',help='DR, Balanço, DFC e Balancete. A ordem não importa.')
    if pdfs:
        st.caption('PDF selecionados:')
        for _file in pdfs: st.markdown('📄 **'+_file.name+'**')
        try:
            new,missing,parses=validate_bundle(pdfs)
            newperiod=normalizar_periodo(new['periodo'])
            new['periodo']=newperiod
            st.success(f'Quatro documentos identificados: {newperiod}.')
            st.dataframe(pd.DataFrame([{'Documento':p['tipo'].upper(),'Ficheiro':p['ficheiro'],'Rubricas extraídas':len(p['valores']),'Páginas':p['paginas']} for p in parses]),hide_index=True)
            preview=[]
            for group in GROUPS:
                for key,value in new.get(group,{}).items():
                    preview.append({'Mapa':group.upper(),'Conta / indicador':LABELS.get(group,{}).get(key,key),'Valor (€)':value})
            with st.expander('Conferir valores extraídos',expanded=False):
                st.dataframe(pd.DataFrame(preview).style.format({'Valor (€)':euro}),hide_index=True,width="stretch")
            # Rubricas do balancete ausentes são assumidas como zero, com aviso auditável.
            # DR, Balanço e DFC mantêm as validações de documentos obrigatórios.
            contas_ausentes = missing.get('balancete', [])
            if contas_ausentes:
                descricoes = [f"{LABELS['balancete'].get(k,k)} ({k})" for k in contas_ausentes]
                st.warning('Rubricas não encontradas no balancete e assumidas com saldo 0,00 €: ' + ', '.join(descricoes))
            mandatory={k:v for k,v in missing.items() if v and k!='balancete'}
            if mandatory:st.error(f'Rubricas indispensáveis em falta: {mandatory}. Não é possível confirmar.')
            else:
                trial=checks(new)
                problems=trial[trial['Estado']=='Divergência']
                st.dataframe(trial.style.format({'Diferença (€)':lambda v:euro(v) if pd.notna(v) else '—'}),hide_index=True,width="stretch")
                if not problems.empty:
                    st.error('Existem divergências de reconciliação. A importação foi bloqueada para evitar valores inconsistentes.')
                    st.info(f"Diagnóstico DR: Vendas = {euro(new.get('dr', {}).get('vendas'))}; Resultado DR = {euro(new.get('dr', {}).get('resultado'))}; Versão = {VERSAO_DASHBOARD}.")
                    with st.expander('Detalhe das rubricas extraordinárias da reconciliação DR'):
                        st.dataframe(pd.DataFrame([{'Rubrica': LABELS['dr'].get(k,k), 'Valor (€)':new.get('dr',{}).get(k,0)} for k in ['imparidade_inventarios','imparidade_receber','provisoes','imparidade_investimentos_nao_depreciaveis','justo_valor','imparidade_investimentos_depreciaveis','imposto_rendimento']]).style.format({'Valor (€)':euro}),hide_index=True,width="stretch")
                    st.caption('Se as Vendas aparecerem como indisponíveis, confirma se o importador_pdf.py foi substituído. Não alteramos a tolerância contabilística.')
                else:
                    existing=newperiod in data
                    if existing:st.warning(f'Já existe um fecho para {newperiod}. Uma confirmação substituirá APENAS esse período, mantendo os restantes.')
                    confirmation=st.checkbox('Validei os quatro documentos e autorizo a gravação do mês',key='pdf_confirm')
                    if st.button('Confirmar importação dos quatro PDF',type='primary',disabled=not confirmation,width="stretch"):
                        current=read_all()
                        current[newperiod]=new
                        save_all(current)
                        st.success('Fecho contabilístico guardado. Selecione o mês no menu lateral.')
                        st.rerun()
        except Exception as e:st.error(f'Não foi possível importar os PDF: {e}')
    st.divider()
    st.write('**Dívidas, créditos e pagamentos — XML**')
    xmls=st.file_uploader('Carregar os 3 XML do mesmo mês',type=['xml'],accept_multiple_files=True,key='xml_financeiro',help='Dividas.xml, Pagamentos.xml e Creditos.xml. A ordem é livre.')
    if xmls:
        for _x in xmls:st.markdown('🧾 **'+_x.name+'**')
        try:
            parsed=[parse_xml(x) for x in xmls]
            kinds=[x[0] for x in parsed];pers=[x[1] for x in parsed]
            if len(parsed)!=3 or set(kinds)!={'Dividas','Pagamentos','Creditos'} or len(set(pers))!=1:
                st.error('Carrega exatamente Dividas, Pagamentos e Creditos, todos referentes ao mesmo mês.')
            else:
                period_xml=pers[0]
                with st.expander('Conferir totais dos três XML',expanded=True):
                    overview=[]
                    for kind,_,dfx in parsed:
                        for code,values in summary(dfx,kind,period_xml).items():
                            overview.append({'Documento':kind,'Tipo':code,'Registos':values['documentos'],'Valor':values['valor']})
                    st.dataframe(tabela_euros(pd.DataFrame(overview),['Valor']),hide_index=True,width="stretch")
                existing_xml=period_xml in snapshots(ROOT)
                if existing_xml:st.warning('Existem XML guardados para '+period_xml+'. Confirma se pretendes substituir esse fecho.')
                confirm_xml=st.checkbox('Confirmei os três ficheiros XML deste mês',key='confirm_xml')
                if st.button('Guardar fecho XML '+period_xml,disabled=not confirm_xml,type='primary',width="stretch"):
                    write_snapshot(ROOT,period_xml,{k:df for k,_,df in parsed},replace=existing_xml)
                    st.success('Histórico XML guardado.');st.rerun()
        except Exception as exc:st.error('Erro a ler os XML: '+str(exc))
    st.divider()
    st.write('**Importação alternativa por Excel**')
    template=[]
    for group in GROUPS:
        for code,name in LABELS[group].items():template.append({'periodo':'2026-10','grupo':group,'codigo':code,'rubrica':name,'valor':None,'valor_homologo':None})
    template_df=pd.DataFrame(template)
    output=io.BytesIO()
    with pd.ExcelWriter(output,engine='openpyxl') as w: template_df.to_excel(w,index=False,sheet_name='Indicadores')
    st.download_button('Descarregar modelo Excel',output.getvalue(),'modelo_importacao_ulsla.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',width="stretch")
    upload=st.file_uploader('Importar mês (Excel)',type=['xlsx'])
    if upload:
        try:
            incoming=pd.read_excel(upload,sheet_name='Indicadores',dtype={'periodo':str,'grupo':str,'codigo':str})
            required={'periodo','grupo','codigo','valor'}
            if not required.issubset(incoming.columns):raise ValueError('Colunas em falta: '+str(required-set(incoming.columns)))
            incoming=incoming.dropna(subset=['valor']).copy()
            incoming['periodo']=incoming['periodo'].astype(str).str.strip()
            if incoming.empty:raise ValueError('Sem linhas preenchidas')
            if not incoming['periodo'].str.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])').all():raise ValueError('Período inválido; usar AAAA-MM')
            if not incoming.apply(lambda r:r['grupo'] in LABELS and r['codigo'] in LABELS[r['grupo']],axis=1).all():raise ValueError('Grupo/código desconhecido')
            if incoming.duplicated(['periodo','grupo','codigo']).any():raise ValueError('Existem indicadores repetidos no mesmo período')
            st.info(f'{len(incoming)} indicadores válidos para {incoming.periodo.nunique()} mês(es). A importação substitui os valores dos mesmos códigos.')
            if st.button('Confirmar importação',type='primary'):
                for _,r in incoming.iterrows():
                    per=r['periodo'];obj=data.setdefault(per,{'periodo':per,'referencia':per+'-fim-do-mês','origem':'Importação Excel','natureza':'DR/DFC acumulados; Balanço saldos'})
                    obj.setdefault(r['grupo'],{})[r['codigo']]=float(r['valor'])
                    if 'valor_homologo' in incoming.columns and pd.notna(r['valor_homologo']):obj.setdefault(r['grupo']+'_n1',{})[r['codigo']]=float(r['valor_homologo'])
                save_all(data);st.success('Dados guardados.');st.rerun()
        except Exception as e:st.error(f'Importação não efetuada: {e}')
    st.divider()
    st.caption('Não são criados meses por interpolação. Um indicador em falta permanece indisponível.')

# Uma instalação sem dados continua a permitir as importações da barra lateral.
if not periods:
    hero('ULSLA | Dashboard Financeiro', 'Importe os primeiros dados para começar.', 'SNC-AP · Histórico financeiro local')
    st.info('Ainda não existem fechos financeiros. Use a importação XML/PDF na barra lateral ou o módulo Importação de Dados no portal.')
    st.stop()

# O período principal é selecionado no topo, fora da barra lateral.
hero('ULSLA | Dashboard Financeiro', 'Indicadores, análises comparativas e histórico financeiro.', 'SNC-AP · Informação financeira e patrimonial')
with st.container(border=True):
    st.markdown('### 📅 Período de referência dos indicadores')
    c_select,c_info=st.columns([1.05,2])
    with c_select:
        selection=period_selectbox('Selecionar fecho SNC-AP',periods,index=len(periods)-1,
            format_func=periodo_legenda,key='v613_main_period')
    with c_info:
        report_date=referencia(selection)
        st.markdown(f'**DADOS REPORTADOS A: {report_date}**')
        st.caption(f'Fecho SNC-AP: {selection} · DR e DFC: valores acumulados; Balanço: saldos à data.')

d=data[selection]; c=calc(d);dr=d.get('dr',{});b=d.get('balanco',{});f=d.get('dfc',{});bal=d.get('balancete',{})

# Só a data de referência produz uma atualização global. A navegação e os filtros
# de cada área correm num fragmento e não reexecutam todo o dashboard.
@st.fragment
def _render_area_ativa():
    st.markdown('### Área de análise')
    tipo = st.radio('Tipo de análise', ['Essencial', 'Avançada'], horizontal=True,
                    key='v615_nav_group', label_visibility='collapsed')
    essenciais = ['Visão executiva', 'Acompanhamento da contratualização', 'Indicadores financeiros', 'Dívida e pagamentos', 'Balanço e liquidez', 'Fluxos de caixa', 'XML SNC-AP · Orçamento e Património', 'PMP — Apuramento contabilístico', 'Painel interativo']
    avancadas = ['Exploração da despesa', 'Evolução mensal', 'Comparador de contas', 'Comparador por Pools', 'Reconciliar e validar', 'Dados e metodologia', 'Análise económico-financeira comparativa', 'Verificação de dados']
    opcoes = essenciais if tipo == 'Essencial' else avancadas
    active_page = st.selectbox('Abrir área', opcoes, key='v615_active_quick' if tipo == 'Essencial' else 'v615_active_advanced')
    if tipo == 'Avançada':
        st.caption('Os módulos avançados não são calculados até serem selecionados.')
    st.divider()

    if active_page == 'Verificação de dados':
        from verificacao_dados import render as render_verificacao
        render_verificacao(ROOT,key='main_verificacao')

    if active_page == 'Acompanhamento da contratualização':
        from acompanhamento_acss import render as render_acss
        render_acss(ROOT,data,selection)

    if active_page == 'Visão executiva':
        from visao_executiva import render as render_visao_executiva
        render_visao_executiva(data,selection,ROOT)

    if active_page == 'Painel interativo':
        st.subheader('Painel de análise comparativa')
        st.caption('Escolhe até três fechos e analisa rubricas de gestão, contas SNC-AP, Pool 1 e Pool 2. Os três períodos são independentes.')
        available=sorted([per for per,rec in data.items() if rec.get('contas_balancete')],reverse=True)
        if not available:
            st.info('Para visualizar as análises por Pools, importa primeiro um Balancete SNC-AP.')
        else:
            controls=st.columns([1,1,1,1.2])
            chosen_periods=[]
            for ix in range(3):
                with controls[ix]:
                    period=period_selectbox(f'Período {ix+1}', ['—']+available, index=min(ix+1,len(available)),key=f'v5_per_{ix}')
                    if period!='—' and period not in chosen_periods:chosen_periods.append(period)
                    elif period!='—':st.caption('Este período já foi selecionado.')
            with controls[3]:
                source=st.selectbox('Perspetiva de análise',['Pools 1','Pools 2','Contas SNC-AP','Indicadores financeiros'],key='v5_source')
            chosen_periods=sorted(chosen_periods)
            st.caption('Os períodos são apresentados por ordem cronológica. Azul = período anterior; laranja = período seguinte; Δ = mais recente − mais antigo.')
            if chosen_periods:
                st.markdown('#### Comparação entre períodos')
                measures=st.columns([1,2])
                with measures[0]:
                    measure=st.radio('Grandeza',['acumulado','saldo','mensal'],format_func=lambda x:{'acumulado':'Movimento acumulado (ano)','saldo':'Saldo contabilístico','mensal':'Movimento do mês'}[x],horizontal=False,key='v5_measure')
                with measures[1]:
                    st.markdown('<div class="insight-note">Os movimentos mensais de gastos e rendimentos exigem balancetes de dois fechos consecutivos. As comparações não preenchem automaticamente meses ausentes.</div>',unsafe_allow_html=True)
                names=account_names(data)
                mapping=read_map()
                if source.startswith('Pools'):
                    level='Pool 1' if source=='Pools 1' else 'Pool 2'
                    frame=pool_series(data,mapping,measure,level)
                    frame=frame[frame['Período'].isin(chosen_periods)]
                    candidates=sorted(frame['Pool'].unique()) if not frame.empty else []
                    defaults=[x for x in (['Medicamentos','Prestação Serviços Médicos','Transporte de doentes','Hoteleiros','Meios complementares de diagnóstico'] if level=='Pool 1' else ['Pessoal Médico','Pessoal de Enfermagem','Pessoal Assistente Operacional','Gastos pessoal - gerais']) if x in candidates]
                    selected=st.multiselect('Rubricas a apresentar',candidates,default=defaults or candidates[:7],key='v5_pools')
                    frame=frame[frame['Pool'].isin(selected)].rename(columns={'Pool':'Rubrica'})
                elif source=='Contas SNC-AP':
                    candidates=sorted(names,key=lambda c:(len(c),c))
                    defaults=[x for x in ['61','62','63','6221911','6255','612411'] if x in candidates]
                    selected=st.multiselect('Contas a apresentar',candidates,default=defaults or candidates[:5],format_func=lambda x:x+' · '+names[x],key='v5_accounts')
                    frame=account_series(data,selected,measure).rename(columns={'Conta':'Rubrica'})
                    frame=frame[frame['Período'].isin(chosen_periods)][['Período','Rubrica','Valor (€)']]
                    frame['Rubrica']=frame['Rubrica'].map(lambda x:x+' · '+names.get(x,''))
                else:
                    indicator_options=[(group,key,label) for group in ['dr','balanco','dfc'] for key,label in LABELS[group].items()]
                    option_map={f'{g} / {name}':(g,k) for g,k,name in indicator_options}
                    options=list(option_map)
                    selected=st.multiselect('Indicadores a apresentar',options,default=[x for x in options if x.endswith(('Gastos com pessoal','Fornecimentos e serviços externos','Resultado líquido'))],key='v5_indicators')
                    rows=[]
                    for period in chosen_periods:
                        for name in selected:
                            group,key=option_map[name];v=data[period].get(group,{}).get(key)
                            if v is not None:rows.append({'Período':period,'Rubrica':name.split(' / ',1)[1],'Valor (€)':v})
                    frame=pd.DataFrame(rows,columns=['Período','Rubrica','Valor (€)'])
                    if measure=='mensal':st.info('Nesta perspetiva os valores representam o indicador do mapa, normalmente acumulado (DR/DFC) ou saldo (Balanço). Usa os comparadores analíticos para movimento mensal.')
                if not frame.empty:
                    frame=frame[frame['Valor (€)'].notna()].copy()
                if not frame.empty:
                    ref=chosen_periods[0]
                    pivot=frame.pivot_table(index='Rubrica',columns='Período',values='Valor (€)',aggfunc='first')
                    for period in chosen_periods:
                        if period not in pivot.columns:pivot[period]=float('nan')
                    pivot=pivot[chosen_periods]
                    table=pivot.copy()
                    for period in chosen_periods[1:]:
                        table[f'Δ {period} vs {ref} (€)']=pivot[period]-pivot[ref]
                        table[f'Δ {period} vs {ref} (%)']=100*(pivot[period]-pivot[ref])/pivot[ref].abs().replace(0,float('nan'))
                    a,bchart=st.columns([1.65,1])
                    with a:
                        fig=px.bar(frame,x='Rubrica',y='Valor (€)',color='Período',barmode='group',category_orders={'Período':chosen_periods},color_discrete_map={p: ['#0489a2','#f19b42','#526a98'][i] for i,p in enumerate(chosen_periods)})
                        fig.update_layout(height=455,margin=dict(t=24,b=110,l=12,r=12),legend=dict(orientation='h',y=1.12,x=0),xaxis_tickangle=-30,plot_bgcolor='white',paper_bgcolor='white',font=dict(color='#243b53'),yaxis_title='Euros',xaxis_title='')
                        st.plotly_chart(fig,width="stretch")
                    with bchart:
                        totals=frame.groupby('Período',as_index=False)['Valor (€)'].sum()
                        fig2=px.bar(totals,x='Período',y='Valor (€)',text_auto='.3s',color='Período',category_orders={'Período':chosen_periods},color_discrete_map={p: ['#0489a2','#f19b42','#526a98'][i] for i,p in enumerate(chosen_periods)})
                        fig2.update_layout(height=455,margin=dict(t=22,b=22,l=6,r=6),showlegend=False,plot_bgcolor='white',paper_bgcolor='white',title='Total das rubricas selecionadas',xaxis_title='',yaxis_title='Euros')
                        st.plotly_chart(fig2,width="stretch")
                        st.caption('O total agrega exclusivamente as rubricas selecionadas. Evita combinar contas-mãe e subcontas.')
                    st.markdown('#### Desvios financeiros (€ e %)')
                    def fmt_cmp(v,percent=False):
                        if pd.isna(v):return '—'
                        arrow='▲ ' if v>0 else '▼ ' if v<0 else '● '
                        return arrow+(f'{v:+.2f}%' if percent else euro(v))
                    fmts={col:(lambda v,col=col:fmt_cmp(v,'(%)' in col)) if col.startswith('Δ ') else (lambda v:euro(v) if pd.notna(v) else '—') for col in table.columns}
                    delta_cols=[col for col in table if col.startswith('Δ ')]
                    styler=table.reset_index().style.format(fmts)
                    if delta_cols:styler=styler.map(lambda v:'color:#b42318;font-weight:600' if pd.notna(v) and v>0 else 'color:#16803c;font-weight:600' if pd.notna(v) and v<0 else '',subset=delta_cols)
                    st.dataframe(styler,hide_index=True,width="stretch",height=min(550,85+len(table)*35))
                    if source.startswith('Pools'):
                        selected_pool=st.selectbox('Abrir detalhe contabilístico da Pool',selected,key='v5_drill')
                        detalhe_periodo=period_selectbox('Detalhe do fecho',chosen_periods,
                                                     key='v615_pool_detail_period',format_func=periodo_curto)
                        detailed=pool_details(data[detalhe_periodo],mapping,'saldo' if measure=='saldo' else 'acumulado')
                        detailed=detailed[detailed[level]==selected_pool]
                        st.dataframe(tabela_euros(detailed),hide_index=True,width="stretch")
                    output=io.BytesIO()
                    with pd.ExcelWriter(output,engine='openpyxl') as writer:
                        table.reset_index().to_excel(writer,index=False,sheet_name='Comparação 3 períodos')
                        frame.to_excel(writer,index=False,sheet_name='Dados dos gráficos')
                    st.download_button('⬇ Exportar análise comparativa (Excel)',output.getvalue(),'ulsla_comparacao_3_periodos.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',key='v5_export')
                else:
                    st.info('Não há valores disponíveis para esta combinação de filtros e períodos. Experimenta selecionar movimento acumulado ou outras rubricas.')
        st.markdown('#### Guias de análise financeira')
        groups=st.columns(4)
        guide=[('Consumos e medicamentos','Pool 1 · Medicamentos, reagentes e consumo clínico'),('Prestadores externos','Pool 1 · MCDT, terapêutica, serviços médicos e transportes'),('Recursos humanos','Pool 1 · Tipo de remuneração; Pool 2 · Grupo profissional'),('Rendimentos SNS','Pool 1 · Contrato Programa, outras entidades e reembolsos')]
        for col,(heading,txt) in zip(groups,guide):
            with col:
                st.markdown(f'**{heading}**')
                st.caption(txt)
        st.caption('Indicadores adicionais do Excel (dívida vencida por antiguidade, stock físico, atividade clínica) exigem informação complementar: não são inferidos dos quatro PDF.')
    if active_page == 'Visão executiva':
        a,bcol=st.columns([1.2,1])
        with a:
            st.subheader('Estrutura dos gastos')
            df=pd.DataFrame({'Rubrica':['FSE','Pessoal','Consumos','Depreciações','Outros gastos'],'Valor':[dr.get(x,0) for x in ['fse','pessoal','consumos','depreciacoes','outros_gastos']]})
            fig=px.bar(df.sort_values('Valor'),x='Valor',y='Rubrica',orientation='h',text_auto='.3s',color_discrete_sequence=['#087b80']);fig.update_layout(height=330,margin=dict(t=8,b=10,l=0,r=5),showlegend=False,xaxis_title='Euros',yaxis_title='');st.plotly_chart(fig,width="stretch")
        with bcol:
            st.subheader('Diagnóstico financeiro')
            if dr.get('resultado', 0) < 0:
                st.error('Resultado líquido negativo: ' + euro(dr.get('resultado'), True))
            else:
                st.success('Resultado positivo')
            if f.get('operacional',0)<0:st.warning('Fluxos operacionais negativos: '+euro(f['operacional'],True))
            if b and c['fundo_maneio']<0:st.warning('Fundo de maneio negativo: '+euro(c['fundo_maneio'],True))
            if bal:st.info('Saldo IGCP – Aumento de capital: '+euro(bal.get('igcp_aumento_capital'),True)+'; disponibilidade não necessariamente livre.')
            st.caption('Os alertas são descritivos e não representam conclusões sobre incumprimento contratual.')
        st.subheader('Comparação com N-1 apresentado no documento')
        p=[]
        for group,code in [('dr','resultado'),('dr','fse'),('dr','pessoal'),('dr','prestacoes_servicos'),('balanco','fornecedores'),('balanco','caixa')]:
            cur=get(d,group,code);prev=get(d,group+'_n1',code)
            if cur is not None and prev is not None:p.append({'Rubrica':LABELS[group][code],'N':cur,'N-1':prev,'Variação (€)':cur-prev,'Variação (%)':(cur-prev)/abs(prev)*100 if prev else None})
        st.dataframe(pd.DataFrame(p).style.format({'N':lambda x:euro(x),'N-1':lambda x:euro(x),'Variação (€)':lambda x:euro(x),'Variação (%)':lambda x:f'{x:+.1f}%' if pd.notna(x) else '—'}),hide_index=True,width="stretch")
    if active_page == 'Exploração da despesa':
        st.subheader('Gastos: detalhe contabilístico disponível')
        dd=pd.DataFrame([{'Rubrica':LABELS['balancete'][key],'Total (€)':val} for key,val in bal.items() if key in ['subcontratos_saude','servicos_medicos_empresas','honorarios_medicos','transporte_doentes','medicamentos_farmacias','medicamentos_consumo']])
        if len(dd):
            st.dataframe(dd.style.format({'Total (€)':euro}),hide_index=True,width="stretch")
            st.caption('Rubricas analíticas de níveis diferentes. Não somar estas linhas entre si nem às rubricas da DR sem definir previamente o perímetro.')
        else:st.info('Sem detalhe do balancete para este mês.')
        if d.get('contas_balancete'):
            st.subheader('Balancete integral — pesquisa por conta e descrição')
            q=st.text_input('Pesquisar conta ou rubrica',placeholder='Ex.: 621, medicamentos, honorários')
            dfall=pd.DataFrame([{'Conta':k,**v} for k,v in d['contas_balancete'].items()])
            if q:dfall=dfall[dfall['Conta'].str.contains(q,case=False,regex=False)|dfall['descricao'].str.contains(q,case=False,regex=False,na=False)]
            st.dataframe(tabela_euros(dfall),width="stretch",hide_index=True,height=390)
            st.caption('Contas hierárquicas: não somar contas-mãe às suas subcontas. Os valores de saldos são apresentados exatamente como registados no balancete.')
        st.subheader('Evolução anual dos grandes agregados de despesa')
        lines=[]
        for per,ddat in sorted(data.items()):
            for k in ['consumos','fse','pessoal']:
                if k in ddat.get('dr',{}):lines.append({'Período':per,'Rubrica':LABELS['dr'][k],'Acumulado (€)':ddat['dr'][k]})
        if lines:st.plotly_chart(px.line(pd.DataFrame(lines),x='Período',y='Acumulado (€)',color='Rubrica',markers=True),width="stretch")
    if active_page == 'Balanço e liquidez':
        st.subheader('Posição patrimonial')
        col1,col2,col3=st.columns(3)
        col1.metric('Ativo',euro(b.get('ativo'),True) if b else '—');col2.metric('Passivo',euro(b.get('passivo'),True) if b else '—');col3.metric('Liquidez corrente',f'{c["liquidez_corrente"]:.2f}' if c['liquidez_corrente'] is not None else '—')
        st.caption('Liquidez corrente = ativo corrente ÷ passivo corrente. 0,71 significa 0,71 € de ativo corrente por cada 1 € de passivo corrente.')
        rows=[('Fornecedores',b.get('fornecedores')),('Fornecedores de investimentos',b.get('fornecedores_investimento')),('Adiantamentos de clientes',b.get('adiantamentos_clientes')),('Outras contas a pagar',b.get('outras_contas_pagar')),('Outras contas a receber',b.get('outras_contas_receber')),('Clientes e utentes',b.get('clientes'))]
        st.dataframe(pd.DataFrame([{'Rubrica':r,'Saldo (€)':v} for r,v in rows if v is not None]).style.format({'Saldo (€)':euro}),hide_index=True,width="stretch")
        if bal:
            st.subheader('Detalhe da tesouraria (balancete)')
            st.dataframe(pd.DataFrame([{'Conta / indicador':LABELS['balancete'][k],'Valor (€)':bal[k]} for k in ['igcp_hla','igcp_aumento_capital','igcp_prr'] if k in bal]).style.format({'Valor (€)':euro}),hide_index=True,width="stretch")
            st.warning('Caixa excluindo apenas a conta identificada como Aumento de Capital: '+euro(c['caixa_sem_capital'])+'. Isto NÃO é uma medida certificada de disponibilidades livres: podem existir outros saldos consignados.')
        st.caption('O ativo corrente contém acréscimos de rendimentos elevados; a liquidez contabilística não deve ser confundida com caixa imediatamente utilizável.')
    if active_page == 'Fluxos de caixa':
        st.subheader('Demonstração dos fluxos de caixa')
        pairs=[('Atividades operacionais','operacional'),('Investimento','investimento'),('Financiamento','financiamento')]
        ff=pd.DataFrame([{'Fluxo':name,'Valor (€)':f[k]} for name,k in pairs if k in f])
        if len(ff):
            fig=px.bar(ff,x='Fluxo',y='Valor (€)',color='Valor (€)',color_continuous_scale='RdYlGn',text_auto='.3s');fig.update_layout(height=360,coloraxis_showscale=False);st.plotly_chart(fig,width="stretch")
        st.dataframe(pd.DataFrame([{'Indicador':LABELS['dfc'][k],'Montante (€)':v} for k,v in f.items()]).style.format({'Montante (€)':euro}),hide_index=True,width="stretch")
        st.caption('Cobertura de prejuízos é fluxo de financiamento; não constitui receita operacional.')
    if active_page == 'Evolução mensal':
        st.subheader('Série mensal: valores acumulados e movimentos do mês')
        gp=st.selectbox('Demonstração', ['dr','balanco','dfc'],format_func=lambda x:{'dr':'Resultados','balanco':'Balanço','dfc':'Fluxos de caixa'}[x]);key=st.selectbox('Indicador',list(LABELS[gp]),format_func=lambda k:LABELS[gp][k])
        hist=pd.DataFrame([{'Período':p,'Valor':x.get(gp,{}).get(key)} for p,x in sorted(data.items()) if key in x.get(gp,{})])
        if not hist.empty:
            hist['Movimento mensal']=float('nan')
            for idx in range(len(hist)):
                current=mes_civil(hist.iloc[idx]['Período'])
                if current is None:
                    continue
                if gp in ('dr','dfc') and current.month==1:
                    hist.loc[hist.index[idx],'Movimento mensal']=hist.iloc[idx]['Valor']
                elif idx>0:
                    previous=mes_civil(hist.iloc[idx-1]['Período'])
                    if previous is not None and current-previous==1 and (gp=='balanco' or current.year==previous.year):
                        hist.loc[hist.index[idx],'Movimento mensal']=hist.iloc[idx]['Valor']-hist.iloc[idx-1]['Valor']
            mode=st.radio('Visualização',['Valor à data / acumulado','Variação entre fechamentos'],horizontal=True)
            field='Valor' if mode=='Valor à data / acumulado' else 'Movimento mensal'
            st.plotly_chart(px.line(hist,x='Período',y=field,markers=True),width="stretch")
            st.dataframe(hist.style.format({'Valor':euro,'Movimento mensal':lambda x:euro(x) if pd.notna(x) else '—'}),hide_index=True,width="stretch")
            st.caption('Para DR e DFC, a diferença de acumulados consecutivos do mesmo ano aproxima o movimento mensal. Para Balanço é variação de saldos, não receita/despesa do mês. Não se estima o movimento de setembro sem agosto.')
        else:st.info('Indicador sem dados.')
    if active_page == 'Comparador de contas':
        st.subheader('Comparação de rubricas por conta SNC-AP e período')
        st.caption('As contas são identificadas pelo código contabilístico, não pela descrição, que pode variar ou surgir truncada nos PDF.')
        names=account_names(data)
        if not names:
            st.info('Ainda não existem balancetes analíticos importados com contas individualizadas.')
        else:
            options=sorted(names, key=lambda c:(len(c),c))
            defaults=[c for c in ['61','62','63','6211','6221911','612411','6255'] if c in names]
            selected=st.multiselect('Selecionar contas (podes pesquisar pelo código ou descrição)',options,default=defaults,
                format_func=lambda x:f'{x} — {names[x]}',help='Seleciona contas ao mesmo nível para evitar dupla contagem. Por exemplo, 62 já inclui 621 e 622.')
            measure=st.radio('Grandeza a comparar',list(COLUMNS),format_func=lambda x:COLUMNS[x],horizontal=True)
            st.info('Convenção contabilística: saldo/movimento líquido = débito − crédito. Gastos tendem a ser positivos e rendimentos/passivos tendem a ser negativos. A variação positiva não significa necessariamente melhoria.')
            if selected:
                avail=sorted([p for p,v in data.items() if v.get('contas_balancete')])
                if avail:
                    x,y=st.columns(2)
                    with x:pa=period_selectbox('Período de referência (A)',avail,index=0,key='comparador_a')
                    with y:pb=period_selectbox('Período de comparação (B)',avail,index=len(avail)-1,key='comparador_b')
                    result=account_compare(data,selected,pa,pb,measure,names)
                    st.subheader('Diferenças entre períodos')
                    st.dataframe(result.style.format({pa:lambda v:euro(v) if pd.notna(v) else '—',pb:lambda v:euro(v) if pd.notna(v) else '—',
                        'Variação (€)':lambda v:euro(v) if pd.notna(v) else '—','Variação (%)':lambda v:f'{v:+.2f}%' if pd.notna(v) else '—'}),hide_index=True,width="stretch")
                    historical=account_series(data,selected,measure)
                    available_rows=historical.dropna(subset=['Valor (€)']).copy()
                    if not available_rows.empty:
                        available_rows['Rubrica']=available_rows['Conta'].map(lambda c:c+' — '+names.get(c,''))
                        fig=px.line(available_rows,x='Período',y='Valor (€)',color='Rubrica',markers=True)
                        fig.update_layout(xaxis_title='',yaxis_title='Euros',legend_title='Conta',height=430)
                        st.plotly_chart(fig,width="stretch")
                    st.subheader('Histórico e disponibilidade dos dados')
                    historical['Rubrica']=historical['Conta'].map(lambda c:names.get(c,''))
                    st.dataframe(historical[['Período','Conta','Rubrica','Valor (€)','Estado']].style.format({'Valor (€)':lambda v:euro(v) if pd.notna(v) else '—'}),hide_index=True,width="stretch")
                    excel=io.BytesIO()
                    with pd.ExcelWriter(excel,engine='openpyxl') as writer:
                        result.to_excel(writer,index=False,sheet_name='Comparação')
                        historical.to_excel(writer,index=False,sheet_name='Histórico')
                    st.download_button('Exportar comparação e histórico (Excel)',excel.getvalue(),'comparacao_contas_ulsla.xlsx',
                        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            st.caption('Movimento mensal: diferença entre movimentos acumulados de dois balancetes de meses consecutivos do mesmo ano. Se faltar o mês anterior, o movimento mensal fica indisponível. Para saldos, compara-se a posição nas datas selecionadas. Não se somam contas-mãe com contas-filhas.')
    if active_page == 'Comparador por Pools':
        st.subheader('Comparação por Pools — mapa de contas ULSLA')
        st.caption('Agrupamento por código de conta e Pools 1/2. Apenas contas terminais do balancete entram nos totais; contas-mãe não são somadas novamente.')
        mapping=read_map()
        st.caption(f'Mapa carregado: {len(mapping)} contas; {len({v["pool1"] for v in mapping.values() if v["pool1"]})} Pools 1; {len({v["pool2"] for v in mapping.values() if v["pool2"]})} Pools 2.')
        level=st.radio('Agrupamento', ['Pool 1','Pool 2'],horizontal=True)
        measure=st.radio('Grandeza', list(COLUMNS),format_func=lambda x:COLUMNS[x],horizontal=True,key='pools_measure')
        avail=sorted(p for p,v in data.items() if v.get('contas_balancete'))
        if avail:
            left,right=st.columns(2)
            with left: pa=period_selectbox('Período A',avail,index=0,key='pools_a')
            with right: pb=period_selectbox('Período B',avail,index=len(avail)-1,key='pools_b')
            history=pool_series(data,mapping,measure,level)
            groups=sorted(history['Pool'].unique()) if not history.empty else []
            chosen=st.multiselect('Pools a comparar',groups,default=groups)
            if chosen:
                hist=history[history['Pool'].isin(chosen)].copy()
                pivot=hist.pivot_table(index='Pool',columns='Período',values='Valor (€)',aggfunc='first')
                for per in (pa,pb):
                    if per not in pivot.columns:pivot[per]=float('nan')
                table=pivot[[pa,pb]].copy() if pa!=pb else pivot[[pa]].copy()
                if pa!=pb:
                    table['Variação (€)']=table[pb]-table[pa]
                    table['Variação (%)']=100*table['Variação (€)']/table[pa].abs().replace(0,float('nan'))
                st.dataframe(table.reset_index().style.format({col:(lambda x:euro(x) if pd.notna(x) else '—') for col in table.columns if col!='Variação (%)'} | ({'Variação (%)':lambda x:f'{x:+.2f}%' if pd.notna(x) else '—'} if 'Variação (%)' in table.columns else {})),hide_index=True,width="stretch")
                st.plotly_chart(px.line(hist,x='Período',y='Valor (€)',color='Pool',markers=True),width="stretch")
                file=io.BytesIO()
                with pd.ExcelWriter(file,engine='openpyxl') as w:
                    table.reset_index().to_excel(w,index=False,sheet_name='Comparação Pools')
                    hist.to_excel(w,index=False,sheet_name='Histórico Pools')
                    for period in set((pa,pb)):
                        detail=pool_details(data[period],mapping,'saldo' if measure=='saldo' else 'acumulado')
                        detail.to_excel(w,index=False,sheet_name='Contas '+period)
                st.download_button('Exportar Pools e contas para Excel',file.getvalue(),'pools_ulsla.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            detail=pool_details(data[pb],mapping,'saldo' if measure=='saldo' else 'acumulado')
            unclassified=detail[detail[level]=='']
            st.caption(f'Cobertura do balancete {pb}: {len(detail)-len(unclassified)} contas terminais classificadas em {level}; {len(unclassified)} sem classificação.')
            with st.expander('Contas sem classificação / revisão do mapa'):
                st.dataframe(tabela_euros(unclassified),hide_index=True,width="stretch")
                st.download_button('Exportar contas sem Pool (CSV)',unclassified.to_csv(index=False,sep=';').encode('utf-8-sig'),'contas_sem_pool.csv','text/csv')
            st.warning('Contas sem Pool são excluídas dos totais. A soma das Pools pode não corresponder ao total das classes contabilísticas. Contas sem equivalência entre dois fechos não são automaticamente assumidas como zero.')
            st.caption('O ficheiro mapa_pools.tsv conserva as classificações originais e pode ser atualizado em futuras versões, após validação das correspondências.')
        else:st.info('É necessário importar pelo menos um balancete analítico.')
    if active_page == 'Reconciliar e validar':
        st.subheader('Controlos automáticos de coerência')
        chk=checks(d);st.dataframe(chk.style.format({'Diferença (€)':lambda x:euro(x) if pd.notna(x) else '—'}),hide_index=True,width="stretch")
        if bal and b:
            st.caption('Validação adicional: conta 1 do balancete = '+euro(bal.get('igcp_aumento_capital',0)+bal.get('igcp_prr',0)+bal.get('igcp_hla',0))+' apenas para as três contas selecionadas; não representa o total da conta 1.')
        st.warning('O controlo DR × Balanço do resultado exige a rubrica específica "Resultado líquido" do Balanço, não apenas o património líquido. Nos meses importados sem essa rubrica, essa validação fica por confirmar.')
    if active_page == 'Dados e metodologia':
        st.subheader('Mapa de indicadores, unidades e fontes')
        for group in GROUPS:
            with st.expander({'dr':'DR — Rendimentos e gastos','balanco':'Balanço — Saldos','dfc':'DFC — Fluxos','balancete':'Balancete — Analítico'}[group]):
                st.dataframe(pd.DataFrame([{'Código':k,'Rubrica':LABELS[group][k],'Valor':euro(v)} for k,v in d.get(group,{}).items() if k in LABELS[group]]),hide_index=True,width="stretch")
        st.markdown('''**Regras de interpretação:** (1) N-1 é a coluna homóloga apresentada nos documentos, não necessariamente o mês imediatamente anterior; (2) a data 01/09–30/09 impressa na DR e na DFC não basta para tratar os valores como movimentos isolados de setembro; (3) não se inferem valores históricos ausentes; (4) indicadores como PMP, dívida vencida, orçamento, atividade clínica e contratos-programa exigem fontes adicionais; (5) para análise mensal completa, inserir o mesmo conjunto de indicadores para cada fecho.''')
        export=json.dumps(data,indent=2,ensure_ascii=False).encode('utf-8');st.download_button('Exportar histórico JSON',export,'ulsla_historico.json','application/json')


    # Módulo autónomo de stocks e fluxos mensais, não confundidos com saldos contabilísticos.
    if active_page == 'Dívida e pagamentos':
        st.subheader('Dívida a fornecedores, pagamentos e créditos')
        history_xml=snapshots(ROOT)
        if not history_xml:
            st.info('Importa os três XML (Dívidas, Pagamentos e Créditos) na barra lateral para iniciar o histórico de dívida.')
        else:
            ordered=sorted([p for p,m in history_xml.items() if 'Dividas' in m.get('tipos',[])],reverse=True)
            if not ordered:
                st.warning('Não existem fechos com Dividas.xml; importa os ficheiros do período.')
                st.stop()
            st.markdown("""<style>
            div[data-testid="stVerticalBlockBorderWrapper"]:has([data-testid="stSelectbox"][aria-label="Fecho XML principal"]) {border:2px solid #167e9b!important;background:#e8f4fa!important;border-radius:16px!important}
            </style>""",unsafe_allow_html=True)
            with st.container(border=True):
                st.markdown('### 📅 Seleção dos períodos de análise')
                st.caption('Escolhe um fecho para a análise habitual, ou ativa a comparação para apresentar os dois períodos nos mapas seguintes.')
                col_period,col_mode=st.columns([2,1])
                with col_period:
                    period_debt=period_selectbox('Fecho XML principal',ordered,key='period_debt',format_func=periodo_curto)
                with col_mode:
                    compare_active=st.toggle('Comparar dois períodos',value=False,key='compare_global_enabled',disabled=len(ordered)<2)
                compare_second=None
                if compare_active:
                    alternatives=[p for p in ordered if p!=period_debt]
                    compare_second=period_selectbox('Segundo fecho XML',alternatives,key='period_debt_secondary',format_func=periodo_curto)
                    st.info(f'Comparação cronológica: {min(period_debt,compare_second)} (anterior) → {max(period_debt,compare_second)} (recente). Desvio = recente − anterior.')
                else:
                    st.caption('Análise individual ativa. Os restantes mapas mantêm o comportamento da versão 6.2.')
            # Apenas os 12 fechos disponíveis até ao período principal (inclusive).
            last_twelve=sorted([p for p in ordered if p<=period_debt])[-12:]
            if compare_second and compare_second>period_debt:
                last_twelve=sorted([p for p in ordered if p<=compare_second])[-12:]
            hist=[]
            for p in last_twelve:
                t=history_xml[p]['totais'].get('Dividas',{})
                hist.extend([{'Período':p,'Estado':l,'Valor (€)':v} for l,v in [('P1',t.get('P1',{}).get('valor',0)),('P2 líquido',t.get('P2',{}).get('valor',0)+t.get('NC',{}).get('valor',0))]])
            hist_df=pd.DataFrame(hist)
            if not hist_df.empty:
                hist_df['Valor formatado']=hist_df['Valor (€)'].map(euro)
                fig=px.bar(hist_df,x='Período',y='Valor (€)',color='Estado',barmode='group',title='Evolução mensal dos saldos em dívida — últimos 12 fechos disponíveis',color_discrete_sequence=['#eea44d','#2474a6'],custom_data=['Valor formatado'])
                fig.update_traces(hovertemplate='%{x}<br>Valor: %{customdata[0]}<extra>%{fullData.name}</extra>')
                st.plotly_chart(fig,width="stretch")
            if compare_active:
                render_comparativo(ROOT,history_xml,period_debt,compare_second,tabela_euros,euro,enriched_debt,supplier_summary,payment_days)
            else:
                meta=history_xml[period_debt]['totais']
                tot=meta.get('Dividas',{})
                p1=tot.get('P1',{}).get('valor',0);p2=tot.get('P2',{}).get('valor',0);nc=tot.get('NC',{}).get('valor',0)
                metrics=st.columns(5)
                for widget,name,val in zip(metrics,['P1 · Em conferência','P2 · Conferidas','NC · Notas de crédito','P2 líquido de NC','Pagamentos do mês'],[p1,p2,nc,p2+nc,sum(v['valor'] for k,v in meta.get('Pagamentos',{}).items() if k!='PRAZO_PAGAMENTO_OBSERVADO')]):
                    widget.metric(name,euro(val,True))
                st.caption('P1 e P2 são estados das faturas nos XML. NC abatidas ao total P2 por convenção de gestão; confirma as notas de crédito que pertencem efetivamente ao P2. Não equivale a dívida contabilística do Balanço.')
                div=load_snapshot(ROOT,period_debt,'Dividas')
                pagamentos=load_snapshot(ROOT,period_debt,'Pagamentos')
                creditos=load_snapshot(ROOT,period_debt,'Creditos')
                if not div.empty:
                    ds=enriched_debt(div,period_debt)
                    left,right=st.columns(2)
                    with left:
                        st.markdown('#### Antiguidade da dívida por vencimento')
                        age=ds[ds.TipoDocCentral.isin(['P1','P2'])].groupby(['Estado vencimento','TipoDocCentral'],observed=True).ValorDoc.sum().reset_index()
                        age['Valor formatado']=age['ValorDoc'].map(euro);fig=px.bar(age,x='Estado vencimento',y='ValorDoc',color='TipoDocCentral',barmode='stack',color_discrete_sequence=['#efad57','#217ba4'],custom_data=['Valor formatado']);fig.update_traces(hovertemplate='%{x}<br>Valor: %{customdata[0]}<extra>%{fullData.name}</extra>');st.plotly_chart(fig,width="stretch")
                        st.caption('Antiguidade bruta P1/P2; NC excluídas deste gráfico para evitar imputações sem ligação documental.')
                    with right:
                        st.markdown('#### Principais fornecedores · P2')
                        rank=supplier_summary(ds[ds.TipoDocCentral=='P2']).head(15)
                        rank=rank.copy();rank['Valor formatado']=rank['ValorDoc'].map(euro);fig=px.bar(rank.iloc[::-1],x='ValorDoc',y='NomeEntidade',orientation='h',color_discrete_sequence=['#2474a6'],labels={'ValorDoc':'Dívida (€)','NomeEntidade':'Fornecedor'},height=490,custom_data=['Valor formatado']);fig.update_traces(hovertemplate='%{y}<br>Dívida: %{customdata[0]}<extra></extra>');st.plotly_chart(fig,width="stretch")
                    st.markdown('#### Fornecedores por classificação económica')
                    st.caption('A classificação económica não é o código SNC-AP. Para agrupar estes XML pelas Pools das contas contabilísticas, é necessário um mapa de correspondência validado entre os dois classificadores.')
                    tipo=st.multiselect('Estado da dívida',['P1','P2','NC','DF','CF'],default=['P1','P2'],key='filter_tipo_debt')
                    filt=ds[ds.TipoDocCentral.isin(tipo)].copy()
                    classe=st.selectbox('Rubrica económica',['Todas']+sorted(filt.ClassificadorEconomico.dropna().unique().tolist()),key='classe_debt')
                    if classe!='Todas':filt=filt[filt.ClassificadorEconomico==classe]
                    key_search=st.text_input('Pesquisar por fornecedor, NIF ou número de documento',key='search_debt')
                    if key_search:filt=filt[filt.NomeEntidade.str.contains(key_search,case=False,regex=False,na=False)|filt.NifEntidade.str.contains(key_search,regex=False,na=False)|filt.NumDoc.str.contains(key_search,case=False,regex=False,na=False)]
                    grouped=filt.groupby(['ClassificadorEconomico','NomeEntidade','NifEntidade'],as_index=False).ValorDoc.sum().sort_values('ValorDoc',ascending=False)
                    st.dataframe(tabela_euros(grouped.rename(columns={'ClassificadorEconomico':'Classificação','NomeEntidade':'Fornecedor','NifEntidade':'NIF','ValorDoc':'Valor (€)'})),hide_index=True,width="stretch",height=400)
                    st.download_button('Exportar dívida filtrada (CSV)',filt.to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig'),file_name=f'dividas_{period_debt}.csv',mime='text/csv')
                if not pagamentos.empty:
                    st.markdown('#### Prazo observado dos documentos pagos')
                    days=payment_days(pagamentos)
                    st.metric('Prazo médio observado (emissão → pagamento)',f'{days:.1f} dias' if days is not None else '—')
                    st.caption('É um indicador operacional ponderado pelo valor, não o PMP oficial; o cálculo regulamentar carece de validação da base, critérios e datas.')
                if not creditos.empty:
                    st.markdown('#### Créditos a receber')
                    total=creditos.ValorDoc.sum()
                    st.metric('Créditos líquidos no XML',euro(total,True))
                    st.dataframe(tabela_euros(supplier_summary(creditos).head(15).rename(columns={'NomeEntidade':'Cliente','NifEntidade':'NIF','ValorDoc':'Crédito (€)'})),hide_index=True,width="stretch")

        if history_xml and not compare_active:
            st.divider()
            render_comparacao_divida(ROOT, history_xml, period_debt)

    if active_page == 'Indicadores financeiros':
        st.subheader('Indicadores económico-financeiros')
        st.caption('Indicadores calculados dos mapas SNC-AP. Valores nulos ou sem base são apresentados como indisponíveis.')
        receita=c['rendimentos'];ativo=b.get('ativo');pat=b.get('patrimonio');passivo=b.get('passivo')
        atcorr=b.get('ativo_corrente');pascorr=b.get('passivo_corrente');cash=b.get('caixa');invent=b.get('inventarios')
        result=dr.get('resultado');oper=dr.get('operacional');ebitda=dr.get('ebitda')
        vals=[
          ('Liquidez corrente',atcorr/pascorr if pascorr else None,'vezes','Ativo corrente / Passivo corrente'),
          ('Liquidez reduzida',(atcorr-invent)/pascorr if pascorr and invent is not None else None,'vezes','(Ativo corrente - inventários) / Passivo corrente'),
          ('Liquidez imediata',cash/pascorr if pascorr and cash is not None else None,'vezes','Caixa e depósitos / Passivo corrente'),
          ('Autonomia financeira',100*pat/ativo if ativo else None,'%','Património líquido / Ativo'),
          ('Endividamento',100*passivo/ativo if ativo else None,'%','Passivo / Ativo'),
          ('Solvabilidade',100*pat/passivo if passivo else None,'%','Património líquido / Passivo'),
          ('Margem operacional',100*oper/receita if receita and oper is not None else None,'%','Resultado operacional / Rendimentos'),
          ('Margem EBITDA',100*ebitda/receita if receita and ebitda is not None else None,'%','EBITDA / Rendimentos'),
          ('Margem líquida',100*result/receita if receita and result is not None else None,'%','Resultado líquido / Rendimentos'),
          ('ROA simplificado',100*result/ativo if ativo and result is not None else None,'%','Resultado líquido / Ativo no fecho (não usa ativo médio)'),
          ('ROE simplificado',100*result/pat if pat and result is not None and pat>0 else None,'%','Resultado líquido / Património líquido no fecho (não usa capital médio)'),
          ('Fundo de maneio',c['fundo_maneio'] if b else None,'€','Ativo corrente menos passivo corrente')]
        rows=[]
        for name,v,unit,formula in vals:
            display=('—' if v is None else euro(v) if unit=='€' else f'{v:,.2f}'.replace(',','X').replace('.',',').replace('X','.')+(' %' if unit=='%' else ''))
            rows.append({'Indicador':name,'Valor':display,'Unidade':unit,'Fórmula / ressalva':formula})
        st.dataframe(pd.DataFrame(rows),hide_index=True,width="stretch",height=475)
        st.markdown('#### Prazos médios — condições de cálculo')
        all_xml=snapshots(ROOT)
        if selection in all_xml:
            pm=load_snapshot(ROOT,selection,'Pagamentos')
            if not pm.empty:
                p=payment_days(pm)
                st.metric('Prazo médio observado dos pagamentos',f'{p:.1f} dias' if p is not None else '—')
        st.info('PMP e PMR oficiais exigem método regulamentar e validação dos universos elegíveis. Os XML de pagamentos permitem estimar os dias efetivos até ao pagamento, mas não comprovam isoladamente o PMP oficial. Os créditos em aberto permitem antiguidade dos recebíveis; sem ficheiro de recebimentos não é possível determinar o prazo real de cobrança.')

    if active_page == 'PMP — Apuramento contabilístico':
        from pmp_extratos import render as render_pmp_extratos
        render_pmp_extratos(data)

    # Separador acrescentado, sem alterar os índices dos separadores anteriores.
    if active_page == 'Análise económico-financeira comparativa':
        from analise_financeira_comparativa import render as render_analise_v613
        render_analise_v613(data,selection,euro)

    if active_page == 'XML SNC-AP · Orçamento e Património':
        render_s3cp_xml(ROOT,selection)

_render_area_ativa()
