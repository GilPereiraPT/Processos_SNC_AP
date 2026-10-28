"""Inventário transversal, apenas de leitura. Não importa módulos de aplicação."""
from __future__ import annotations
from pathlib import Path
from datetime import date
import gzip
import json
import re
import sqlite3
import pandas as pd

XML_KINDS = ('BA','DR','BLC','DFC','DOREC','DODES','AFT','AI','DAPL')
DEBT_KINDS = ('Dividas','Pagamentos','Creditos')
COLUMNS = ['Período','Área','Dado','Estado','Necessidade','Origem','Detalhe','Como resolver']
ATTENTION = {'Em falta','Ilegível','Por confirmar'}


def norm(value):
    match = re.fullmatch(r'(20\d{2})-(\d{1,2})', str(value))
    if match and 1 <= int(match[2]) <= 14:
        return f'{match[1]}-{min(int(match[2]),12):02d}'
    return None


def read_json(path):
    opener = gzip.open if path.name.endswith('.gz') else open
    with opener(path, 'rt', encoding='utf-8-sig') as handle:
        return json.load(handle)


def readonly(path):
    # mode=ro: nunca cria uma base vazia nem migra o esquema.
    con = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=5)
    con.execute('PRAGMA query_only=ON')
    return con


def audit(root, start='2024-01', end=None, history=None):
    root = Path(root)
    end = end or date.today().strftime('%Y-%m')
    periods = [str(p) for p in pd.period_range(start, end, freq='M')]
    rows = []
    def add(period, area, item, state, need, source='', detail='', action=''):
        rows.append(dict(zip(COLUMNS, [period,area,item,state,need,str(source),detail,action])))
    # Importações históricas: a existência de valores não prova origem PDF.
    historical = {}
    for name in ('seed_2026_09.json','dados_mensais.json'):
        path = root/name
        if not path.exists():
            if name.startswith('seed_'):
                add('Geral','Dashboard',name,'Opcional — ausente','Opcional',name,'Histórico inicial opcional; uma instalação nova pode começar por importar dados.','Repor apenas se existir um histórico inicial a preservar.')
            continue
        try:
            data = read_json(path)
            if not isinstance(data,dict): raise ValueError('Objeto JSON esperado')
            if 'periodo' in data: data = {data['periodo']:data}
            for per, obj in sorted(data.items()):
                key = norm(per)
                if key and isinstance(obj,dict): historical.setdefault(key,{}).update(obj)
        except Exception as exc:
            add('Geral','Dashboard',name,'Ilegível','Obrigatório',name,str(exc),'Repor uma cópia válida do histórico.')
    for per, obj in (history or {}).items():
        if norm(per) and isinstance(obj,dict): historical.setdefault(norm(per),{}).update(obj)

    xml, broken = {}, {}
    for path in sorted((root/'dados_s3cp_xml').glob('*/*.json.gz')):
        per, kind = norm(path.parent.name), path.name.split('.')[0]
        if not per or kind not in XML_KINDS: continue
        try:
            obj = read_json(path)
            if not isinstance(obj,dict) or obj.get('tipo') != kind or norm(obj.get('periodo')) != per:
                raise ValueError('Tipo ou período incoerente com a pasta/ficheiro')
            if str(obj.get('entidade')) != '510445152':
                raise ValueError('Entidade diferente da ULSLA (510445152)')
            if not all(isinstance(obj.get(k),list) for k in ('resumo','registos')):
                raise ValueError('Estrutura de resumo/registos inválida')
            # Mesma preferência do catálogo: pasta canónica antes de 13/14 legados.
            rank = (100 if path.parent.name == per else 0) + int(str(obj.get('periodo_original',path.parent.name))[-2:])
            if (per,kind) not in xml or rank > xml[per,kind][0]: xml[per,kind] = (rank,path)
        except Exception as exc: broken[per,kind] = (path,str(exc))
    for per in periods:
        for kind in XML_KINDS:
            key = (per,kind)
            group = {'DR':'dr','BLC':'balanco','DFC':'dfc'}.get(kind)
            stored = historical.get(per,{}).get(group) if group else None
            if key in xml:
                state, source, detail = 'Recebido — XML',xml[key][1].relative_to(root),'Estrutura importada legível; não substitui validação contabilística.'
            elif isinstance(stored,dict) and stored:
                state, source, detail = 'Recebido — histórico','Histórico financeiro','Valores guardados disponíveis; origem PDF/Excel não presumida. XML pode continuar necessário ao SISEE.'
            elif key in broken:
                state, source, detail = 'Ilegível',broken[key][0].relative_to(root),broken[key][1]
            else: state, source, detail = 'Em falta',f'dados_s3cp_xml/{per}/{kind}.json.gz',''
            add(per,'XML SNC-AP',kind,state,'Obrigatório',source,detail,'Importação de Dados / Dashboard → Importação XML.')
            if state == 'Recebido — histórico':
                add(per,'Reporte SISEE',kind+' XML para reporte','Em falta','Se usar o módulo',f'dados_s3cp_xml/{per}/{kind}.json.gz','O reporte lê XML; o histórico não é equivalente.','Importar o XML do mapa correspondente.')
        ledger = historical.get(per,{}).get('contas_balancete')
        has_ledger = isinstance(ledger,dict) and bool(ledger)
        add(per,'Comparadores e Pools','Contas detalhadas do balancete',
            'Recebido' if has_ledger else 'Em falta','Se usar o módulo','Histórico → contas_balancete',
            'Os comparadores e Pools usam o detalhe de contas do histórico; o resumo do balancete não é equivalente.',
            'Dashboard → importação do balancete PDF com detalhe de contas.')
        for kind in DEBT_KINDS:
            path = root/'dados_xml'/per/(kind+'.json.gz')
            state, detail = 'Em falta',''
            if path.exists():
                try:
                    obj = read_json(path)
                    if not isinstance(obj,list) or not obj: raise ValueError('Sem lista de documentos utilizável')
                    if not all(isinstance(r,dict) and 'ValorDoc' in r for r in obj):raise ValueError('Documentos sem ValorDoc')
                    state, detail = 'Recebido — XML',f'{len(obj)} documentos; validado o ficheiro, sem depender só do resumo.json.'
                except Exception as exc: state, detail = 'Ilegível',str(exc)
            add(per,'Dívida e pagamentos',kind,state,'Obrigatório',path.relative_to(root),detail,'Dashboard → Dívida e pagamentos / importador de dívida histórica.')
    # Assinalar também XML ilegíveis que estejam a ser encobertos por alternativa válida.
    for (per,kind),(path,error) in broken.items():
        if per in periods and ((per,kind) in xml or historical.get(per,{}).get({'DR':'dr','BLC':'balanco','DFC':'dfc'}.get(kind,''))):
            add(per,'Integridade',kind+' — cópia ilegível','Ilegível','Obrigatório',path.relative_to(root),error,'Rever a cópia indicada; existe outra fonte disponível.')

    # Extratos contabilísticos 3–5: controlar meses e classe 4 pelo conteúdo, não pelo nome anual.
    movements, errors = {}, {}
    for path in sorted((root/'dados_pmp_extratos').glob('extrato_*.csv.gz')):
        try:
            frame = pd.read_csv(path,sep=';',compression='gzip',dtype=str,keep_default_na=False)
            required = {'Conta','Data contabilização','Tipo','Debito','Credito','Valor líquido (€)'}
            if not required.issubset(frame):raise ValueError('Colunas em falta: '+', '.join(sorted(required-set(frame))))
            dates = pd.to_datetime(frame['Data contabilização'],errors='coerce')
            if dates.isna().any():raise ValueError('Datas de contabilização inválidas')
            frame['_mes'] = dates.dt.strftime('%Y-%m')
            frame['_conta'] = frame['Conta'].str.replace('.','',regex=False).str.strip()
            for per, part in frame.groupby('_mes'):
                movements.setdefault(per,[]).append((path,part))
        except Exception as exc:
            match = re.search(r'extrato_(\d{4})',path.name)
            if match: errors[match[1]] = (path,str(exc))
            add('Geral','Integridade','Extrato contabilístico','Ilegível','Obrigatório',path.relative_to(root),str(exc),'Reimportar o extrato original no módulo PMP.')
    for per in periods:
        parts = movements.get(per,[])
        detail = ''
        if parts:
            frame = pd.concat([part for _,part in parts],ignore_index=True)
            source = ', '.join(str(path.relative_to(root)) for path,_ in parts)
            count4 = int(frame['_conta'].str.startswith('4').sum())
            state = 'Recebido — movimentos' if count4 else 'Por confirmar'
            detail = f'{count4} movimentos da classe 4; {len(frame)} movimentos no mês. A presença não comprova cobertura integral do extrato.'
            if not count4: detail += ' Confirmar se não houve movimentos ou importar o extrato completo.'
        else:
            source = f'dados_pmp_extratos/extrato_{per[:4]}.csv.gz'
            state = 'Ilegível' if per[:4] in errors else 'Em falta'
            detail = 'Não foram localizados movimentos deste mês. Pode tratar-se de um mês sem movimentos; confirmar na origem.'
        add(per,'Extratos contabilísticos','Extrato da classe 4',state,'Obrigatório',source,detail,'Dashboard → PMP — Apuramento contabilístico → importar extrato CSV das contas 3–5.')
        for prefix in ('31','372','43','443','447','453','454'):
            count = sum(int(part['_conta'].str.startswith(prefix).sum()) for _,part in parts)
            state2 = 'Recebido — movimentos' if count else ('Por confirmar' if parts else state)
            add(per,'PMP','Movimentos da conta '+prefix,state2,'Se usar o módulo',source,
                f'{count} movimentos. Ausência de movimentos não prova ausência do ficheiro nem valor zero.',
                'Importar extrato 3–5 ou confirmar que não existiram movimentos nesta conta/mês.')

    # Analítica: comparar registo de importação com movimentos; não criar/migrar SQLite.
    db = root/'dados_analitica'/'analitica.sqlite3'
    imported, actual, ba = {}, {}, set()
    db_error = None
    if db.exists():
        try:
            con = readonly(db)
            try:
                imported = {f'{int(y)}-{int(m):02d}':int(n or 0) for y,m,n in con.execute('SELECT ano,mes,linhas FROM importacoes')}
                actual = {f'{int(y)}-{int(m):02d}':int(n) for y,m,n in con.execute('SELECT ano,mes,COUNT(*) FROM movimentos GROUP BY ano,mes')}
                ba = {f'{int(y)}-{int(m):02d}' for y,m in con.execute('SELECT ano,mes FROM ba_esperado')}
            finally: con.close()
        except Exception as exc: db_error = str(exc)
    for per in periods:
        if db_error: state,detail = 'Ilegível',db_error
        elif per in imported and actual.get(per,0) == imported[per]:
            state,detail = 'Recebido — importação',f'{actual.get(per,0)} linhas; registo e movimentos coincidem.'
        elif per in imported or per in actual:
            state,detail = 'Por confirmar',f'Registo: {imported.get(per,"ausente")}; movimentos: {actual.get(per,0)}. Rever a importação.'
        else: state,detail = 'Em falta','Sem registo de importação nem movimentos do mês.'
        add(per,'Contabilidade analítica','Extrato analítico',state,'Obrigatório',db.relative_to(root),detail,'Contabilidade Analítica → Importar extrato.')
        add(per,'Contabilidade analítica','Referência para reconciliação BA',
            'Recebido' if per in ba or (per,'BA') in xml else ('Ilegível' if db_error else 'Em falta'),
            'Se usar o módulo','ba_esperado / BA XML',
            'A disponibilidade da referência não comprova que os valores reconciliam.',
            'Importar BA XML e executar Contabilidade Analítica → Reconciliação.')

    # Dependências estáticas e alternativas efetivamente lidas pelos scripts.
    files = [
        ('Identidade','Logótipo ULSLA',['logotipo ULSLA.png','logotipo_ULSLA.png','logo_ulsla.png','ulsla_logo.png','Logotipo ULSLA.png'],'Obrigatório',None),
        ('Contabilidade analítica','Mapa de centros M',['ULSLA_Centros_Custo_Tipo_M_Grupos*.csv'],'Obrigatório',{'Tipo','Centro de Custos','Grande Grupo','Subgrupo original'}),
        ('Contabilidade analítica','Agrupamento de centros',['ULSLA_CC_Grupos_Report.csv'],'Se usar o módulo',{'Centro de Custos','Grupo report','Subgrupo report'}),
        ('Contabilidade analítica','Cadastro de entidades',['LIST_ENTIDADES_15102026.CSV'],'Se usar o módulo',None),
        ('Contabilidade analítica','Plano de contas',['LIST_PCONTAS_15102026.CSV','plano_contas_dashboard.csv'],'Se usar o módulo',{'Conta','Designação'}),
        ('Pools','Mapa de contas e Pools',['mapa_pools.tsv'],'Se usar o módulo',{'Conta','Designação','Tipo','Pool 1','Pool 2'}),
        ('Reporte SISEE','Correspondência de rubricas RCE',['sisee_mapeamento_rce.tsv'],'Se usar o módulo',{'Conta','Conta Acumulação'}),
        ('Produção / CP','Produção valorizada (março 2026)',['producao_cp_2026_03.csv'],'Se usar o módulo',{'ano','mes','cc_producao','quantidade','preco_eur','icm'}),
        ('Produção / CP','Correspondência CC / produção',['correspondencia_cc_producao.csv'],'Se usar o módulo',{'cc_lancamento','cc_producao'}),
    ]
    for area,label,patterns,need,columns in files:
        candidates = [p for pattern in patterns for p in sorted(root.glob(pattern)) if p.is_file()]
        path = candidates[0] if candidates else None
        state, detail = ('Recebido','Presença verificada; confirmar atualização na origem.') if path else ('Em falta','')
        if path:
            try:
                if path.stat().st_size == 0: raise ValueError('Ficheiro vazio')
                if columns:
                    sep = '\t' if path.suffix == '.tsv' else ';'
                    frame = pd.read_csv(path,sep=sep,encoding='cp1252' if path.name.startswith('LIST_') else 'utf-8-sig',skiprows=3 if path.name.startswith('LIST_') else 0,dtype=str)
                    frame.columns=frame.columns.str.strip()
                    if not columns.issubset(frame):raise ValueError('Colunas em falta: '+', '.join(sorted(columns-set(frame))))
                    if frame.empty:raise ValueError('Tabela sem linhas')
            except Exception as exc: state,detail = 'Ilegível',str(exc)
        add('Geral',area,label,state,need,path.relative_to(root) if path else ' ou '.join(patterns),detail,'Repor/atualizar o ficheiro de apoio indicado na pasta da aplicação.')

    for year in sorted({p[:4] for p in periods}):
        for prefix,label,need in [('base','Contratualização anual ACSS','Se usar o módulo'),('calendarizacao','Calendarização ACSS','Opcional'),('reparticao_pools','Repartição manual por Pools','Opcional')]:
            path = root/'contratualizacao'/f'{prefix}_{year}.json'
            state,detail = 'Em falta',''
            if path.exists():
                try:
                    obj=read_json(path)
                    if not isinstance(obj,dict) or not obj:raise ValueError('Sem objeto de configuração utilizável')
                    state,detail='Recebido','JSON legível; confirmar valores e ano.'
                except Exception as exc:state,detail='Ilegível',str(exc)
            if not path.exists() and need=='Opcional':state,detail='Opcional — ausente','O módulo utiliza a regra automática por defeito.'
            add(year,'Contratualização',label,state,need,path.relative_to(root),detail,'Repor a base contratual ou ajustar a configuração no módulo ACSS.')

    for filename,label in [('cgo_dados_complementares.json','Dados complementares CGO'),('ute_complementares.json','Dados complementares UTE')]:
        path = root/'dados_sisee'/filename
        stored,error={},None
        if path.exists():
            try:
                obj=read_json(path)
                stored=obj.get('periodos',{}) if filename.startswith('cgo') else obj
                if not isinstance(stored,dict):raise ValueError('Estrutura de períodos inválida')
            except Exception as exc:error=str(exc)
        for per in periods:
            if int(per[-2:]) % 3:continue
            quarter=f'{per[:4]}-T{int(per[-2:])//3}'
            value=stored.get(quarter)
            required = ({'doentes','rh_inicio','entradas','saidas','rh_medio','orgaos','direcao','viaturas','valorizacoes','novos_trabalhadores'} | {f'linha_{r}' for r in (29,40,51,52,54,55,56,57,58,59,60,72,73,95)}) if filename.startswith('cgo') else {'juros_igcp','juros_outros','dispensa','ganhos_dispensa','ganhos_entregues','autorizacao'}
            complete = isinstance(value,dict) and required.issubset(value)
            state='Ilegível' if error else ('Recebido — guardado' if complete else 'Por confirmar')
            add(per,'Reporte SISEE',label,state,'Se usar o módulo',path.relative_to(root),error or 'Exige valores próprios do trimestre; valores iniciais ou do trimestre anterior não confirmam este período.','Produção de Mapas → CGO / UTE → confirmar e guardar dados complementares.')
    add('Geral','Reporte SISEE','Modelos oficiais Excel / cálculo XLS','Por carregar na utilização','Se usar o módulo','Carregamento no formulário','Os ficheiros carregados temporariamente não são conservados. A ausência na pasta não é uma falta histórica.','Carregar o modelo oficial no momento de produzir cada mapa; XLS do CGO é alternativo ao BA XML.')
    add('Geral','PMP','Apuramentos manuais antigos (dados_pmp.json)','Opcional','Opcional','dados_pmp.json','Histórico alternativo; não substitui os extratos nem o método automático atual.','Usar apenas se necessário ao histórico manual.')
    return pd.DataFrame(rows, columns=COLUMNS)


def signature(root):
    root=Path(root)
    patterns=['*.json','*.csv','*.CSV','*.tsv','*ULSLA*.png','*ulsla*.png',
              'dados_s3cp_xml/*/*.json.gz','dados_xml/*/*.json.gz',
              'dados_pmp_extratos/extrato_*.csv.gz','dados_analitica/analitica.sqlite3*',
              'contratualizacao/*.json','dados_sisee/*.json']
    return tuple(sorted({(str(p.relative_to(root)),p.stat().st_mtime_ns,p.stat().st_size)
                         for pattern in patterns for p in root.glob(pattern) if p.is_file()}))


def render(root, history=None, compact=False, key='dados'):
    import streamlit as st
    from ulsla_branding import period_selectbox
    @st.cache_data(show_spinner=False,max_entries=4)
    def cached(base, sig, end):return audit(base,end=end)
    st.caption('Inventário desde janeiro de 2024: XML, dívida, extratos, analítica e ficheiros de apoio. Verificação apenas de leitura.')
    # Histórico é relido do disco; não usar dados derivados do Dashboard como prova de origem.
    end=st.text_input('Verificar até (AAAA-MM)',value=date.today().strftime('%Y-%m'),key=key+'_end')
    if not re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])',end) or end<'2024-01':
        st.warning('Indique um mês válido a partir de 2024-01.');return
    if st.button('Atualizar verificação',key=key+'_refresh'):cached.clear()
    with st.spinner('A verificar as fontes de dados...'): frame=cached(str(Path(root).resolve()),signature(root),end)
    years=sorted({p[:4] for p in frame['Período'] if re.match(r'^20\d{2}',p)},reverse=True)
    year=period_selectbox('Exercício a verificar',['Todos']+years,key=key+'_year')
    view=frame if year=='Todos' else frame[frame['Período'].str.startswith(year) | frame['Período'].eq('Geral')]
    months=sorted([p for p in view['Período'].unique() if re.fullmatch(r'20\d{2}-\d{2}',p)],reverse=True)
    month=period_selectbox('Mês a verificar',['Todos']+months,key=key+'_month')
    if month!='Todos':view=view[view['Período'].isin([month,month[:4],'Geral'])]
    area=st.selectbox('Área a verificar',['Todas']+sorted(frame['Área'].unique()),key=key+'_area')
    if area!='Todas':view=view[view['Área'].eq(area)]
    pending=view[view.Estado.isin(ATTENTION) & view.Necessidade.ne('Opcional')]
    st.markdown(f'**{len(pending)} pontos a resolver ou confirmar** · {int(pending.Estado.eq("Em falta").sum())} em falta · {int(pending.Estado.eq("Ilegível").sum())} ilegíveis · {int(pending.Estado.eq("Por confirmar").sum())} por confirmar')
    if st.checkbox('Mostrar apenas faltas, erros e confirmações pendentes',value=True,key=key+'_only'):view=pending
    st.dataframe(view[['Período','Área','Dado','Estado']] if compact else view,hide_index=True,use_container_width=True)
    st.download_button('Descarregar verificação apresentada (CSV)',view.to_csv(index=False,sep=';').encode('utf-8-sig'),'ULSLA_verificacao_dados.csv','text/csv',key=key+'_csv')
    if not compact:
        st.download_button('Descarregar inventário completo (CSV)',frame.to_csv(index=False,sep=';').encode('utf-8-sig'),'ULSLA_inventario_completo.csv','text/csv',key=key+'_all')
    st.caption('O mês corrente pode ainda não estar fechado: ajuste «Verificar até». Movimentos encontrados não comprovam um extrato completo; meses sem movimentos exigem confirmação. Períodos 12/13/14 convergem para dezembro nos XML SNC-AP.')
