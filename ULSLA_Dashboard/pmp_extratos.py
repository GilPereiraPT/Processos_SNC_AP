"""Importação de extratos de contas 3-5 e apuramento de aquisições do PMP.
Todos os tipos de documento exceto OD; sinais contabilísticos débito menos crédito.
O extrato 3-5 não contém 62; dívida e 62 vêm de BA XML, NIF 999999990.
"""
from pathlib import Path
import io, json, re, hashlib, sqlite3, shutil
from datetime import datetime
import pandas as pd
import streamlit as st
from ulsla_branding import period_selectbox

ROOT=Path(__file__).resolve().parent/'dados_pmp_extratos'
MON={'JAN':1,'FEV':2,'MAR':3,'ABR':4,'MAI':5,'JUN':6,'JUL':7,'AGO':8,'SET':9,'OUT':10,'NOV':11,'DEZ':12}
REQUIRED={'Conta','Data Contab.','Tipo','Debito','Credito'}

def currency(s):
    return pd.to_numeric(s.fillna('0').astype(str).str.replace('€','',regex=False).str.replace(' ','',regex=False).str.replace('.','',regex=False).str.replace(',','.',regex=False),errors='coerce').fillna(0.0)

def dates(s):
    x=s.astype(str).str.upper().str.strip().str.extract(r'^(\d{2})-([A-ZÇ]{3})-(\d{4})$')
    months=x[1].map(MON)
    return pd.to_datetime({'year':pd.to_numeric(x[2],errors='coerce'),'month':months,'day':pd.to_numeric(x[0],errors='coerce')},errors='coerce')

def load_csv(data):
    raw=data if isinstance(data,bytes) else data.read()
    txt=None
    for enc in ('utf-8-sig','cp1252','latin-1'):
        try:txt=raw.decode(enc);break
        except UnicodeDecodeError:continue
    lines=txt.splitlines()
    ix=next((i for i,line in enumerate(lines[:35]) if line.lstrip('\ufeff').startswith('Conta;Data Contab.;')),None)
    if ix is None:raise ValueError('Cabeçalho Conta;Data Contab. não encontrado.')
    d=pd.read_csv(io.StringIO('\n'.join(lines[ix:])),sep=';',dtype=str,keep_default_na=False,low_memory=False)
    if not REQUIRED.issubset(d.columns):raise ValueError('Colunas obrigatórias em falta: '+', '.join(sorted(REQUIRED-set(d.columns))))
    d=d[d['Tipo'].str.strip().ne('')].copy()  # remove saldos iniciais
    d['Data contabilização']=dates(d['Data Contab.'])
    if d['Data contabilização'].isna().any():raise ValueError(f"Datas de contabilização não reconhecidas: {d['Data contabilização'].isna().sum()}")
    d['Conta']=d['Conta'].astype(str).str.strip()
    d['Tipo']=d['Tipo'].astype(str).str.strip().str.upper()
    d['Débito (€)']=currency(d['Debito']);d['Crédito (€)']=currency(d['Credito'])
    d['Valor líquido (€)']=d['Débito (€)']-d['Crédito (€)']
    # O extrato possui movimentos analíticos; cada linha é contada uma única vez.
    # Abrange todas as subcontas 31, 43 e 45, não apenas 450/453.
    c=d['Conta']
    d['Rubrica']='Fora do perímetro do PMP'
    d.loc[c.str.startswith('31'),'Rubrica']='31 — Compras'
    d.loc[c.str.startswith('43'),'Rubrica']='43 — Ativos fixos tangíveis'
    d.loc[c.str.startswith('45'),'Rubrica']='45 — Investimentos em curso'
    relevant=d['Rubrica']!='Fora do perímetro do PMP'
    d['Estado']='Excluído — fora de 31/43/45'
    d.loc[relevant & d['Tipo'].eq('OD'),'Estado']='Excluído — OD'
    d.loc[relevant & ~d['Tipo'].eq('OD'),'Estado']='Incluído — documento não OD'
    d['Trimestre']=d['Data contabilização'].dt.strftime('%Y')+'-T'+(((d['Data contabilização'].dt.month-1)//3)+1).astype(str)
    d['Ano']=d['Data contabilização'].dt.year
    return d

DB=ROOT/'importacoes.sqlite3'
BACKUP=ROOT/'copias_seguranca'

def db_connect():
    ROOT.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS importacoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        instante TEXT NOT NULL, ano INTEGER NOT NULL, nome_ficheiro TEXT,
        sha256 TEXT, acao TEXT NOT NULL, movimentos INTEGER NOT NULL,
        ficheiro_anterior TEXT, observacoes TEXT)""")
    con.commit()
    return con

def signature(d):
    cols=[c for c in ['Conta','Data Contab.','Nº Lancamento','Tipo','Nº Documento','Debito','Credito'] if c in d]
    if not cols:return pd.Series(dtype=str)
    return pd.util.hash_pandas_object(d[cols].fillna('').astype(str),index=False).astype(str)

def preview_import(incoming):
    result=[]
    for yr,part in incoming.groupby('Ano'):
        file=ROOT/f'extrato_{yr}.csv.gz'
        if file.exists():
            old=pd.read_csv(file,sep=';',compression='gzip',dtype=str,keep_default_na=False,low_memory=False)
            incoming_sig=signature(part)
            old_sig=set(signature(old))
            duplicates=int(incoming_sig.isin(old_sig).sum())
            count=len(old)
        else:duplicates=0;count=0
        result.append({'Ano':int(yr),'Existentes':count,'Novo ficheiro':len(part),'Movimentos coincidentes':duplicates,'Movimentos não coincidentes':len(part)-duplicates,'Sobreposição': bool(count)})
    return pd.DataFrame(result)

def commit_import(d,filename,action):
    if action not in ('substituir','adicionar'):raise ValueError('Ação não autorizada.')
    BACKUP.mkdir(parents=True,exist_ok=True)
    rows=[]
    with db_connect() as con:
        for yr,part in d.groupby('Ano'):
            path=ROOT/f'extrato_{int(yr)}.csv.gz'
            old=pd.read_csv(path,sep=';',compression='gzip',dtype=str,keep_default_na=False,low_memory=False) if path.exists() else None
            backupname=None
            if old is not None:
                backupname=f'{path.stem}_{datetime.now().strftime("%Y%m%d_%H%M%S_%f")}.csv.gz'
                shutil.copy2(path,BACKUP/backupname)
            if old is not None and action=='adicionar':
                oldhash=set(signature(old));part=part.loc[~signature(part).isin(oldhash)].copy()
                if len(part):
                    # Preservar todas as linhas existentes, mesmo perante diferenças nas colunas
                    updated=pd.concat([old,part.astype(str)],ignore_index=True)
                else:updated=old
            else:updated=part
            temp=path.with_name(path.name+'.tmp')
            updated.to_csv(temp,index=False,compression='gzip',encoding='utf-8-sig',sep=';')
            temp.replace(path)
            con.execute('INSERT INTO importacoes (instante, ano, nome_ficheiro, sha256, acao, movimentos, ficheiro_anterior, observacoes) VALUES (?,?,?,?,?,?,?,?)',
                        (datetime.now().isoformat(timespec='seconds'),int(yr),filename,hashlib.sha256(part.to_csv(index=False).encode('utf8')).hexdigest(),action,len(part),backupname,'Importação confirmada pelo utilizador'))
            rows.append((int(yr),len(part)))
        con.commit()
    return rows

def pmp_cards(data_balancetes):
    try:
        df=all_stored()
        calc_df=reconcile_pmp(df,data_balancetes) if not df.empty else pd.DataFrame()
        if calc_df.empty or 'Período' not in calc_df:
            return pd.DataFrame(columns=['Período','PMP (dias)','Estado'])
        return calc_df.sort_values('Período').tail(4)
    except Exception:
        return pd.DataFrame(columns=['Período','PMP (dias)','Estado'])

def save(d):
    ROOT.mkdir(exist_ok=True)
    years=sorted(d.Ano.unique())
    for yr in years:
        dest=ROOT/f'extrato_{yr}.csv.gz'
        d[d.Ano==yr].to_csv(dest,index=False,compression='gzip',encoding='utf-8-sig',sep=';')
    return years

def all_stored():
    files=sorted(ROOT.glob('extrato_*.csv.gz')) if ROOT.exists() else []
    parts=[]
    for path in files:
        try:
            x=pd.read_csv(path,sep=';',compression='gzip',dtype={'Conta':str,'Nº Documento':str,'Nº Lancamento':str},low_memory=False)
            x['Data contabilização']=pd.to_datetime(x['Data contabilização'])
            parts.append(x)
        except Exception as e:st.warning(f'Não foi possível ler {path.name}: {e}')
    return pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()

def summary(d):
    included=d[d['Estado']=='Incluído — documento não OD']
    by=included.groupby(['Trimestre','Rubrica','Tipo'],as_index=False).agg(**{'Valor líquido (€)':('Valor líquido (€)','sum'),'Movimentos':('Tipo','size')})
    totals=included.groupby('Trimestre',as_index=False)['Valor líquido (€)'].sum().rename(columns={'Valor líquido (€)':'Aquisições líquidas 31/43/45 (€)'})
    return by,totals

def reconcile_pmp(d, data_balancetes):
    """Método único: extratos 31/43/45 sem OD, conta 62 e dívida de balancetes.

    Usa apenas balancetes de março, junho, setembro e dezembro e trimestres
    completos. Nunca recupera valores pelo método indicativo antigo.
    """
    # Fonte contabilistica exclusiva para 62 e divida: BA XML de fecho trimestral.
    # NIF 999999990 foi confirmado pela ULSLA para este apuramento.
    from importador_s3cp_xml import catalog, load, pmp_ba
    base=Path(__file__).resolve().parent
    quarters={}
    for (month,kind),meta in sorted(catalog(base).items()):
        if kind!='BA' or not re.fullmatch(r'20\d\d-(0[1-9]|1[0-2])',str(month)):
            continue
        m=int(month[-2:])
        if m not in (3,6,9,12):continue
        obj=load(base,month,'BA')
        if not obj:continue
        components=pmp_ba(obj)
        found={k:False for k in ('Fornecedores','Investimentos','Outros credores','FSE')}
        prefixes={'Fornecedores':('221','222','225','226'),
                  'Investimentos':('2711','2716'),
                  'Outros credores':('278929'), 'FSE':('62',)}
        for item in obj.get('registos',[]):
            if str(item.get('NIFEntidadeParceira',''))!='999999990':continue
            acc=str(item.get('ContaLocal','')).replace('.','').strip()
            for group,codes in prefixes.items():
                if any(acc.startswith(code) for code in codes):found[group]=True
        q=f'{month[:4]}-T{m//3}'
        missing=[label for label in ('Fornecedores','Investimentos','Outros credores') if not found[label]]
        quarters[q]={'Mês balancete':month,
                     'FSE acumulado (€)':components.get('FSE') if found['FSE'] else None,
                     'Dívida (€)':sum(components.get(k,0) for k in ('Fornecedores','Investimentos','Outros credores')) if not missing else None,
                     'BA fornecedores (€)':components.get('Fornecedores'),
                     'BA investimentos (€)':components.get('Investimentos'),
                     'BA outros credores (€)':components.get('Outros credores'),
                     'Contas de terceiros ausentes':', '.join(missing),
                     'Conta 62 encontrada':found['FSE'],
                     'Origem BA':'XML SNC-AP · NIF 999999990'}
    if d.empty:
        acq={};audit={};detail={}
    else:
        # Reclassificar também extratos guardados antes da correção 6.13.2.
        x=d.copy()
        x['Conta']=x['Conta'].astype(str).str.strip()
        x['Tipo']=x['Tipo'].astype(str).str.upper().str.strip()
        x['Data contabilização']=pd.to_datetime(x['Data contabilização'],errors='coerce')
        valid=x['Conta'].str.startswith(('31','43','45')) & x['Tipo'].ne('OD') & x['Data contabilização'].notna()
        x=x.loc[valid].copy()
        # Os valores líquido, débito e crédito já foram normalizados no importador.
        x['Valor líquido (€)']=pd.to_numeric(x['Valor líquido (€)'],errors='coerce')
        x['Trimestre']=x['Data contabilização'].dt.strftime('%Y')+'-T'+x['Data contabilização'].dt.quarter.astype(str)
        acq=x.groupby('Trimestre')['Valor líquido (€)'].sum().to_dict()
        audit=x.groupby('Trimestre').size().to_dict()
        detail=x.assign(Grupo=x['Conta'].str.extract(r'^(31|43|45)',expand=False)).groupby(['Trimestre','Grupo'])['Valor líquido (€)'].sum().to_dict()
    ids=sorted(set(quarters)|set(acq))
    rows=[]
    for q in ids:
        y,t=map(int,q.split('-T'))
        cur=quarters.get(q)
        prior=quarters.get(f'{y}-T{t-1}') if t>1 else None
        total62=cur['FSE acumulado (€)'] if cur else None
        # Janeiro-março: acumulado 62 do próprio ano. Nos restantes,
        # diferença entre acumulados em dois fechos trimestrais sucessivos.
        fse=(total62-(prior['FSE acumulado (€)'] if t>1 else 0.0)
             if total62 is not None and (t==1 or (prior and prior['FSE acumulado (€)'] is not None)) else None)
        aq=acq.get(q)
        joint=(aq+fse) if aq is not None and fse is not None else None
        issues=[]
        if cur is None: issues.append('Falta BA XML do fecho trimestral')
        elif cur['Contas de terceiros ausentes']:issues.append('Contas de terceiros ausentes: '+cur['Contas de terceiros ausentes'])
        elif not cur['Conta 62 encontrada']: issues.append('Conta 62 ausente no balancete')
        if t>1 and (prior is None or prior['FSE acumulado (€)'] is None):issues.append('Falta 62 acumulada do trimestre anterior')
        if aq is None:issues.append('Sem movimentos 31/43/45 para o trimestre — verificar extrato')
        if joint is not None and joint<=0:issues.append('Aquisições líquidas não positivas')
        rows.append({'Período':q,'Fecho contabilístico':cur['Mês balancete'] if cur else None,
                     'Aquisições 31/43/45 (€)':aq,'Movimentos não OD (n.º)':audit.get(q,0),
                     'Compras 31 trimestre (€)':detail.get((q,'31')),
                     'Ativos 43 trimestre (€)':detail.get((q,'43')),
                     'Investimento 45 trimestre (€)':detail.get((q,'45')),
                     'FSE 62 (€)':fse,'Aquisições totais (€)':joint,
                     'Dívida (€)':cur['Dívida (€)'] if cur else None,
                     'Fornecedores BA (€)':cur['BA fornecedores (€)'] if cur else None,
                     'Investimentos BA (€)':cur['BA investimentos (€)'] if cur else None,
                     'Outros credores BA (€)':cur['BA outros credores (€)'] if cur else None,
                     'Contas de terceiros ausentes':cur['Contas de terceiros ausentes'] if cur else '',
                     'Fonte 62 e dívida':'BA XML · NIF 999999990' if cur else 'BA XML em falta',
                     'PMP (dias)':None,'Estado':'Por apurar', 'Observações':'; '.join(issues)})
    lookup={r['Período']:r for r in rows}
    base_issues={r['Período']:bool(r['Observações']) for r in rows}
    for row in rows:
        y,t=map(int,row['Período'].split('-T'))
        window=[]
        for back in (3,2,1,0):
            yy,tt=y,t-back
            while tt<=0:yy-=1;tt+=4
            window.append(f'{yy}-T{tt}')
        pieces=[lookup.get(q) for q in window]
        if any(p is None or p['Aquisições totais (€)'] is None or p['Dívida (€)'] is None
               or base_issues.get(p['Período'],True) for p in pieces):
            row['Estado']='Dados insuficientes — janela de quatro trimestres'
            missing_window=[q for q,p in zip(window,pieces) if p is None or p['Aquisições totais (€)'] is None or p['Dívida (€)'] is None or base_issues.get(p['Período'],True)]
            row['Observações']='; '.join(filter(None,[row['Observações'],'Trimestres pendentes: '+', '.join(missing_window) if missing_window else '']))
            continue
        denominator=sum(p['Aquisições totais (€)'] for p in pieces)
        if denominator<=0:
            row['Estado']='Aquisições não positivas na janela';continue
        row['PMP (dias)']=365*(sum(p['Dívida (€)'] for p in pieces)/4)/denominator
        row['Estado']='Calculado — sujeito a validação contabilística'
    return pd.DataFrame(rows)

def render(data_balancetes=None):
    st.subheader('Aquisições do PMP — extratos contabilísticos 3 a 5')
    st.caption('A importação é analisada antes de gravar. Se já existirem movimentos do mesmo ano, a substituição exige confirmação explícita; é criada uma cópia de segurança.')
    up=st.file_uploader('Extrato de contas 3 a 5 (CSV)',type=['csv'],key='extrato_pmp_csv')
    if up is not None:
        try:
            incoming=load_csv(up.getvalue())
            preview=preview_import(incoming)
            st.info(f"Extrato analisado: {len(incoming):,} movimentos; anos: {', '.join(map(str,sorted(incoming.Ano.unique())))}.")
            st.dataframe(preview,hide_index=True,use_container_width=True)
            if preview['Sobreposição'].any():
                st.warning('Já existem dados dos anos identificados. Nenhum ficheiro será substituído sem autorização.')
                method=st.radio('Tratamento de movimentos existentes', ['Cancelar','Adicionar apenas movimentos não coincidentes','Substituir os extratos dos anos abrangidos'],index=0,key='pmp_import_method')
                ok=st.checkbox('Confirmo que verifiquei os anos abrangidos e autorizo a operação selecionada.',key='pmp_import_ack')
                enabled=method!='Cancelar' and ok
                if st.button('Confirmar importação dos extratos',disabled=not enabled,key='pmp_save_new',type='primary'):
                    result=commit_import(incoming,up.name,'adicionar' if method.startswith('Adicionar') else 'substituir')
                    st.success(f'Importação concluída para {len(result)} exercício(s).');st.rerun()
            else:
                if st.button('Guardar novo(s) exercício(s)',key='pmp_save_first',type='primary'):
                    commit_import(incoming,up.name,'adicionar');st.success('Dados guardados.');st.rerun()
        except Exception as e:st.error(f'Erro no extrato: {e}')
    with st.expander('Histórico de importações e cópias de segurança'):
        with db_connect() as con:
            hist=pd.read_sql_query('SELECT instante AS Data, ano AS Ano, nome_ficheiro AS Ficheiro, acao AS Operação, movimentos AS Movimentos, ficheiro_anterior AS Cópia FROM importacoes ORDER BY id DESC LIMIT 100',con)
        if hist.empty: st.caption('Sem novas importações registadas neste histórico.')
        else: st.dataframe(hist,hide_index=True,use_container_width=True)
        st.caption('Os extratos existentes antes desta versão permanecem disponíveis; não se atribui um histórico retroativo fictício.')
    d=all_stored()
    if d.empty:
        st.info('Ainda não foram importados extratos. O apuramento das aquisições fica pendente.');return
    st.write('Exercícios importados: **'+', '.join(map(str,sorted(d.Ano.unique())))+'**')
    d=d.copy()
    d['Conta']=d['Conta'].astype(str).str.strip()
    d['Tipo']=d['Tipo'].astype(str).str.upper().str.strip()
    is_acq=d['Conta'].str.startswith(('31','43','45'))
    d['Estado']='Excluído — fora de 31/43/45'
    d.loc[is_acq & d['Tipo'].eq('OD'),'Estado']='Excluído — OD'
    d.loc[is_acq & d['Tipo'].ne('OD'),'Estado']='Incluído — documento não OD'
    d.loc[d['Conta'].str.startswith('31'),'Rubrica']='31 — Compras'
    d.loc[d['Conta'].str.startswith('43'),'Rubrica']='43 — Ativos fixos tangíveis'
    d.loc[d['Conta'].str.startswith('45'),'Rubrica']='45 — Investimentos em curso'
    by,totals=summary(d)
    st.markdown('#### Aquisições líquidas por trimestre — contas 31, 43 e 45, sem OD')
    st.dataframe(totals.style.format({'Aquisições líquidas 31/43/45 (€)':'{:,.2f} €'}),hide_index=True,use_container_width=True)
    st.dataframe(by.style.format({'Valor líquido (€)':'{:,.2f} €'}),hide_index=True,use_container_width=True)
    st.markdown('#### PMP — BA XML com NIF 999999990 e extratos 31/43/45 sem OD')
    joined=reconcile_pmp(d,data_balancetes)
    if not joined.empty:
        st.dataframe(joined.style.format({c:'{:,.2f} €' for c in ['Aquisições 31/43/45 (€)','FSE 62 (€)','Aquisições totais (€)','Dívida (€)']}|{'PMP (dias)':'{:.1f}'},na_rep='—'),hide_index=True,use_container_width=True)
    st.info('A conta 62 e a dívida são obtidas exclusivamente dos BA XML guardados, com NIFEntidadeParceira = 999999990. As aquisições 31/43/45 continuam a usar os extratos sem OD. Se faltarem BA trimestrais, o PMP fica por apurar.')
    st.caption('São incluídos TODOS os tipos de documento exceto OD (incluindo P1, P2, NC, AC e DF). Cada movimento é atribuído pela data de contabilização e contabilizado com sinal débito menos crédito. A classificação não exclui automaticamente transferências entre 43 e 45: validar em auditoria.')
    with st.expander('Auditoria — movimentos incluídos, excluídos e pendentes'):
        opts=sorted(d['Trimestre'].dropna().unique(),reverse=True)
        selected=period_selectbox('Trimestre para auditar',opts,key='pmp_extrato_tri')
        sub=d[d['Trimestre']==selected]
        audit=sub.groupby(['Estado','Tipo'],as_index=False).agg(Movimentos=('Tipo','size'),**{'Débito (€)':('Débito (€)','sum'),'Crédito (€)':('Crédito (€)','sum'),'Valor líquido (€)':('Valor líquido (€)','sum')})
        st.dataframe(audit.style.format({c:'{:,.2f} €' for c in ['Débito (€)','Crédito (€)','Valor líquido (€)']}),hide_index=True,use_container_width=True)
        cols=[c for c in ['Conta','Data Contab.','Data Doc.','Nº Lancamento','Tipo','Nº Documento','Entidade','Designação','Rubrica','Débito (€)','Crédito (€)','Estado'] if c in sub]
        st.download_button('Exportar movimentos auditáveis (CSV)',sub[cols].to_csv(index=False,sep=';',decimal=',').encode('utf-8-sig'),f'pmp_auditoria_{selected}.csv','text/csv')
        st.dataframe(sub[cols].head(1000),hide_index=True,use_container_width=True)
