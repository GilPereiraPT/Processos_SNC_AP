"""ULSLA - Contabilidade Analitica (custos diretos), app Streamlit independente.
Nao altera a base de dados do dashboard financeiro.
"""
from __future__ import annotations
import hashlib
import io
import gzip
import json
import os
from pathlib import Path
import sqlite3
from decimal import Decimal
import xml.etree.ElementTree as ET
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from ulsla_branding import period_selectbox, period_multiselect
from ulsla_branding import hero

ROOT = Path(__file__).resolve().parent
BASE = ROOT / 'dados_analitica'
BASE.mkdir(exist_ok=True)
DB = BASE / 'analitica.sqlite3'
MAP_FILE = ROOT / 'ULSLA_Centros_Custo_Tipo_M_Grupos.csv'
if not MAP_FILE.exists():
    candidates = sorted(ROOT.glob('ULSLA_Centros_Custo_Tipo_M_Grupos*.csv'))
    if candidates: MAP_FILE = candidates[0]
VERSION = '2.9.0'


def connect():
    cx = sqlite3.connect(DB, timeout=90)
    cx.execute('PRAGMA journal_mode=WAL')
    cx.execute('PRAGMA busy_timeout=90000')
    cx.executescript('''
    CREATE TABLE IF NOT EXISTS movimentos (
      ano INTEGER NOT NULL, mes INTEGER NOT NULL, data_contab TEXT NOT NULL,
      cc TEXT NOT NULL, designacao TEXT, conta TEXT NOT NULL,
      conta_analitica TEXT, tipo TEXT, documento TEXT, docid TEXT,
      debito_cent INTEGER NOT NULL, credito_cent INTEGER NOT NULL,
      fonte_sha TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_mov_mes ON movimentos(ano,mes);
    CREATE INDEX IF NOT EXISTS idx_mov_cc ON movimentos(cc);
    CREATE INDEX IF NOT EXISTS idx_mov_conta ON movimentos(conta);
    CREATE TABLE IF NOT EXISTS ba_esperado (
      ano INTEGER NOT NULL, mes INTEGER NOT NULL,
      mensal_cent INTEGER NOT NULL, acumulado_cent INTEGER NOT NULL,
      hash TEXT NOT NULL, fonte TEXT, PRIMARY KEY (ano,mes));
    CREATE TABLE IF NOT EXISTS importacoes (
      ano INTEGER NOT NULL, mes INTEGER NOT NULL, sha TEXT NOT NULL,
      nome TEXT, linhas INTEGER, importado_em TEXT DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY(ano,mes));
    ''')
    columns = {r[1] for r in cx.execute('PRAGMA table_info(movimentos)')}
    if 'entidade' not in columns:
        cx.execute("ALTER TABLE movimentos ADD COLUMN entidade TEXT NOT NULL DEFAULT ''")
    cx.execute('CREATE INDEX IF NOT EXISTS idx_mov_entidade ON movimentos(entidade)')
    return cx


def eur_cent(value):
    text = str(value or '').strip().replace('€','').replace('\xa0','').replace(' ','')
    if ',' in text:
        text = text.replace('.','').replace(',','.')
    return int((Decimal(text or '0') * 100).quantize(Decimal('1')))


def euro(value):
    negative = value < 0
    value_text = f'{abs(int(value)) / 100:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return f'({value_text} €)' if negative else f'{value_text} €'


@st.cache_data(show_spinner=False)
def mapa_centros():
    d = pd.read_csv(MAP_FILE, encoding='utf-8-sig', sep=';', dtype=str)
    d.columns = d.columns.str.strip()
    d = d[d['Tipo'].str.strip().eq('M')].copy()
    d['Centro de Custos'] = d['Centro de Custos'].str.strip()
    # Classificação aprovada no livro ULSLA_Modelo_Report_Centros_Custo.xlsx,
    # folha Mapa_CC: Grupo Report (coluna M) / Subgrupo Report (coluna N).
    # O CSV de correspondência é uma fotografia fiel desse mapa e não altera lançamentos.
    class_file = ROOT / 'ULSLA_CC_Grupos_Report.csv'
    if class_file.is_file():
        cfg = pd.read_csv(class_file, sep=';', encoding='utf-8-sig', dtype=str).fillna('')
        cfg['Centro de Custos'] = cfg['Centro de Custos'].str.strip()
        if cfg['Centro de Custos'].duplicated().any():
            raise ValueError('Existem centros de custo repetidos no mapa de agrupamento.')
        d = d.merge(cfg[['Centro de Custos','Grupo report','Subgrupo report']],
                    on='Centro de Custos', how='left', validate='one_to_one')
        uncovered = d['Grupo report'].isna() | d['Grupo report'].eq('')
        if uncovered.any():
            raise ValueError('Centros sem grupo no livro de apoio: '+', '.join(d.loc[uncovered,'Centro de Custos'].tolist()[:20]))
        # Reutilizar os nomes já consumidos em todos os painéis e comparadores.
        d['Grande Grupo original'] = d['Grande Grupo']
        d['Subgrupo original fonte'] = d['Subgrupo original']
        d['Grande Grupo'] = d['Grupo report']
        d['Subgrupo original'] = d['Subgrupo report']
    return d


def parse_extrato(content):
    first = content[:2000].decode('cp1252', errors='replace')
    if 'C. Custo;' not in first:
        raise ValueError('Cabeçalho "C. Custo" não encontrado. Confirma o formato CAEXTMOV.')
    i = next(i for i, line in enumerate(content.decode('cp1252', errors='replace').splitlines()[:30]) if line.startswith('C. Custo;'))
    df = pd.read_csv(io.BytesIO(content), encoding='cp1252', sep=';', skiprows=i, dtype=str, low_memory=False)
    mandatory = ['C. Custo','Conta Ctbl.','Tipo','Nº Doc.','Dt de Contab.','Débito','Crédito']
    missing = [x for x in mandatory if x not in df.columns]
    if missing: raise ValueError(f'Colunas obrigatórias em falta: {missing}')
    # Ignorar apenas linhas inteiramente vazias; nunca descartar movimentos incompletos.
    df = df.dropna(how='all').copy()
    df = df.loc[~df[['C. Custo', 'Conta Ctbl.', 'Dt de Contab.']].isna().all(axis=1)].copy()
    # Preservar o código da entidade para permitir cruzamento com o cadastro.
    possiveis = ['Entidade', 'Cód. Entidade', 'Cod. Entidade', 'Código Entidade',
                 'Cod Entidade', 'Cód Entidade', 'Nº Entidade', 'Cod. Ent.', 'Entid.']
    col_entidade = next((c for c in df.columns if c.strip().lower() in
                        {p.lower() for p in possiveis}), None)
    if col_entidade is None:
        col_entidade = next((c for c in df.columns if 'entidade' in c.lower() and
                            not any(t in c.lower() for t in ('nome', 'descri', 'design'))), None)
    df['_entidade'] = (df[col_entidade].fillna('').astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
                       if col_entidade else '')
    df.attrs['entidade_coluna'] = col_entidade
    # Os extratos CAEXTMOV podem apresentar barras, hifens, horas ou espaços adicionais.
    raw_dates = df['Dt de Contab.'].fillna('').astype(str).str.strip()
    raw_dates = raw_dates.str.replace('\u00a0', ' ', regex=False).str.strip()
    parsed = pd.Series(pd.NaT, index=df.index, dtype='datetime64[ns]')
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%d.%m.%Y',
                '%Y-%m-%d', '%Y/%m/%d',
                '%d-%m-%Y %H:%M:%S', '%d/%m/%Y %H:%M:%S',
                '%d-%m-%Y %H:%M', '%d/%m/%Y %H:%M',
                '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        missing_dates = parsed.isna() & raw_dates.ne('')
        if not missing_dates.any():
            break
        parsed.loc[missing_dates] = pd.to_datetime(raw_dates.loc[missing_dates], format=fmt, errors='coerce')
    df['dt'] = parsed
    invalid = df['dt'].isna()
    if invalid.any():
        exemplos = df.loc[invalid, ['C. Custo', 'Conta Ctbl.', 'Dt de Contab.']].head(5).fillna('')
        detalhes = '; '.join(f"registo {int(idx) + 1}: {r['Dt de Contab.']!r} (CC {r['C. Custo']}, conta {r['Conta Ctbl.']})" for idx, r in exemplos.iterrows())
        raise ValueError(f'{int(invalid.sum())} datas contabilísticas inválidas ou em branco. Exemplos: {detalhes}. Nenhum movimento foi importado.')
    for col in ['Débito','Crédito']:
        def cv(s):
            try:return eur_cent(s)
            except Exception:raise ValueError(f'Valor monetário inválido na coluna {col}: {s}')
        df[col+'_cent'] = df[col].map(cv)
    df['ano'] = df['dt'].dt.year.astype(int)
    df['mes'] = df['dt'].dt.month.astype(int)
    if not df['Conta Ctbl.'].str.strip().str.startswith('6').all():
        raise ValueError('O extrato contém contas fora da classe 6. Envia exclusivamente movimentos da classe 6.')
    known = set(mapa_centros()['Centro de Custos'])
    unknown = sorted(set(df['C. Custo'].str.strip()) - known)
    # Nao ignorar centros desconhecidos: isso prejudicaria a reconciliacao.
    return df, unknown


def parse_ba(content):
    root = ET.fromstring(content)
    if root.tag.split('}')[-1] != 'BA':raise ValueError('O ficheiro selecionado não é um BA XML.')
    cab = root.find('Cabecalho')
    if cab is None:raise ValueError('BA sem cabeçalho.')
    ano = int(cab.findtext('Ano'))
    mes_original = int(cab.findtext('Periodo'))
    if mes_original < 1 or mes_original > 14:raise ValueError('Período do BA inválido.')
    mes = min(12,mes_original)
    sums = {'BA02':0,'BA03':0}
    for reg in root.findall('./Registos/Registo'):
        if not (reg.findtext('ContaLocal') or '').replace('.','').startswith('6'):continue
        for v in reg.findall('DetalheResumo'):
            typ = v.findtext('SaldosEMovimentos')
            if typ in sums:
                sums[typ] += eur_cent(v.findtext('Debito'))-eur_cent(v.findtext('Credito'))
    return ano,mes,sums['BA02'],sums['BA03']



def ba_financeiro_caminhos(ano, mes):
    # O Dashboard Financeiro guarda os BA como JSON comprimido na pasta compartilhada.
    base = ROOT / 'dados_s3cp_xml'
    if not base.exists():
        return []
    if mes != 12:
        caminho = base / f'{ano}-{mes:02d}' / 'BA.json.gz'
        return [caminho] if caminho.is_file() else []
    # Dezembro, incluindo arquivos mais antigos de fechos 13/14.
    return [p for p in (base / f'{ano}-{n:02d}' / 'BA.json.gz' for n in (14,13,12)) if p.is_file()]


def referencia_ba_guardado(path):
    with gzip.open(path, 'rt', encoding='utf-8') as handle:
        obj = json.load(handle)
    if obj.get('tipo') != 'BA':
        raise ValueError('O mapa guardado nao e BA.')
    total = {'BA02': 0, 'BA03': 0}
    for reg in obj.get('registos', []):
        conta = str(reg.get('ContaLocal', '')).replace('.', '').strip()
        if not conta.startswith('6'):
            continue
        for key in total:
            detalhe = reg.get('detalhes', {}).get(key, {})
            total[key] += eur_cent(str(detalhe.get('Debito', 0))) - eur_cent(str(detalhe.get('Credito', 0)))
    periodo = obj.get('periodo_original') or obj.get('periodo') or ''
    rank = int(str(periodo).split('-')[-1]) if '-' in str(periodo) else 0
    return total['BA02'], total['BA03'], str(obj.get('hash', '')), rank


def sincronizar_ba_financeiro(cx):
    # Guarda apenas os totais para consulta rapida; nunca altera o Dashboard Financeiro.
    meses = cx.execute('SELECT ano, mes FROM importacoes').fetchall()
    actualizados, erros = 0, []
    for ano, mes in meses:
        caminhos = ba_financeiro_caminhos(ano, mes)
        if not caminhos:
            continue
        candidatos = []
        for caminho in caminhos:
            try:
                mensal, acumulado, sha, rank = referencia_ba_guardado(caminho)
                candidatos.append((rank, mensal, acumulado, sha, caminho))
            except Exception as exc:
                erros.append(f'{ano}-{mes:02d}: {exc}')
        if not candidatos:
            continue
        _, mensal, acumulado, sha, caminho = max(candidatos, key=lambda x: x[0])
        fonte = 'Dashboard Financeiro: ' + str(caminho.relative_to(ROOT))
        anterior = cx.execute('SELECT hash, fonte FROM ba_esperado WHERE ano=? AND mes=?', (ano, mes)).fetchone()
        if anterior == (sha, fonte):
            continue
        with cx:
            cx.execute('INSERT INTO ba_esperado(ano,mes,mensal_cent,acumulado_cent,hash,fonte) '
                       'VALUES(?,?,?,?,?,?) ON CONFLICT(ano,mes) DO UPDATE SET '
                       'mensal_cent=excluded.mensal_cent,acumulado_cent=excluded.acumulado_cent, '
                       'hash=excluded.hash,fonte=excluded.fonte',
                       (ano, mes, mensal, acumulado, sha, fonte))
        actualizados += 1
    return actualizados, erros


def read_validation(cx):
    data = cx.execute('''SELECT i.ano,i.mes,i.linhas,i.nome,b.mensal_cent,b.acumulado_cent,
         COALESCE((SELECT SUM(m.debito_cent-m.credito_cent) FROM movimentos m WHERE m.ano=i.ano AND m.mes=i.mes),0) mensal,
         COALESCE((SELECT SUM(m.debito_cent-m.credito_cent) FROM movimentos m WHERE m.ano=i.ano AND m.mes<=i.mes),0) acumulado,
         (SELECT COUNT(DISTINCT m2.mes) FROM movimentos m2 WHERE m2.ano=i.ano AND m2.mes<=i.mes) meses_carregados
         FROM importacoes i LEFT JOIN ba_esperado b ON b.ano=i.ano AND b.mes=i.mes
         ORDER BY i.ano DESC,i.mes DESC''').fetchall()
    rows=[]
    for ano,mes,linhas,nome,bm,bc,monthly,cumul,months in data:
        if bm is None:status='BA em falta'
        elif monthly != bm:status='Divergência mensal'
        elif months < mes:status='Histórico incompleto (acumulado não verificável)'
        elif cumul != bc:status='Divergência acumulada'
        else:status='Validado'
        rows.append({'Período':f'{ano}-{mes:02d}','Movimentos':linhas,'Analítica mensal (€)':monthly/100,
           'BA mensal (€)':None if bm is None else bm/100,'Diferença mensal (€)':None if bm is None else (monthly-bm)/100,
           'Analítica acumulada (€)':cumul/100,'BA acumulado (€)':None if bc is None else bc/100,
           'Diferença acumulada (€)':None if bc is None or months<mes else (cumul-bc)/100,
           'Estado':status,'Ficheiro':nome})
    return pd.DataFrame(rows)


def save_import(cx,df,sha,nome):
    cols=['ano','mes','dt','C. Custo','Designação','Conta Ctbl.','Conta Analítica','Tipo','Nº Doc.','DOCID','_entidade','Débito_cent','Crédito_cent']
    for c in ['Designação','Conta Analítica','DOCID']:
        if c not in df:df[c]=''
    changes=[]
    with cx:
        for (ano,mes),part in df.groupby(['ano','mes'],sort=True):
            cx.execute('DELETE FROM movimentos WHERE ano=? AND mes=?',(int(ano),int(mes)))
            sql='''INSERT INTO movimentos(ano,mes,data_contab,cc,designacao,conta,conta_analitica,tipo,documento,docid,entidade,debito_cent,credito_cent,fonte_sha)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)'''
            records = ((int(ano),int(mes),t.strftime('%Y-%m-%d'),str(cc).strip(),str(des),str(conta).strip(),str(anal),str(tipo),str(doc),str(docid),str(entidade).strip(),int(deb),int(cred),sha)
                for t,cc,des,conta,anal,tipo,doc,docid,entidade,deb,cred in part[['dt','C. Custo','Designação','Conta Ctbl.','Conta Analítica','Tipo','Nº Doc.','DOCID','_entidade','Débito_cent','Crédito_cent']].itertuples(index=False,name=None))
            cx.executemany(sql,records)
            cx.execute('''INSERT INTO importacoes(ano,mes,sha,nome,linhas) VALUES(?,?,?,?,?)
                 ON CONFLICT(ano,mes) DO UPDATE SET sha=excluded.sha,nome=excluded.nome,linhas=excluded.linhas,importado_em=CURRENT_TIMESTAMP''',
                 (int(ano),int(mes),sha,nome,len(part)))
            changes.append(f'{ano}-{mes:02d}: {len(part):,} movimentos')
    return changes


# Only aggregated, indexed SQL results reach the visualisations. No full CSV reload.
def periods_available(cx):
    return [f'{a}-{m:02d}' for a,m in cx.execute('SELECT ano,mes FROM importacoes ORDER BY ano,mes').fetchall()]


def cost_frame(cx, period_list, center_ids, account_prefix='', por_entidade=False):
    if not period_list or not center_ids:
        return pd.DataFrame(columns=['ano','mes','cc','conta','cent','movimentos'])
    # SQLite parameter limit: 553 centers + periods remains safe on legacy SQLite.
    periods=[(int(p[:4]),int(p[5:])) for p in period_list]
    conditions=' OR '.join('(ano=? AND mes=?)' for _ in periods)
    coluna_entidade = ', entidade' if por_entidade else ''
    query=f'''SELECT ano,mes,cc,conta{coluna_entidade},SUM(debito_cent-credito_cent) cent,COUNT(*) movimentos
      FROM movimentos WHERE ({conditions}) AND cc IN ({','.join('?' for _ in center_ids)})'''
    args=[x for pair in periods for x in pair] + list(center_ids)
    if account_prefix:
        query+=' AND conta LIKE ?';args.append(account_prefix+'%')
    query+=' GROUP BY ano,mes,cc,conta' + coluna_entidade
    return pd.read_sql_query(query,cx,params=args)


def join_map(df, mapping):
    if df.empty:return df
    out=df.merge(mapping[['Centro de Custos','Designação','Grande Grupo','Subgrupo original']],
          left_on='cc',right_on='Centro de Custos',how='left')
    out['Periodo']=out['ano'].astype(str)+'-'+out['mes'].astype(str).str.zfill(2)
    out['Grupo']=out['Grande Grupo'].fillna('Centro sem classificação')
    out['Subgrupo']=out['Subgrupo original'].fillna('Sem subgrupo')
    out['Centro']=out['cc']+' — '+out['Designação'].fillna('Sem designação')
    out['Conta']=out['conta']
    return out


def styled_amounts(df, columns=('Valor (€)', 'Diferença (€)', 'Período A (€)', 'Período B (€)')):
    t=df.copy()
    for c in columns:
        if c in t:
            t[c]=t[c].apply(lambda v: euro(round(float(v)*100)) if pd.notna(v) else '—')
    for c in ['Variação (%)']:
        if c in t:
            t[c]=t[c].apply(lambda v: f'{v:,.1f}%'.replace(',','X').replace('.',',').replace('X','.') if pd.notna(v) else 'n/a')
    return t


def download_table(df, title, key):
    st.download_button('Exportar CSV — '+title, data=df.to_csv(index=False,sep=';').encode('utf-8-sig'),
        file_name='ULSLA_analitica_'+key+'.csv',mime='text/csv',key='dl_'+key)


def chart_bar(df, category, val, title, horizontal=True, height=420):
    if df.empty:return
    shown=df.sort_values(val, ascending=False).head(22).copy()
    if horizontal:
        shown=shown.sort_values(val)
        fig=px.bar(shown,y=category,x=val,orientation='h',color=val,
                   color_continuous_scale=['#e2a050','#207bba'],title=title)
        fig.update_layout(yaxis_title='',xaxis_title='Euros',height=height)
    else:
        fig=px.bar(shown,x=category,y=val,color=val,
                   color_continuous_scale=['#e2a050','#207bba'],title=title)
        fig.update_layout(xaxis_title='',yaxis_title='Euros',height=height)
    fig.update_layout(template='plotly_dark',paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',
        showlegend=False,coloraxis_showscale=False,margin=dict(l=12,r=12,t=65,b=12),
        font=dict(family='Arial'),hovermode='closest')
    fig.update_traces(hovertemplate='%{y}<br>%{x:,.2f} €<extra></extra>' if horizontal else '%{x}<br>%{y:,.2f} €<extra></extra>')
    st.plotly_chart(fig,use_container_width=True,theme=None)


def premium_chart(fig, height=430):
    fig.update_layout(template='plotly_dark', height=height, paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)', font=dict(family='Arial',size=12,color='#dce8f5'),
        margin=dict(l=12,r=24,t=55,b=35), hovermode='closest',
        legend=dict(orientation='h',y=1.13,x=0),
        xaxis=dict(showgrid=False),yaxis=dict(gridcolor='rgba(155,177,207,.13)'))
    st.plotly_chart(fig,use_container_width=True,theme=None)


def premium_insights(frame, mapping, available, selection):
    st.markdown('### Inteligência de custos')
    periods_sorted=sorted(set(selection))
    monthly=frame.groupby('Periodo',as_index=False)['cent'].sum().sort_values('Periodo')
    monthly['euros']=monthly['cent']/100
    if len(monthly)>1:
        last=monthly.iloc[-1]; previous=monthly.iloc[-2]
        change=last['euros']-previous['euros']
        pct=100*change/abs(previous['euros']) if previous['euros'] else None
        a,b,c,d=st.columns(4)
        a.metric('Último mês selecionado',euro(round(last['cent'])))
        b.metric('Variação face ao mês anterior selecionado',euro(round(change*100)),
                 delta=f'{pct:+.1f}%' if pct is not None else None,delta_color='inverse')
        c.metric('Média por mês selecionado',euro(round(monthly['cent'].mean())))
        d.metric('Meses com movimentos',len(monthly))
        st.caption('A comparação anterior usa os meses selecionados com movimentos; não pressupõe continuidade temporal.')
    tab1,tab2,tab3,tab4=st.tabs(['Evolução e composição','Ranking e Pareto','Mapa de calor','Comparação homóloga'])
    with tab1:
        breakdown=frame.groupby(['Periodo','Grupo'],as_index=False)['cent'].sum()
        breakdown['Euros']=breakdown['cent']/100
        fig=px.bar(breakdown,x='Periodo',y='Euros',color='Grupo',barmode='relative',
                   title='Evolução mensal por grande grupo',color_discrete_sequence=px.colors.qualitative.Safe)
        fig.update_traces(hovertemplate='%{x}<br>%{y:,.2f} €<extra></extra>')
        premium_chart(fig)
        pivot=breakdown.pivot_table(index='Periodo',columns='Grupo',values='Euros',aggfunc='sum',fill_value=0)
        if len(pivot)>1:
            fig=go.Figure()
            for col in pivot.columns:
                fig.add_trace(go.Scatter(x=pivot.index,y=pivot[col].cumsum(),mode='lines+markers',name=str(col),
                    hovertemplate='%{x}<br>%{y:,.2f} €<extra></extra>'))
            fig.update_layout(title='Acumulado dos meses selecionados (não substitui YTD contabilístico)',yaxis_title='Euros')
            premium_chart(fig)
    with tab2:
        dimension=st.selectbox('Ranking por',['Centro','Subgrupo','Conta','Grupo'],key='premium_rank_dim')
        ranked=frame.groupby(dimension,as_index=False)['cent'].sum().sort_values('cent',ascending=False)
        ranked['Euros']=ranked['cent']/100
        ranked['Peso (%)']=ranked['cent']/ranked['cent'].sum()*100 if ranked['cent'].sum()!=0 else 0
        top=ranked.head(20).sort_values('Euros')
        fig=px.bar(top,x='Euros',y=dimension,orientation='h',title='20 maiores rubricas / centros',
                   color='Euros',color_continuous_scale=['#1b668c','#5bc0eb'])
        fig.update_layout(coloraxis_showscale=False)
        premium_chart(fig,max(430,len(top)*28+100))
        positive=ranked[ranked['cent']>0].copy()
        if not positive.empty:
            positive['Peso acumulado (%)']=positive['cent'].cumsum()/positive['cent'].sum()*100
            st.dataframe(styled_amounts(positive[[dimension,'Euros','Peso (%)','Peso acumulado (%)']].rename(columns={'Euros':'Valor (€)'})),
                         hide_index=True,use_container_width=True)
    with tab3:
        dimension=st.selectbox('Linhas do mapa de calor',['Grupo','Subgrupo','Centro'],key='premium_heat_dim')
        hot=frame.groupby([dimension,'Periodo'],as_index=False)['cent'].sum()
        leaders=hot.groupby(dimension)['cent'].sum().abs().nlargest(18).index
        matrix=hot[hot[dimension].isin(leaders)].pivot(index=dimension,columns='Periodo',values='cent').fillna(0)/100
        if not matrix.empty:
            fig=px.imshow(matrix,aspect='auto',color_continuous_scale='Blues',
                labels=dict(x='Período',y=dimension,color='Euros'),title='Intensidade dos custos por período')
            fig.update_traces(hovertemplate='%{y}<br>%{x}<br>%{z:,.2f} €<extra></extra>')
            premium_chart(fig,max(390,len(matrix)*30+130))
    with tab4:
        by=frame.groupby(['ano','mes','Grupo'],as_index=False)['cent'].sum()
        years=sorted(by['ano'].unique())
        if len(years)<2:
            st.info('A comparação homóloga exige movimentos importados de pelo menos dois anos.')
        else:
            ynew=period_selectbox('Ano em análise',years[::-1],key='premium_ynew')
            yold=period_selectbox('Ano de referência',[y for y in years if y!=ynew],key='premium_yold')
            months_new=set(by.loc[by.ano==ynew,'mes']);months_old=set(by.loc[by.ano==yold,'mes'])
            common=sorted(months_new & months_old)
            st.caption('Meses comuns com movimentos: '+(', '.join(f'{m:02d}' for m in common) or 'nenhum')+'. A comparação exclui meses não comuns.')
            if common:
                comp=by[by.mes.isin(common)].groupby(['Grupo','ano'])['cent'].sum().unstack(fill_value=0)
                comp=comp.reindex(columns=[yold,ynew],fill_value=0)/100
                comp.columns=['Referência (€)','Análise (€)']
                comp['Diferença (€)']=comp['Análise (€)']-comp['Referência (€)']
                comp['Variação (%)']=comp.apply(lambda r:100*r['Diferença (€)']/abs(r['Referência (€)']) if r['Referência (€)'] else float('nan'),axis=1)
                fig=go.Figure()
                for name,color in [('Referência (€)','#46a9df'),('Análise (€)','#e9aa61')]:
                    fig.add_bar(x=comp.index,y=comp[name],name=name,marker_color=color,
                                hovertemplate='%{x}<br>%{y:,.2f} €<extra></extra>')
                fig.update_layout(title='Comparação homóloga — mesmos meses',barmode='group',yaxis_title='Euros')
                premium_chart(fig)
                st.dataframe(styled_amounts(comp.reset_index(),['Referência (€)','Análise (€)','Diferença (€)']),
                             hide_index=True,use_container_width=True)



# Entidades e classificacao das contas: tabelas locais, sem alterar o dashboard financeiro.
ENT_FILE = ROOT / 'LIST_ENTIDADES_15102026.CSV'
PLANO_FILE = ROOT / 'LIST_PCONTAS_15102026.CSV'
PLANO_ALTERNATIVO = ROOT / 'plano_contas_dashboard.csv'
GRUPOS_SNC = {
    '60':'Custo das mercadorias vendidas e matérias consumidas',
    '61':'Custo das mercadorias vendidas e matérias consumidas',
    '62':'Fornecimentos e serviços externos',
    '63':'Gastos com pessoal',
    '64':'Gastos de depreciação e amortização',
    '65':'Perdas por imparidade',
    '66':'Perdas por reduções de justo valor',
    '67':'Provisões do período',
    '68':'Outros gastos e perdas',
    '69':'Gastos e perdas de financiamento',
}

@st.cache_data(show_spinner=False)
def entidades_catalogo():
    """Lê o cadastro por campos estáveis, sem perder linhas por ';' em observações.

    O ficheiro exportado inclui campos livres, contactos e endereços adicionais
    que podem conter separadores. Precisamos apenas de Código, Nome e NIF;
    o NIF ocupa a nona coluna do layout original (índice 8).
    """
    if not ENT_FILE.is_file():
        return pd.DataFrame(columns=['Código','Nome','NIF'])
    linhas = []
    with ENT_FILE.open('r', encoding='cp1252', errors='replace', newline='') as handle:
        for numero, linha in enumerate(handle, start=1):
            if numero <= 3:  # localização, data e cabeçalho do relatório
                continue
            campos = linha.rstrip('\r\n').split(';', 9)
            if len(campos) < 2:
                continue
            codigo = normalizar_codigo(campos[0])
            if not codigo or not codigo.isdigit():
                continue  # linhas de rodapé/totalização
            nome = campos[1].strip()
            nif = campos[8].strip() if len(campos) > 8 else ''
            linhas.append((codigo, nome, nif))
    df = pd.DataFrame(linhas, columns=['Código','Nome','NIF'])
    if df.empty:
        return df
    # Prefere designações não vazias em duplicados.
    df = df.sort_values('Nome', key=lambda x: x.eq('').astype(int))
    return df.drop_duplicates('Código', keep='first').reset_index(drop=True)

def normalizar_codigo(value):
    """Código textual, preservando zeros; elimina apenas separadores de exportação."""
    import re
    s = str(value or '').strip().lstrip("'\"").strip()
    return re.sub(r'\.0+$', '', s).replace(' ', '').replace('.', '')


@st.cache_data(show_spinner=False)
def plano_contas():
    """Plano oficial com linhas de totalização e movimento; nunca soma pais e filhos."""
    source = PLANO_FILE if PLANO_FILE.is_file() else PLANO_ALTERNATIVO
    if not source.is_file():
        return pd.DataFrame(columns=['Conta','Designação','Grupo','Tipo'])
    if source == PLANO_FILE:
        df = pd.read_csv(source, sep=';', encoding='cp1252', skiprows=3,
                         dtype=str, on_bad_lines='skip').fillna('')
    else:
        df = pd.read_csv(source, sep=';', encoding='utf-8-sig', dtype=str).fillna('')
    df.columns=df.columns.str.strip()
    if not {'Conta','Designação'}.issubset(df.columns):
        return pd.DataFrame(columns=['Conta','Designação','Grupo','Tipo'])
    if 'Grupo' not in df: df['Grupo']=''
    if 'Tipo' not in df: df['Tipo']=''
    df['Conta']=df['Conta'].map(normalizar_codigo)
    df['Designação']=df['Designação'].astype(str).str.strip()
    df=df.loc[df['Conta'].str.match(r'^6[0-9]+$',na=False)].copy()
    df['Grupo']=df['Grupo'].astype(str).str.strip()
    return df[['Conta','Designação','Grupo','Tipo']].drop_duplicates('Conta',keep='last')


@st.cache_data(show_spinner=False)
def lookup_plano():
    plano = plano_contas()
    return (plano.set_index('Conta')[['Designação','Grupo']].to_dict('index')
            if not plano.empty else {})


def obter_grupo_e_designacao(codigo, contas):
    """Usa conta exata; só recorre à ancestral quando não existe a conta no plano."""
    codigo=normalizar_codigo(codigo)
    match=codigo if codigo in contas else next(
        (codigo[:i] for i in range(len(codigo)-1,1,-1) if codigo[:i] in contas),None)
    entry=contas.get(match,{})
    label=str(entry.get('Designação','')).strip()
    grupo=str(entry.get('Grupo','')).strip() or GRUPOS_SNC.get(codigo[:2],'Outros gastos (classe 6)')
    if match and match!=codigo:
        label=(label+' (conta agregadora)').strip()
    return grupo, (label or 'Sem designação no plano oficial')


def enriquecer_contas(df):
    if df.empty:return df
    df=df.copy()
    df['Conta_normalizada']=df['conta'].map(normalizar_codigo)
    catalogo=lookup_plano()
    unique={c:obter_grupo_e_designacao(c,catalogo) for c in df['Conta_normalizada'].unique()}
    df['Rubrica']=df['Conta_normalizada'].map(lambda c:unique[c][0])
    df['Designação da conta']=df['Conta_normalizada'].map(lambda c:unique[c][1])
    df['Conta identificada']=df['Conta_normalizada']+' — '+df['Designação da conta']
    return df


def entidade_salarios(codigo):
    c=normalizar_codigo(codigo)
    return c.startswith(('9963','9990000'))

def periodos_homologos(periodos, escolhido):
    ano,mes=map(int,escolhido.split('-'))
    return f'{ano-1}-{mes:02d}' if f'{ano-1}-{mes:02d}' in periodos else None

def entidade_frame(cx, meses, ids):
    return cost_frame(cx,meses,ids,por_entidade=True)


def painel_rubricas_entidades(cx,periodos,mapa):
    st.subheader('Rubricas SNC-AP e entidades')
    st.caption('Escolhe um único período. Comparação automática com o mês homólogo do ano anterior; sem estimar meses em falta.')
    escolhido=period_selectbox('Período em análise',sorted(periodos,reverse=True),key='re_periodo')
    homologo=periodos_homologos(periodos,escolhido)
    if not homologo: st.warning('Não existe o período homólogo importado. Serão mostrados os custos do período selecionado.')
    cat=entidades_catalogo()
    plano=plano_contas()
    if cat.empty:st.warning('Falta o ficheiro LIST_ENTIDADES_15102026.CSV na pasta da aplicação.')
    if plano.empty:st.warning('Plano de contas oficial em falta: coloca LIST_PCONTAS_15102026.CSV na pasta da aplicação.')
    cc_groups=sorted(mapa['Grande Grupo'].dropna().unique().tolist())
    cc_scope=st.selectbox('Grupo de centros de custo', ['Total ULSLA']+cc_groups,key='re_group_cc')
    meses=[escolhido]+([homologo] if homologo else [])
    scoped=mapa if cc_scope=='Total ULSLA' else mapa.loc[mapa['Grande Grupo'].eq(cc_scope)]
    ids=scoped['Centro de Custos'].dropna().astype(str).str.strip().unique().tolist()
    base=entidade_frame(cx,meses,ids)
    if base.empty:st.info('Não existem movimentos nos períodos escolhidos.');return
    base=enriquecer_contas(base)
    base['entidade']=base['entidade'].map(normalizar_codigo)
    base['É vencimento']=base['entidade'].map(entidade_salarios)
    base=base.merge(cat,left_on='entidade',right_on='Código',how='left',validate='many_to_one')
    base['Entidade designada']=base.apply(lambda r: (str(r['entidade'])+' — '+str(r['Nome'])) if pd.notna(r['Nome']) and str(r['Nome']).strip() else
             ((str(r['entidade'])+' — Código não encontrado') if str(r['entidade']).strip() else 'Sem entidade no extrato'),axis=1)
    base['Periodo']=base['ano'].astype(str)+'-'+base['mes'].astype(str).str.zfill(2)
    presentes=base.loc[base['Periodo'].eq(escolhido)]
    ref=base.loc[base['Periodo'].eq(homologo)] if homologo else base.iloc[:0]
    cur=presentes['cent'].sum()/100; old=ref['cent'].sum()/100
    diff=cur-old
    base_fornecedores=base.loc[~base['É vencimento'] & base['entidade'].ne('9999999')].copy()
    fornecedores=base_fornecedores.loc[base_fornecedores['Periodo'].eq(escolhido)]
    fornecedores_ref=base_fornecedores.loc[base_fornecedores['Periodo'].eq(homologo)] if homologo else base_fornecedores.iloc[:0]
    desconhecidos_df=fornecedores.loc[fornecedores['entidade'].ne('') & fornecedores['Nome'].isna()].copy()
    desconhecidas=desconhecidos_df['entidade'].nunique()
    sem_codigo=int(presentes.loc[presentes['entidade'].eq(''),'movimentos'].sum())
    a,b,c,d=st.columns(4)
    a.metric('Custos do período',euro(round(cur*100)))
    b.metric('Homólogo' if homologo else 'Homólogo indisponível',euro(round(old*100)) if homologo else '—')
    c.metric('Variação homóloga',euro(round(diff*100)) if homologo else '—',
             delta=f'{diff/abs(old)*100:+.1f}%' if homologo and old else None,delta_color='inverse')
    d.metric('Códigos não identificados',int(desconhecidas))
    if desconhecidas:
        st.warning(f'{desconhecidas} códigos de entidade com movimentos não constam do cadastro carregado, após normalização. Os códigos de vencimentos estão excluídos deste controlo.')
        diagnostico=desconhecidos_df.groupby('entidade',as_index=False).agg(
            movimentos=('movimentos','sum'),valor_cent=('cent','sum'))
        diagnostico['Valor (€)']=diagnostico['valor_cent']/100
        with st.expander('Consultar códigos de entidade sem correspondência'):
            st.dataframe(styled_amounts(diagnostico[['entidade','movimentos','Valor (€)']]),hide_index=True,use_container_width=True)
            st.download_button('Exportar códigos por identificar',diagnostico.to_csv(index=False,sep=';').encode('utf-8-sig'),
                               file_name='ULSLA_entidades_nao_identificadas.csv',mime='text/csv')
    tab1,tab2,tab3=st.tabs(['Rubricas de custos','Entidades / fornecedores','Evolução e detalhe'])
    def comparar(dim):
        a=presentes.groupby(dim)['cent'].sum()/100
        b=ref.groupby(dim)['cent'].sum()/100
        v=pd.concat([b.rename('Homólogo (€)'),a.rename('Atual (€)')],axis=1).fillna(0).reset_index()
        v['Diferença (€)']=v['Atual (€)']-v['Homólogo (€)']
        v['Variação (%)']=v.apply(lambda r:100*r['Diferença (€)']/abs(r['Homólogo (€)']) if r['Homólogo (€)'] else float('nan'),axis=1)
        return v.sort_values('Atual (€)',ascending=False)
    with tab1:
        for dim in ['Rubrica','Conta identificada']:
            st.markdown('**'+('Grupos de custos' if dim=='Rubrica' else 'Contas SNC-AP')+'**')
            t=comparar(dim)
            top=t.head(16).iloc[::-1]
            if not top.empty:
                fig=go.Figure()
                if homologo:fig.add_bar(y=top[dim],x=top['Homólogo (€)'],name=homologo,orientation='h',marker_color='#8ab5cb')
                fig.add_bar(y=top[dim],x=top['Atual (€)'],name=escolhido,orientation='h',marker_color='#0c8eaf')
                fig.update_layout(barmode='group',height=max(370,len(top)*35+125),title='Comparação homóloga',margin=dict(l=15,r=60,t=60,b=35),xaxis_title='Euros',yaxis_title='',template='plotly_white',legend=dict(orientation='h',y=1.12))
                fig.update_xaxes(tickformat=',.0f',automargin=True)
                fig.update_yaxes(automargin=True)
                st.plotly_chart(fig,use_container_width=True)
            st.dataframe(styled_amounts(t,['Homólogo (€)','Atual (€)','Diferença (€)']),hide_index=True,use_container_width=True)
    with tab2:
        if sem_codigo==int(presentes['movimentos'].sum()):
            st.warning('Os movimentos atualmente importados não incluem código de entidade. Importa novamente o CAEXTMOV contendo a coluna Entidade para ativar a análise nominal. Os valores anteriores permanecem intactos até à nova importação.')
        st.info('Os códigos iniciados por 9963 ou 9990000 (vencimentos) e o código 9999999 (Diversos) são excluídos da análise por entidade. Permanecem nos gastos, nas rubricas e na reconciliação.')
        if fornecedores.empty:
            st.info('Não existem movimentos de entidades não salariais neste período.')
        t_prev=presentes; r_prev=ref
        presentes=fornecedores; ref=fornecedores_ref
        t=comparar('Entidade designada')
        presentes=t_prev; ref=r_prev
        st.caption('Exclui vencimentos e Diversos (9999999). A classificação sem entidade distingue extratos sem código de entidades desconhecidas no cadastro.')
        top=t.sort_values('Atual (€)',ascending=False).head(20).iloc[::-1]
        if not top.empty:
            fig=px.bar(top,x='Atual (€)',y='Entidade designada',orientation='h',text='Atual (€)',title='Entidades com maior volume de custos')
            fig.update_traces(marker_color='#0c8eaf',texttemplate='%{x:,.0f} €',textposition='outside',cliponaxis=False)
            fig.update_layout(template='plotly_white',height=max(430,len(top)*33+140),margin=dict(l=15,r=95,t=55,b=25),yaxis_title='',xaxis_title='Euros')
            st.plotly_chart(fig,use_container_width=True)
        st.dataframe(styled_amounts(t,['Homólogo (€)','Atual (€)','Diferença (€)']),hide_index=True,use_container_width=True)
    with tab3:
        st.caption('Âmbito de CC: '+cc_scope)
        series=base.groupby(['Periodo','Rubrica'],as_index=False)['cent'].sum()
        series['Valor (€)']=series['cent']/100
        fig=px.bar(series,x='Rubrica',y='Valor (€)',color='Periodo',barmode='group',title='Estrutura de custos por rubrica')
        fig.update_layout(template='plotly_white',height=480,xaxis_tickangle=-20,margin=dict(l=20,r=20,t=60,b=100))
        st.plotly_chart(fig,use_container_width=True)
        table=presentes.groupby(['conta','Designação da conta','Rubrica','entidade','Entidade designada','cc'],as_index=False)['cent'].sum()
        table['Valor (€)']=table['cent']/100
        st.caption('O detalhe contabilístico inclui vencimentos para preservar a reconciliação; apenas a análise de fornecedores os exclui.')
        st.dataframe(styled_amounts(table[['conta','Designação da conta','Rubrica','Entidade designada','cc','Valor (€)']].sort_values('Valor (€)',ascending=False)),hide_index=True,use_container_width=True)
        st.download_button('Exportar detalhe (CSV)',table.to_csv(index=False,sep=';').encode('utf-8-sig'),file_name='ULSLA_rubricas_entidades_'+escolhido+'.csv',mime='text/csv')

def money_summary(df):
    return round(df['cent'].sum()) if not df.empty else 0



# Painel executivo: períodos homólogos e indicadores de gestão.
from html import escape as html_escape

REPORT_GROUPS = ['Cuidados de Saúde Hospitalares', 'Cuidados de Saúde Primários',
                 'Serviços de Apoio Clínico', 'Serviços Administrativos',
                 'Gastos Não Imputáveis']

def display_compact_cent(cent):
    value = abs(float(cent)) / 100
    prefix = '−' if cent < 0 else ''
    if value >= 1e6:
        out = f'{value/1e6:,.2f} M€'
    elif value >= 1e3:
        out = f'{value/1e3:,.1f} mil €'
    else:
        out = f'{value:,.2f} €'
    return prefix + out.replace(',', 'X').replace('.', ',').replace('X', '.')

def formatted_percent(before, after):
    if before == 0:
        return '—' if after == 0 else 'Nova base'
    return f'{(after-before)/abs(before)*100:+.1f}%'.replace('.', ',')

def executive_card(label, previous, current, previous_year, current_year, style='normal'):
    diff = current - previous
    direction = ('up' if diff > 0 else 'down' if diff < 0 else 'flat')
    pct = formatted_percent(previous, current)
    label = html_escape(str(label))
    good = 'down' if direction == 'down' else 'up' if direction == 'up' else 'flat'
    st.markdown(f"""<div class='ca-exec-card ca-{html_escape(style)}'>
       <div class='ca-card-label'>{label}</div>
       <div class='ca-year-row'><span>{previous_year}</span><strong>{html_escape(display_compact_cent(previous))}</strong></div>
       <div class='ca-year-row ca-current'><span>{current_year}</span><strong>{html_escape(display_compact_cent(current))}</strong></div>
       <div class='ca-card-diff ca-{good}'><span>{'▲' if diff>0 else '▼' if diff<0 else '●'} {html_escape(display_compact_cent(diff))}</span>
         <b>{html_escape(pct)}</b></div></div>""", unsafe_allow_html=True)

def executive_plot(fig, height=420):
    fig.update_layout(template='plotly_white', height=height,
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font=dict(family='Arial', size=12, color='#263c56'),
        margin=dict(l=12,r=100,t=40,b=42),
        legend=dict(orientation='h',x=0,y=1.16),
        xaxis=dict(showgrid=False,zeroline=False),
        yaxis=dict(showgrid=True,gridcolor='#e7edf4',zeroline=False),
        hoverlabel=dict(bgcolor='#143553',font_color='#ffffff'))
    st.plotly_chart(fig,use_container_width=True,theme=None)

def compare_dimension(fr, dimension, old_year, current_year):
    if fr.empty:
        return pd.DataFrame(columns=[dimension,'Anterior','Atual','Diferença','Variação (%)'])
    source=fr.groupby([dimension,'ano'],dropna=False)['cent'].sum().unstack(fill_value=0)
    for year in [old_year,current_year]:
        if year not in source: source[year]=0
    result=source[[old_year,current_year]].reset_index()
    result.columns=[dimension,'Anterior','Atual']
    result['Diferença']=result['Atual']-result['Anterior']
    result['Variação (%)']=result.apply(lambda r: (100*r['Diferença']/abs(r['Anterior'])) if r['Anterior'] else float('nan'),axis=1)
    return result

def chart_drivers(tab, dim, orientation, caption):
    selected=tab.sort_values('Diferença',ascending=(orientation=='decrease'))
    selected=selected[selected['Diferença'] > 0] if orientation=='increase' else selected[selected['Diferença'] < 0]
    selected=selected.head(10).sort_values('Diferença').copy()
    if selected.empty:
        st.info('Não existem variações deste tipo no âmbito selecionado.');return
    labels=selected[dim].astype(str).apply(lambda x:x if len(x)<=43 else x[:40]+'…')
    fig=go.Figure(go.Bar(y=labels,x=selected['Diferença']/100,orientation='h',
          marker=dict(color='#cf6e56' if orientation=='increase' else '#168a7d',line=dict(width=0)),
          customdata=(selected[['Anterior','Atual','Variação (%)']].assign(Anterior=lambda v:v.Anterior/100,Atual=lambda v:v.Atual/100)).to_numpy(),
          hovertemplate='%{y}<br>Variação: %{x:,.2f} €<br>Anterior: %{customdata[0]:,.2f} €<br>Atual: %{customdata[1]:,.2f} €<extra></extra>'))
    fig.update_layout(xaxis_title='Variação (€)',yaxis_title='',showlegend=False,
                      margin=dict(l=8,r=35,t=12,b=45))
    executive_plot(fig, max(305,55*len(selected)+95))
    st.caption(caption)



def rubric_group_frame(df):
    """Classificação única por conta contabilística sem alterar movimentos."""
    frame=df[['ano','mes','Grupo','Subgrupo','Centro','conta','cent']].copy()
    codes=frame['conta'].map(normalizar_codigo)
    plan=lookup_plano()
    rubrics={c:obter_grupo_e_designacao(c,plan)[0] for c in codes.unique()}
    frame['Rubrica']=codes.map(rubrics)
    return frame


def compare_rubrics(df, previous_year, current_year):
    t=compare_dimension(df,'Rubrica',previous_year,current_year)
    return t.sort_values('Atual',ascending=False)


def rubric_cc_panel(df, groups, previous_year, current_year, key_prefix='exec'):
    st.markdown('### Estrutura de custos por rubrica e grupo de CC')
    st.caption('Distribuição dos gastos contabilizados por grupo de reporte e rubrica SNC-AP. Comparação automática com o homólogo.')
    c1,c2=st.columns([1.25,1])
    with c1:
        selected=st.selectbox('Grupo de centros de custo', ['Total ULSLA']+groups,key=key_prefix+'_rubric_group')
    with c2:
        view=st.radio('Visualização',['Comparação homóloga','Estrutura empilhada','Peso relativo (100%)'],
                      horizontal=False,key=key_prefix+'_rubric_view')
    subset=df if selected=='Total ULSLA' else df.loc[df['Grupo'].eq(selected)]
    if subset.empty:
        st.info('Sem custos no grupo selecionado.');return
    rubrics=rubric_group_frame(subset)
    t=compare_rubrics(rubrics,previous_year,current_year)
    if t.empty:
        st.info('Não existem rubricas neste grupo.');return
    s_old=int(t['Anterior'].sum());s_new=int(t['Atual'].sum())
    columns=st.columns(3)
    columns[0].metric(f'Custos {previous_year}',display_compact_cent(s_old))
    columns[1].metric(f'Custos {current_year}',display_compact_cent(s_new))
    columns[2].metric('Variação de custos',display_compact_cent(s_new-s_old),formatted_percent(s_old,s_new),delta_color='inverse')
    fig=go.Figure()
    labels=t['Rubrica'].tolist()
    vals_old=t['Anterior'].to_numpy(dtype=float)/100
    vals_new=t['Atual'].to_numpy(dtype=float)/100
    if view=='Comparação homóloga':
        for vals,year,color in [(vals_old,previous_year,'#86b5da'),(vals_new,current_year,'#087d9d')]:
            fig.add_bar(y=labels,x=vals,orientation='h',name=str(year),marker_color=color,
                        hovertemplate='%{y}<br>%{x:,.2f} €<extra></extra>')
        fig.update_layout(barmode='group',xaxis_title='Custos (€)',yaxis_title='',
                          yaxis=dict(autorange='reversed',automargin=True))
    else:
        # O empilhamento usa valores monetários; o modo percentual só é representativo
        # quando não existirem rubricas negativas de regularização.
        if view=='Peso relativo (100%)' and (t[['Anterior','Atual']]<0).any().any():
            st.warning('Há rubricas com valor negativo (regularizações). A composição percentual não é adequada; apresenta-se a estrutura em euros.')
            view='Estrutura empilhada'
        if view=='Peso relativo (100%)' and (s_old<=0 or s_new<=0):
            st.warning('Não é possível apresentar percentagens com totais nulos ou negativos. Mostra-se a estrutura em euros.')
            view='Estrutura empilhada'
        for i,r in t.reset_index(drop=True).iterrows():
            a=float(r['Anterior'])/100;b=float(r['Atual'])/100
            yvals=[a,b] if view!='Peso relativo (100%)' else [100*a/(s_old/100),100*b/(s_new/100)]
            fig.add_bar(x=[str(previous_year),str(current_year)],y=yvals,name=r['Rubrica'],
                        customdata=[[a],[b]],hovertemplate='%{fullData.name}<br>%{x}: %{customdata[0]:,.2f} €<extra></extra>')
        fig.update_layout(barmode='relative' if view!='Peso relativo (100%)' else 'stack',
                          yaxis_title='Percentagem (%)' if view=='Peso relativo (100%)' else 'Custos (€)',
                          xaxis_title='',legend=dict(orientation='h',y=-.28,x=0),
                          margin=dict(l=15,r=45,t=55,b=145))
    fig.update_layout(title=f'{selected} · {previous_year} vs {current_year}',
                      height=max(420,95+len(t)*53) if view=='Comparação homóloga' else 570,
                      font=dict(size=12),margin=dict(l=15,r=45,t=65,b=65) if view=='Comparação homóloga' else dict(l=15,r=45,t=55,b=145))
    executive_plot(fig,fig.layout.height)
    t['Peso no grupo (%)']= t['Atual'].apply(lambda x:x/s_new*100 if s_new>0 else float('nan'))
    increase=t.loc[t['Diferença']>0].sort_values('Diferença',ascending=False)
    decrease=t.loc[t['Diferença']<0].sort_values('Diferença')
    left,right=st.columns(2)
    with left:
        st.markdown('**Maiores aumentos por rubrica**')
        if increase.empty:st.info('Sem aumentos de custos.')
        else:
            for _,r in increase.head(3).iterrows():
                st.markdown(f"<div class='ca-rubric-highlight up'><strong>{html_escape(str(r['Rubrica']))}</strong><span>+{html_escape(display_compact_cent(int(r['Diferença'])))} · {html_escape(formatted_percent(int(r['Anterior']),int(r['Atual'])))}</span></div>",unsafe_allow_html=True)
    with right:
        st.markdown('**Maiores reduções por rubrica**')
        if decrease.empty:st.info('Sem reduções de custos.')
        else:
            for _,r in decrease.head(3).iterrows():
                st.markdown(f"<div class='ca-rubric-highlight down'><strong>{html_escape(str(r['Rubrica']))}</strong><span>{html_escape(display_compact_cent(int(r['Diferença'])))} · {html_escape(formatted_percent(int(r['Anterior']),int(r['Atual'])))}</span></div>",unsafe_allow_html=True)
    st.markdown('**Detalhe por rubrica**')
    out=t.rename(columns={'Anterior':f'{previous_year} (€)','Atual':f'{current_year} (€)','Diferença':'Diferença (€)'})
    for col in [f'{previous_year} (€)',f'{current_year} (€)','Diferença (€)']:
        out[col]=out[col].apply(euro)
    for col in ['Variação (%)','Peso no grupo (%)']:
        out[col]=out[col].map(lambda v:f'{v:,.1f}%'.replace('.',',') if pd.notna(v) else '—')
    st.dataframe(out,hide_index=True,use_container_width=True)
    raw=t[['Rubrica','Anterior','Atual','Diferença','Variação (%)','Peso no grupo (%)']].copy()
    for col in ['Anterior','Atual','Diferença']:raw[col]=raw[col]/100
    st.download_button('Exportar estrutura de custos por grupo (CSV)',raw.to_csv(index=False,sep=';').encode('utf-8-sig'),
                       file_name=f'ULSLA_estrutura_rubricas_{selected.replace(" ","_")}_{current_year}.csv',mime='text/csv',key=key_prefix+'_download_rubrics')
    st.caption('Montantes líquidos: débito − crédito. OD e regularizações incluídas. Percentagens negativas ou superiores a 100% podem decorrer de rubricas de sinal contrário.')

def executive_dashboard(cx, available, mapping):
    st.markdown('<div class="ca-section-kicker">INTELIGÊNCIA DE CUSTOS · ULSLA</div>',unsafe_allow_html=True)
    st.markdown('## Sumário executivo da Contabilidade Analítica')
    latest=max(available)
    a,b,c=st.columns([1.3,1.1,1.8])
    with a:
        selected=period_selectbox('Período de referência',sorted(available,reverse=True),
                    format_func=lambda p:pd.Timestamp(p+'-01').strftime('%m/%Y'),key='ca_exec_period')
    with b:
        mode=st.radio('Âmbito', ['Acumulado até ao mês','Só o mês'],horizontal=False,key='ca_exec_mode')
    with c:
        st.markdown('<div class="ca-howto">**Comparação automática**<div>O ano selecionado é comparado com os mesmos meses do ano anterior. Só são apresentados resultados quando ambos os períodos estão completos.</div></div>',unsafe_allow_html=True)
    y, m = map(int,selected.split('-'))
    prev=y-1
    if mode=='Só o mês':
        chosen=[selected]
        comparator=[f'{prev}-{m:02d}']
        caption=f'{m:02d}/{prev} vs {m:02d}/{y}'
    else:
        chosen=[f'{y}-{i:02d}' for i in range(1,m+1)]
        comparator=[f'{prev}-{i:02d}' for i in range(1,m+1)]
        caption=f'Janeiro–{m:02d}/{prev} vs Janeiro–{m:02d}/{y}'
    missing=[p for p in comparator+chosen if p not in available]
    if missing:
        st.warning('Comparação homóloga ainda não disponível: faltam os períodos '+', '.join(missing)+'.')
        st.info('Os meses em falta não são considerados zero. Importa os extratos para concluir a comparação.')
        if selected in available:
            raw=join_map(cost_frame(cx,[selected],mapping['Centro de Custos'].tolist()),mapping)
            if not raw.empty:
                st.metric('Custo do mês selecionado (sem comparação)',euro(int(raw['cent'].sum())))
        return
    ids=mapping['Centro de Custos'].tolist()
    with st.spinner('A calcular indicadores e desvios homólogos...'):
        df=join_map(cost_frame(cx,sorted(set(chosen+comparator)),ids),mapping)
    if df.empty:
        st.info('Não existem movimentos para este período.');return
    old=int(df.loc[df.ano==prev,'cent'].sum())
    new=int(df.loc[df.ano==y,'cent'].sum())
    delta=new-old
    st.markdown(f'<div class="ca-comparison-strip">{html_escape(caption)} · Custos líquidos = débito − crédito · Comparação entre períodos equivalentes</div>',unsafe_allow_html=True)
    hero1,hero2,hero3=st.columns([1.2,1.2,1])
    with hero1:st.metric(f'Custos {prev}',display_compact_cent(old))
    with hero2:st.metric(f'Custos {y}',display_compact_cent(new))
    with hero3:st.metric('Variação homóloga',display_compact_cent(delta),formatted_percent(old,new),delta_color='inverse')
    st.markdown('### Grupos de reporte — evolução homóloga')
    bygroup=compare_dimension(df,'Grupo',prev,y)
    group_order=[g for g in REPORT_GROUPS if g in set(mapping['Grande Grupo'])]
    group_order += sorted(set(mapping['Grande Grupo'])-set(group_order))
    group_map=bygroup.set_index('Grupo')
    for i in range(0,len(group_order),3):
        cols=st.columns(3)
        for j,g in enumerate(group_order[i:i+3]):
            with cols[j]:
                row=group_map.loc[g] if g in group_map.index else None
                executive_card(g, int(row['Anterior']) if row is not None else 0,
                         int(row['Atual']) if row is not None else 0,prev,y)
    rubric_cc_panel(df,group_order,prev,y)
    st.markdown('### O que explica a variação?')
    tab1,tab2,tab3,tab4=st.tabs(['Maiores aumentos','Maiores reduções','Comparação por grupos','Evolução mensal'])
    with tab1:
        level=st.radio('Detalhe dos aumentos',['Subgrupo','Centro','Conta'],horizontal=True,key='ca_increase_dim')
        chart_drivers(compare_dimension(df,level,prev,y),level,'increase',
              'Aumentos absolutos mais relevantes. Valores positivos representam maior custo contabilizado.')
    with tab2:
        level=st.radio('Detalhe das reduções',['Subgrupo','Centro','Conta'],horizontal=True,key='ca_decrease_dim')
        chart_drivers(compare_dimension(df,level,prev,y),level,'decrease',
              'Reduções absolutas mais relevantes. Podem incluir regularizações contabilísticas.')
    with tab3:
        table=bygroup.copy().sort_values('Atual',ascending=False)
        fig=go.Figure()
        for field,name,color in [('Anterior',str(prev),'#91b0ce'),('Atual',str(y),'#176e94')]:
            fig.add_bar(y=table['Grupo'],x=table[field]/100,name=name,orientation='h',marker_color=color,
                        hovertemplate='%{y}: %{x:,.2f} €<extra></extra>')
        fig.update_layout(barmode='group',xaxis_title='Custos (€)',yaxis_title='')
        executive_plot(fig, max(400,len(table)*70+120))
        shown=table.rename(columns={'Anterior':f'{prev} (€)','Atual':f'{y} (€)','Diferença':'Diferença (€)'})
        for column in [f'{prev} (€)',f'{y} (€)','Diferença (€)']:
            shown[column]=shown[column].apply(euro)
        shown['Variação (%)']=shown['Variação (%)'].apply(lambda v:f'{v:+.1f}%'.replace('.',',') if pd.notna(v) else 'n/a')
        st.dataframe(shown,hide_index=True,use_container_width=True)
    with tab4:
        evo=df.groupby(['ano','mes'])['cent'].sum().reset_index()
        months_to_show=list(range(1,m+1)) if mode!='Só o mês' else [m]
        fig=go.Figure()
        for year,color in [(prev,'#9bb4cc'),(y,'#087d90')]:
            z=evo[evo.ano.eq(year)].set_index('mes')['cent'].div(100)
            fig.add_trace(go.Scatter(x=months_to_show,y=[float(z.get(month,0)) for month in months_to_show],
                 mode='lines+markers',name=str(year),line=dict(color=color,width=3),marker=dict(size=9),
                 hovertemplate='Mês %{x}<br>%{y:,.2f} €<extra></extra>'))
        fig.update_layout(xaxis_title='Mês',yaxis_title='Custos (€)')
        executive_plot(fig,410)
        if mode=='Só o mês':st.caption('A seleção mensal apresenta apenas o mês escolhido em ambos os anos.')
    st.markdown('### Análise dirigida por grupo e centro de custo')
    chosen_group=st.selectbox('Grupo a analisar',group_order,key='ca_focus_group')
    sub=df[df['Grupo'].eq(chosen_group)]
    detailed=compare_dimension(sub,'Subgrupo',prev,y).sort_values('Diferença',ascending=False)
    detailed['Variação (%)']=detailed['Variação (%)'].apply(lambda v:f'{v:+.1f}%'.replace('.',',') if pd.notna(v) else 'n/a')
    pretty=detailed.rename(columns={'Anterior':f'{prev} (€)','Atual':f'{y} (€)','Diferença':'Diferença (€)'})
    for col in [f'{prev} (€)',f'{y} (€)','Diferença (€)']:pretty[col]=pretty[col].apply(euro)
    st.dataframe(pretty,hide_index=True,use_container_width=True)
    download_table(pretty,'evolução de subgrupos','executivo_subgrupos')
    st.caption('A classificação dos grupos e subgrupos segue o livro de apoio dos CC. Movimentos de OD e redistribuições permanecem incluídos. Não se confundem custos diretos com custo total após imputações.')



def _comparison_card_v28(title, frame, earlier, later, detail):
    """Valores monetários em cêntimos; indisponibilidade não equivale a zero."""
    st.markdown(f"<div class='ca-v28-kicker'>{html_escape(title)}</div>", unsafe_allow_html=True)
    if frame is None:
        st.markdown("<div class='ca-v28-missing'>Comparação indisponível<div>Faltam meses importados para este âmbito.</div></div>", unsafe_allow_html=True)
        return
    older=int(frame.loc[frame.ano.eq(earlier),'cent'].sum())
    current=int(frame.loc[frame.ano.eq(later),'cent'].sum())
    executive_card(detail,older,current,earlier,later)


def _mapping_with_costs(cx, mapping, periods, account_prefix=''):
    """CC com custo líquido não nulo em pelo menos um mês selecionado."""
    frame=cost_frame(cx,periods,mapping['Centro de Custos'].astype(str).tolist(),account_prefix)
    if frame.empty:
        return mapping.iloc[:0].copy()
    monthly=frame.groupby(['cc','ano','mes'])['cent'].sum()
    active=set(monthly.loc[monthly.ne(0)].index.get_level_values('cc').astype(str))
    return mapping.loc[mapping['Centro de Custos'].astype(str).isin(active)].copy()


def _valid_scope_selection(key, options):
    if key in st.session_state and st.session_state[key] not in options:
        del st.session_state[key]


def _scope_v28(mapping):
    groups=sorted(mapping['Grande Grupo'].dropna().unique().tolist())
    choice=st.radio('Nível de análise', ['Total ULSLA','Grupo de CC','Centro de custo'],horizontal=True,key='v28_scope_level')
    if choice=='Total ULSLA':
        return mapping.copy(),'Total ULSLA',choice
    if choice=='Grupo de CC':
        _valid_scope_selection('v28_group_choice',groups)
        group=st.selectbox('Grupo de CC',groups,key='v28_group_choice')
        return mapping.loc[mapping['Grande Grupo'].eq(group)].copy(),group,choice
    # Apenas centros com custos no âmbito temporal selecionado.
    options=(mapping[['Centro de Custos','Designação','Grande Grupo']]
             .fillna('').drop_duplicates('Centro de Custos').sort_values(['Grande Grupo','Designação']))
    names={str(r['Centro de Custos']):f"{r['Centro de Custos']} — {r['Designação']} · {r['Grande Grupo']}" for _,r in options.iterrows()}
    _valid_scope_selection('v28_cc_choice',list(names))
    cc=st.selectbox('Pesquisar e selecionar centro de custo',list(names),format_func=lambda value:names[value],key='v28_cc_choice')
    return mapping.loc[mapping['Centro de Custos'].eq(cc)].copy(),names[cc],choice


def _breakdown_v28(frame,previous_year,current_year,dimension,title):
    t=compare_dimension(frame,dimension,previous_year,current_year)
    if t.empty:
        st.info('Sem valores para este âmbito.');return
    t=t.sort_values('Atual',ascending=False)
    st.markdown('#### '+title)
    bars=t.head(12).iloc[::-1]
    fig=go.Figure()
    for col,year,color in [('Anterior',previous_year,'#9cbcd4'),('Atual',current_year,'#087e9e')]:
        fig.add_bar(y=bars[dimension].astype(str),x=bars[col]/100,orientation='h',name=str(year),marker_color=color,
                    hovertemplate='%{y}<br>%{x:,.2f} €<extra></extra>')
    fig.update_layout(barmode='group',xaxis_title='Euros',yaxis_title='',margin=dict(l=12,r=30,t=20,b=40),
                      legend=dict(orientation='h',y=1.13))
    executive_plot(fig,max(350,len(bars)*43+135))
    a,b=st.columns(2)
    with a:
        st.markdown('**Maiores aumentos**')
        ups=t.loc[t['Diferença']>0].sort_values('Diferença',ascending=False).head(5)
        if ups.empty:st.info('Sem aumentos.')
        for _,r in ups.iterrows():
            st.markdown(f"<div class='ca-rubric-highlight up'><strong>{html_escape(str(r[dimension]))}</strong><span>+{html_escape(display_compact_cent(int(r['Diferença'])))} · {html_escape(formatted_percent(int(r['Anterior']),int(r['Atual'])))}</span></div>",unsafe_allow_html=True)
    with b:
        st.markdown('**Maiores reduções**')
        downs=t.loc[t['Diferença']<0].sort_values('Diferença').head(5)
        if downs.empty:st.info('Sem reduções.')
        for _,r in downs.iterrows():
            st.markdown(f"<div class='ca-rubric-highlight down'><strong>{html_escape(str(r[dimension]))}</strong><span>{html_escape(display_compact_cent(int(r['Diferença'])))} · {html_escape(formatted_percent(int(r['Anterior']),int(r['Atual'])))}</span></div>",unsafe_allow_html=True)
    readable=t.rename(columns={'Anterior':f'{previous_year} (€)','Atual':f'{current_year} (€)','Diferença':'Variação (€)'})
    st.dataframe(styled_amounts(readable,[f'{previous_year} (€)',f'{current_year} (€)','Variação (€)']),hide_index=True,use_container_width=True)


def _suppliers_v28(cx,periods,scope_ids,scope_description,identifier):
    st.markdown('#### Principais fornecedores — '+identifier)
    st.caption('Excluídos: códigos iniciados por 9963 e 9990000 (vencimentos) e o código 9999999 (Diversos). Os custos excluídos continuam contabilizados nos totais e na reconciliação.')
    if not periods:return
    fr=entidade_frame(cx,periods,scope_ids)
    if fr.empty:
        st.info('Não existem movimentos com esta seleção.');return
    fr['entidade']=fr['entidade'].map(normalizar_codigo)
    fr=fr.loc[fr['entidade'].ne('') & ~fr['entidade'].map(entidade_salarios) & fr['entidade'].ne('9999999')].copy()
    if fr.empty:
        st.warning('Sem movimentos com código de fornecedor elegível no período escolhido.');return
    cat=entidades_catalogo()
    fr=fr.merge(cat,left_on='entidade',right_on='Código',how='left',validate='many_to_one')
    fr['Fornecedor']=fr['entidade']+' — '+fr['Nome'].fillna('Por identificar')
    bad=fr.loc[fr['Nome'].isna(),'entidade'].nunique()
    if bad:st.warning(f'{bad} códigos de fornecedores sem correspondência no cadastro. Verifica a lista de entidades.')
    data=fr.groupby('Fornecedor',as_index=False)['cent'].sum().sort_values('cent',ascending=False)
    pos=data.loc[data['cent']>0].head(15).iloc[::-1]
    if not pos.empty:
        fig=go.Figure(go.Bar(y=pos['Fornecedor'],x=pos['cent']/100,orientation='h',marker_color='#0c8196',
           hovertemplate='%{y}<br>%{x:,.2f} €<extra></extra>'))
        fig.update_layout(xaxis_title='Custo líquido (€)',yaxis_title='',margin=dict(l=12,r=30,t=25,b=40))
        executive_plot(fig,max(370,len(pos)*38+95))
    view=data.rename(columns={'cent':'Valor (€)'})
    view['Valor (€)']=view['Valor (€)']/100
    st.dataframe(styled_amounts(view[['Fornecedor','Valor (€)']]),hide_index=True,use_container_width=True)
    st.download_button('Exportar ranking de fornecedores',view.to_csv(index=False,sep=';').encode('utf-8-sig'),
                       file_name=f'ULSLA_fornecedores_{identifier.replace(" ","_")}.csv',mime='text/csv',key='v28_suppliers_export')


def executive_dashboard_v28(cx,available,mapping):
    st.markdown('<div class="ca-section-kicker">ULSLA / INTELLIGENCE ANALÍTICA</div>',unsafe_allow_html=True)
    st.subheader('Custos diretos · painel executivo')
    if not available:
        st.warning('Importa os extratos contabilísticos para começar.');return
    chosen=period_selectbox('Período de referência',sorted(available,reverse=True),key='v28_period',
                        format_func=__import__('periodos_snc_ap').periodo_legenda)
    yy,mm=map(int,chosen.split('-'))
    scope_periods=[f'{yy}-{i:02d}' for i in range(1,mm+1) if f'{yy}-{i:02d}' in set(available)]
    active_mapping=_mapping_with_costs(cx,mapping,scope_periods)
    if active_mapping.empty:
        st.info('Não existem custos nos centros de movimento entre janeiro e o mês de referência.');return
    scope,label,kind=_scope_v28(active_mapping)
    st.caption('Seleção limitada aos CC com custos entre janeiro e o mês de referência.')
    ids=scope['Centro de Custos'].astype(str).tolist()
    earlier=yy-1
    month_current=[chosen];month_prior=[f'{earlier}-{mm:02d}']
    accumulated_current=[f'{yy}-{i:02d}' for i in range(1,mm+1)]
    accumulated_prior=[f'{earlier}-{i:02d}' for i in range(1,mm+1)]
    available_set=set(available)
    month_ok=all(p in available_set for p in month_current+month_prior)
    accum_ok=all(p in available_set for p in accumulated_current+accumulated_prior)
    missing=sorted(set(month_current+month_prior+accumulated_current+accumulated_prior)-available_set)
    if missing:
        st.warning('Comparação incompleta: falta importar '+', '.join(missing)+'. Os meses em falta não são tratados como zero.')
    need=sorted((set(accumulated_current+accumulated_prior) if accum_ok else set(month_current+month_prior) if month_ok else {chosen}) & available_set)
    if not need:return
    with st.spinner('A apurar os custos por centro, mês e conta SNC-AP...'):
        base=join_map(cost_frame(cx,need,ids),mapping)
    if base.empty:
        st.info('Não existem custos neste âmbito.');return
    monthly=base.loc[base['mes'].eq(mm)] if month_ok else None
    cumulative=base if accum_ok else None
    st.markdown(f'<div class="ca-v28-context">{html_escape(label)} · {mm:02d}/{yy}</div>',unsafe_allow_html=True)
    col1,col2=st.columns(2)
    with col1:_comparison_card_v28('01 / VARIAÇÃO DO MÊS',monthly,earlier,yy,f'{mm:02d} / Comparação homóloga')
    with col2:_comparison_card_v28('02 / VARIAÇÃO ACUMULADA',cumulative,earlier,yy,f'Janeiro–{mm:02d} / Comparação homóloga')
    if month_ok and accum_ok:
        mo=int(monthly.loc[monthly.ano.eq(earlier),'cent'].sum());mn=int(monthly.loc[monthly.ano.eq(yy),'cent'].sum())
        ao=int(cumulative.loc[cumulative.ano.eq(earlier),'cent'].sum());an=int(cumulative.loc[cumulative.ano.eq(yy),'cent'].sum())
        if (mn-mo)*(an-ao)<0:
            st.info('**Sinal de gestão:** a variação do mês tem sentido contrário à variação acumulada. Analisa os desvios por rubrica e por CC.')
    tab_rub,tab_cc,tab_sup,tab_ev,tab_cp=st.tabs(['Estrutura da despesa','Grupos e centros de custo','Principais fornecedores','Evolução mensal','Rendimentos simulados · CP'])
    with tab_cp:
        from rendimentos_cp import render_cp
        render_cp(st,cx,available,mapping,scope,label,chosen,cost_frame,euro,ROOT)
    with tab_rub:
        unit=st.radio('Base da análise',['Mês','Acumulado'],horizontal=True,key='v28_rub_basis')
        fr=monthly if unit=='Mês' else cumulative
        if fr is None:st.info('Comparação indisponível por falta de meses importados.')
        else:
            grouped=enriquecer_contas(fr)
            _breakdown_v28(grouped,earlier,yy,'Rubrica','Custos por grupo de despesa')
            with st.expander('Detalhar as contas SNC-AP'):
                _breakdown_v28(grouped,earlier,yy,'Conta identificada','Contas contabilísticas')
    with tab_cc:
        unit=st.radio('Base da análise',['Mês','Acumulado'],horizontal=True,key='v28_cc_basis')
        fr=monthly if unit=='Mês' else cumulative
        if fr is None:st.info('Comparação indisponível por falta de meses importados.')
        else:
            dimensions=(['Grupo','Subgrupo','Centro'] if kind=='Total ULSLA' else
                        ['Subgrupo','Centro'] if kind=='Grupo de CC' else ['Conta'])
            dim=st.selectbox('Desagregar por',dimensions,key='v28_cc_dim')
            _breakdown_v28(fr,earlier,yy,dim,'Principais variações por '+dim.lower())
    with tab_sup:
        unit=st.radio('Base do ranking',['Mês','Acumulado'],horizontal=True,key='v28_supplier_basis')
        per=month_current if unit=='Mês' else accumulated_current
        if unit=='Acumulado' and not all(p in available_set for p in per):
            st.warning('Não há histórico completo do ano selecionado para calcular o ranking acumulado.')
        else:_suppliers_v28(cx,per,ids,label,chosen+('_mes' if unit=='Mês' else '_acumulado'))
    with tab_ev:
        if not accum_ok:
            st.info('A evolução anual comparável exige todos os meses até ao período selecionado em ambos os anos.')
        else:
            series=base.groupby(['ano','mes'],as_index=False)['cent'].sum()
            fig=go.Figure()
            for year,color in [(earlier,'#91b5d2'),(yy,'#0b819b')]:
                axis=series.loc[series.ano.eq(year)].set_index('mes')['cent']
                fig.add_trace(go.Scatter(x=list(range(1,mm+1)),y=[axis.get(m,0)/100 for m in range(1,mm+1)],
                  name=str(year),mode='lines+markers',line=dict(color=color,width=3),marker=dict(size=8),
                  hovertemplate='Mês %{x}<br>%{y:,.2f} €<extra></extra>'))
            fig.update_layout(xaxis_title='Mês',yaxis_title='Custos (€)',xaxis=dict(dtick=1))
            executive_plot(fig,420)
    with st.expander('Critérios contabilísticos e validações'):
        st.caption('Movimentos da classe 6, centros M do mapa oficial; gastos líquidos = débito − crédito. Operações diversas permanecem incluídas. A lista de fornecedores exclui vencimentos 9963*, 9990000* e Diversos 9999999, mas os custos contabilísticos permanecem inalterados. Os custos diretos não são confundidos com os custos após imputações do reporte oficial.')

st.set_page_config(page_title='ULSLA | Contabilidade Analítica',page_icon='📊',layout='wide')
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap');
.stApp{background:linear-gradient(145deg,#f5f8fc,#eaf1f7);font-family:'DM Sans',sans-serif;color:#19334e}
.block-container{padding-top:1.3rem;max-width:1600px;padding-bottom:4rem}
section[data-testid="stSidebar"]{background:#11273f;color:#edf5fd;border-right:1px solid #24405e}
section[data-testid="stSidebar"] *{color:inherit}
section[data-testid="stSidebar"] input{color:#18334e!important}
h1,h2,h3{letter-spacing:-.035em;color:#173550}
h1{font-size:2rem!important}h2{font-size:1.55rem!important}
[data-testid="stMetric"]{background:#fff;border:1px solid #dbe6f0;border-radius:17px;padding:19px 22px;box-shadow:0 7px 22px #213f5910}
[data-testid="stMetricValue"]{color:#173955;font-size:1.9rem}
[data-testid="stPlotlyChart"],[data-testid="stDataFrame"]{background:#fff;border:1px solid #e3eaf1;border-radius:15px;padding:10px;box-shadow:0 6px 20px #213f5909}
.ca-section-kicker{color:#077b90;letter-spacing:.16em;font-weight:800;font-size:.72rem;margin-bottom:6px}
.ca-comparison-strip{background:#173e5a;color:#edf8fc;border-radius:11px;padding:13px 20px;margin:14px 0 18px;font-weight:600}
.ca-howto{background:#e8f2f6;padding:13px 16px;border:1px solid #d4e8ef;border-radius:12px;color:#224962;font-size:.86rem;margin-top:4px}
.ca-howto div{font-weight:400;margin-top:5px}
.ca-exec-card{background:#fff;border:1px solid #dfe9f1;box-shadow:0 9px 28px #163d5b13;border-radius:17px;padding:20px 21px;min-height:199px;margin:6px 0 12px;position:relative;overflow:hidden}
.ca-exec-card:before{content:'';position:absolute;top:0;left:0;width:5px;height:100%;background:#0b7f95}
.ca-card-label{font-size:.92rem;font-weight:800;color:#173651;min-height:42px;line-height:1.3;margin-bottom:9px}
.ca-year-row{display:flex;align-items:center;justify-content:space-between;color:#71849a;font-size:.88rem;border-bottom:1px solid #edf1f6;padding:6px 0}
.ca-year-row strong{font-size:1.19rem;color:#38536a;font-weight:700}
.ca-year-row.ca-current{color:#0a6883}.ca-year-row.ca-current strong{color:#0a4e6e;font-size:1.37rem}
.ca-card-diff{display:flex;align-items:center;justify-content:space-between;margin-top:12px;font-size:1.05rem;font-weight:800;gap:7px}
.ca-card-diff b{border-radius:8px;padding:5px 8px;font-size:.92rem}
.ca-card-diff.ca-up{color:#ba5342}.ca-card-diff.ca-up b{background:#fff0eb}
.ca-card-diff.ca-down{color:#0a8973}.ca-card-diff.ca-down b{background:#e5f7f1}
.ca-card-diff.ca-flat{color:#78879a}.ca-card-diff.ca-flat b{background:#edf1f5}
.ca-rubric-highlight{background:#fff;border:1px solid #e0e8f0;border-left:4px solid;border-radius:12px;padding:12px 15px;margin:9px 0;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font-size:.88rem}
.ca-rubric-highlight span{font-weight:800;white-space:nowrap}
.ca-rubric-highlight.up{border-left-color:#c75b4b}.ca-rubric-highlight.up span{color:#b94c3c}
.ca-rubric-highlight.down{border-left-color:#168a78}.ca-rubric-highlight.down span{color:#087966}
.ca-v28-kicker{font-weight:800;font-size:.78rem;letter-spacing:.11em;color:#187b90;margin:10px 0 0}
.ca-v28-context{font-size:1.15rem;color:#173c57;font-weight:750;margin:14px 0}
.ca-v28-missing{background:#fff;border:1px solid #dbe5ed;border-radius:14px;padding:23px;font-weight:750;color:#41556a;min-height:170px}
.ca-v28-missing div{font-weight:400;font-size:.86rem;color:#76869a;margin-top:13px}
</style>""",unsafe_allow_html=True)
hero('ULSLA | Contabilidade Analítica', 'Custos diretos, centros de custo e reconciliação contabilística.', 'Análise e controlo · Centros de movimento (M)')
st.caption('ULSLA · Custos diretos · Centros de movimento (M) · Aplicação independente · v'+VERSION)
cx=connect()
mapa=mapa_centros()
periods=periods_available(cx)

with st.sidebar:
    st.header('Análise e controlo')
    modulo=st.radio('Área', ['Painel de custos','Comparar períodos','Explorar detalhe',
              'Rubricas e entidades','Importar extrato','Reconciliação'],label_visibility='collapsed')
    st.divider()
    st.caption(f'{len(mapa)} centros M classificados · {len(periods)} períodos importados')
    st.caption('Custos contabilizados sem novas imputações. As operações OD são mantidas para reconciliação.')

if modulo=='Rubricas e entidades':
    if periods:painel_rubricas_entidades(cx,periods,mapa)
    else:st.warning('Importa primeiro os movimentos analíticos.')

elif modulo=='Importar extrato':
    st.subheader('Importar movimentos analíticos')
    st.info('Cada mês do CSV substitui integralmente o mesmo mês, nunca duplica movimentos. A base do dashboard financeiro não é alterada.')
    file=st.file_uploader('CAEXTMOV (CSV)',type=['csv'])
    if file:
        try:
            with st.spinner('A verificar o ficheiro...'):
                frame,unknown=parse_extrato(file.getvalue())
        except Exception as exc:
            st.error('Extrato inválido: '+str(exc));st.stop()
        summary=frame.groupby(['ano','mes'],as_index=False)[['Débito_cent','Crédito_cent']].sum()
        summary['Gasto (€)']=(summary['Débito_cent']-summary['Crédito_cent'])/100
        st.dataframe(styled_amounts(summary[['ano','mes','Gasto (€)']].rename(columns={'Gasto (€)':'Valor (€)','ano':'Ano','mes':'Mês'})),hide_index=True,use_container_width=True)
        st.write(f'{len(frame):,} movimentos · {frame["C. Custo"].nunique()} centros de custo')
        st.caption('Coluna de entidade reconhecida: '+str(frame.attrs.get('entidade_coluna') or 'não encontrada no extrato'))
        if unknown:st.error('Centros sem correspondência no plano M: '+', '.join(unknown[:30]))
        else:
            if st.button('Guardar movimentos',type='primary'):
                with st.spinner('A gravar os meses selecionados...'):
                    saved=save_import(cx,frame,hashlib.sha256(file.getvalue()).hexdigest(),file.name)
                updated, errors = sincronizar_ba_financeiro(cx)
                st.session_state['ca_message']='Gravação concluída: '+'; '.join(saved) + f'. BA sincronizados: {updated}.'
                if errors: st.warning('; '.join(errors))
                st.rerun()
    if st.session_state.get('ca_message'):
        st.success(st.session_state['ca_message'])
        if st.button('Fechar confirmação'):st.session_state.pop('ca_message',None);st.rerun()

elif modulo=='Reconciliação':
    st.subheader('Validação contra o balancete SNC-AP')
    with st.spinner('A consultar BA já importados no Dashboard Financeiro...'):
        updated, errors = sincronizar_ba_financeiro(cx)
    if updated:st.success(f'{updated} referência(s) BA atualizada(s) a partir do Dashboard Financeiro.')
    for error in errors:st.warning(error)
    st.caption('Os BA são lidos em dados_s3cp_xml, sem nova importação. A aplicação analítica não altera os mapas originais.')
    validation=read_validation(cx)
    if validation.empty:st.warning('Ainda não existem movimentos importados.')
    else:
        a,b,c=st.columns(3)
        a.metric('Períodos validados',int(validation['Estado'].eq('Validado').sum()))
        b.metric('Aguardam BA',int(validation['Estado'].eq('BA em falta').sum()))
        c.metric('Com divergência',int(validation['Estado'].str.contains('Divergência').sum()))
        cols=[v for v in validation.columns if v.endswith('(€)')]
        st.dataframe(styled_amounts(validation,cols),hide_index=True,use_container_width=True)
        download_table(styled_amounts(validation,cols),'reconciliação','reconciliacao')
        st.caption('Só se considera o acumulado validado com todos os meses desde janeiro presentes. A correspondência contabilística não comprova a inexistência de repartições na origem.')

elif not periods:
    st.warning('Ainda não existem movimentos. Abre «Importar extrato» para começar.')

else:
    groups=sorted(mapa['Grande Grupo'].dropna().unique().tolist())
    choices=sorted(periods,reverse=True)
    if modulo=='Painel de custos':
        executive_dashboard_v28(cx,periods,mapa)
    elif modulo=='Comparar períodos':
        st.subheader('Comparar períodos, serviços e contas')
        st.caption('Os períodos A e B podem abranger um ou vários meses. Seleciona os períodos antes de calcular.')
        with st.form('ca_compare_form'):
            c1,c2=st.columns(2)
            with c1:
                st.markdown('**Período A — referência**')
                pa=period_multiselect('Meses A',choices,default=choices[-min(len(choices),3):],key='compA')
            with c2:
                st.markdown('**Período B — comparação**')
                pb=period_multiselect('Meses B',choices,default=choices[:min(len(choices),3)],key='compB')
            group_sel=st.multiselect('Grandes grupos',groups,default=groups,key='cg')
            dim=st.selectbox('Comparar por',['Grande Grupo','Subgrupo','Centro','Conta'],key='cdim')
            prefix=st.text_input('Filtrar contas por prefixo (opcional)',placeholder='Ex.: 62',key='cpref')
            show=st.form_submit_button('Aplicar comparação',type='primary')
        if show:
            st.session_state['ca_comparison']={'a':pa,'b':pb,'groups':group_sel,'dim':dim,'prefix':prefix.strip()}
        opts=st.session_state.get('ca_comparison')
        if opts:
            if not opts['a'] or not opts['b'] or not opts['groups']:
                st.info('Seleciona pelo menos um mês em cada período e um grande grupo.')
            else:
                ids=mapa.loc[mapa['Grande Grupo'].isin(opts['groups']),'Centro de Custos'].tolist()
                allperiods=sorted(set(opts['a']+opts['b']))
                with st.spinner('A calcular a comparação solicitada...'):
                    data=join_map(cost_frame(cx,allperiods,ids,opts['prefix']),mapa)
                if not data.empty:
                    dim=opts['dim']
                    def group_sum(selected):
                        sub=data[data['Periodo'].isin(selected)]
                        return sub.groupby(dim)['cent'].sum().div(100)
                    a=group_sum(opts['a']);b=group_sum(opts['b'])
                    t=pd.concat([a.rename('Período A (€)'),b.rename('Período B (€)')],axis=1).fillna(0).reset_index()
                    t['Diferença (€)']=t['Período B (€)']-t['Período A (€)']
                    t['Variação (%)']=t.apply(lambda r: (r['Diferença (€)']/abs(r['Período A (€)'])*100) if r['Período A (€)'] else float('nan'),axis=1)
                    t=t.sort_values('Diferença (€)',ascending=False)
                    m1,m2,m3=st.columns(3)
                    m1.metric('Período A',euro(round(a.sum()*100)))
                    m2.metric('Período B',euro(round(b.sum()*100)))
                    m3.metric('Diferença B − A',euro(round(t['Diferença (€)'].sum()*100)))
                    st.caption('A: '+', '.join(sorted(opts['a']))+' | B: '+', '.join(sorted(opts['b'])))
                    if set(opts['a']) & set(opts['b']): st.warning('Há meses comuns aos dois conjuntos. Confirma se a sobreposição é intencional.')
                    if len(opts['a'])!=len(opts['b']): st.warning('Os conjuntos têm números diferentes de meses. Compara também médias mensais para evitar conclusões enviesadas.')
                    avg1=a.sum()/len(opts['a']);avg2=b.sum()/len(opts['b'])
                    k1,k2,k3=st.columns(3)
                    k1.metric('Média mensal A',euro(round(avg1*100)))
                    k2.metric('Média mensal B',euro(round(avg2*100)))
                    k3.metric('Variação média mensal',f'{(avg2/abs(avg1)-1)*100:+.1f}%' if avg1 else 'n/a')
                    delta=t.sort_values('Diferença (€)',ascending=False).head(12)
                    fig_delta=px.bar(delta.sort_values('Diferença (€)'),x='Diferença (€)',y=dim,orientation='h',title='Principais aumentos absolutos',color='Diferença (€)',color_continuous_scale='RdBu_r')
                    premium_chart(fig_delta,480)
                    g=t.sort_values('Diferença (€)',key=lambda col:col.abs(),ascending=False).head(18)
                    fig=go.Figure()
                    for name,color in [('Período A (€)','#38a5df'),('Período B (€)','#e3a155')]:
                        fig.add_bar(y=g[dim],x=g[name],name=name,orientation='h',marker_color=color,
                                    hovertemplate='%{y}<br>%{x:,.2f} €<extra></extra>')
                    fig.update_layout(barmode='group',template='plotly_dark',height=max(390,min(850,25*len(g)+160)),
                        paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',yaxis_title='',xaxis_title='Euros',
                        margin=dict(l=10,r=10,t=35,b=10))
                    st.plotly_chart(fig,use_container_width=True,theme=None)
                    view=styled_amounts(t)
                    st.dataframe(view,hide_index=True,use_container_width=True)
                    download_table(view,'comparação','comparacao')
                else:st.info('Sem custos no âmbito da comparação escolhida.')
        else:st.info('Escolhe os períodos e clica «Aplicar comparação».')

    else:
        st.subheader('Painel de custos diretos' if modulo=='Painel de custos' else 'Exploração detalhada de custos')
        with st.form('ca_filters'):
            c1,c2,c3=st.columns(3)
            with c1:
                selected=period_multiselect('Períodos',choices,default=choices[:min(3,len(choices))])
                selected_group=st.multiselect('Grandes grupos',groups,default=groups)
            with c2:
                subs=sorted(mapa.loc[mapa['Grande Grupo'].isin(selected_group),'Subgrupo original'].dropna().unique().tolist())
                selected_sub=st.multiselect('Subgrupos (opcional)',subs)
                prefix=st.text_input('Conta começa por (opcional)',placeholder='Ex.: 62')
            with c3:
                filtered=mapa[mapa['Grande Grupo'].isin(selected_group)]
                if selected_sub:filtered=filtered[filtered['Subgrupo original'].isin(selected_sub)]
                options=dict(zip(filtered['Centro de Custos'],filtered['Centro de Custos']+' — '+filtered['Designação']))
                centers=st.multiselect('Centros M (opcional)',list(options),format_func=lambda x:options[x])
            go=st.form_submit_button('Aplicar filtros',type='primary')
        if go:
            st.session_state['ca_view']={'periods':selected,'groups':selected_group,'subs':selected_sub,'centers':centers,'prefix':prefix.strip()}
        opts=st.session_state.get('ca_view')
        if not opts:st.info('Seleciona os filtros e clica «Aplicar filtros».')
        else:
            filt=mapa[mapa['Grande Grupo'].isin(opts['groups'])]
            if opts['subs']:filt=filt[filt['Subgrupo original'].isin(opts['subs'])]
            if opts['centers']:filt=filt[filt['Centro de Custos'].isin(opts['centers'])]
            with st.spinner('A consultar apenas os movimentos selecionados...'):
                frame=join_map(cost_frame(cx,opts['periods'],filt['Centro de Custos'].tolist(),opts['prefix']),mapa)
            if frame.empty:st.info('Sem movimentos para os filtros aplicados.')
            else:
                total=money_summary(frame)
                m1,m2,m3,m4=st.columns(4)
                m1.metric('Custo líquido da seleção',euro(total))
                m2.metric('Centros com movimentos',frame['cc'].nunique())
                m3.metric('Contas de gasto',frame['conta'].nunique())
                m4.metric('Movimentos contabilísticos',f'{int(frame["movimentos"].sum()):,}'.replace(',','.'))
                bygroup=frame.groupby('Grupo',as_index=False)['cent'].sum();bygroup['Valor (€)']=bygroup['cent']/100
                evolution=frame.groupby('Periodo',as_index=False)['cent'].sum().sort_values('Periodo');evolution['Valor (€)']=evolution['cent']/100
                if modulo=='Painel de custos':
                    l,r=st.columns([1,1.15])
                    with l:
                        fig=px.pie(bygroup,names='Grupo',values='Valor (€)',hole=.62,
                            color_discrete_sequence=['#238ac5','#29a788','#e5aa5b','#8e9cb3'])
                        fig.update_layout(title='Distribuição por grande grupo',template='plotly_dark',height=410,
                            paper_bgcolor='rgba(0,0,0,0)',margin=dict(l=10,r=10,t=65,b=10))
                        fig.update_traces(hovertemplate='%{label}: %{value:,.2f} €<br>%{percent}<extra></extra>')
                        st.plotly_chart(fig,use_container_width=True,theme=None)
                    with r:
                        fig=px.line(evolution,x='Periodo',y='Valor (€)',markers=True,title='Evolução por mês',
                            color_discrete_sequence=['#39a5dd'])
                        fig.update_layout(template='plotly_dark',height=410,paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)',margin=dict(l=10,r=10,t=65,b=10),yaxis_title='Euros',xaxis_title='')
                        fig.update_traces(hovertemplate='%{x}: %{y:,.2f} €<extra></extra>')
                        st.plotly_chart(fig,use_container_width=True,theme=None)
                    chart_bar(frame.groupby('Subgrupo',as_index=False)['cent'].sum().assign(**{'Valor (€)':lambda x:x.cent/100}),
                        'Subgrupo','Valor (€)','Subgrupos com maior custo')
                dim=st.radio('Pormenor', ['Grande Grupo','Subgrupo','Centro','Conta','Periodo'],horizontal=True,
                             key='ca_breakdown_'+modulo)
                agg=frame.groupby(dim,as_index=False).agg(cent=('cent','sum'),movimentos=('movimentos','sum'))
                agg['Valor (€)']=agg['cent']/100
                agg=agg.sort_values('Valor (€)',ascending=False)
                if modulo=='Explorar detalhe':chart_bar(agg,dim,'Valor (€)','Custos por '+dim.lower())
                view=styled_amounts(agg[[dim,'Valor (€)','movimentos']].rename(columns={'movimentos':'Movimentos'}))
                st.dataframe(view,hide_index=True,use_container_width=True)
                download_table(view,'custos diretos', 'custos_'+dim.replace(' ','_').lower())
                st.caption('Montantes líquidos (débito − crédito). Sem imputações adicionais. Operações diversas da origem podem incluir redistribuições.')

cx.close()

