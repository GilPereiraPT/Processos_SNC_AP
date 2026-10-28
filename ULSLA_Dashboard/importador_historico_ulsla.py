"""Ferramenta extraordinaria de carga historica XML SNC-AP ULSLA.
Executa isoladamente do dashboard na porta 8503.
"""
from __future__ import annotations
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import tempfile
import zipfile
from collections import Counter
from datetime import date, datetime
import xml.etree.ElementTree as ET
import pandas as pd
import streamlit as st
from ulsla_branding import period_selectbox
from ulsla_branding import hero
from importador_s3cp_xml import inspect, catalog, save, TIPOS

ROOT = Path(__file__).resolve().parent
KINDS = ['BA','DR','BLC','DFC','DOREC','DODES','AFT','AI','DAPL']
TARGET = ['BA','DOREC','DODES','AFT','AI','DAPL']
SUPPORTED = set(KINDS)
BATCH_OPTIONS = {'Todos os meses disponíveis':'all','Um mês':'month','Um trimestre':'quarter','Um ano':'year'}
SPECIAL = {'DR','BLC','DFC'}
MAX_SIZE = 75 * 1024 * 1024
SOURCE_ROOT = r'U:\CCM a Importar'
st.set_page_config(page_title='ULSLA | Carga historica XML',page_icon='📚',layout='wide')
st.markdown('''<style>
.stApp {background:#f4f7fb;color:#203049} .block-container {padding-top:1.5rem}
h1,h2,h3{color:#173b54} [data-testid="stMetric"] {border:1px solid #dce8ee;border-radius:12px;padding:14px;background:white}
</style>''',unsafe_allow_html=True)


def norm(period):
    y,m=period.split('-');return f'{y}-{min(int(m),12):02d}'


def original_priority(p):
    return int(p.split('-')[1])


def sources_from_directory(folder):
    p=Path(folder).expanduser().resolve()
    if not p.is_dir(): raise ValueError('A pasta indicada não existe.')
    # Não seguir links, evitando percorrer outras unidades inadvertidamente.
    for f in sorted(p.rglob('*')):
        if f.is_symlink() or not f.is_file():continue
        if f.suffix.lower()=='.xml':
            if f.stat().st_size > MAX_SIZE:
                yield str(f),None,'XML superior a 75 MB';continue
            try:yield str(f),f.read_bytes(),None
            except Exception as e:yield str(f),None,str(e)
        elif f.suffix.lower()=='.zip':
            yield from sources_from_zip(f.read_bytes(),str(f))


def sources_from_zip(blob,filename):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for member in z.infolist():
            if member.is_dir() or not member.filename.lower().endswith('.xml'):continue
            name=f'{filename} :: {member.filename}'
            if member.file_size > MAX_SIZE or member.compress_size and member.file_size/max(member.compress_size,1)>250:
                yield name,None,'XML demasiado grande/compressão suspeita';continue
            try:yield name,z.read(member),None
            except Exception as e:yield name,None,str(e)


def xml_sources(folder,uploads,automatic=False):
    if automatic:
        location = Path(SOURCE_ROOT)
        if not location.is_dir():
            yield str(location),None,'Pasta U: indisponível. Verifica se a unidade de rede está ligada.'
        else:
            yield from sources_from_directory(str(location))
    elif folder:
        yield from sources_from_directory(folder)
    for upload in uploads or []:
        if upload.name.lower().endswith('.zip'):
            yield from sources_from_zip(upload.getvalue(),upload.name)
        else:
            yield upload.name,upload.getvalue(),None


def pdf_exists():
    """Verifica apenas registos explicitamente identificados como PDF no historico.
    Nao assume que a ausencia de XML equivale a ausencia de PDF.
    """
    out=set()
    for candidate in [ROOT/'dados_mensais.json',ROOT/'seed_2026_09.json',ROOT/'historico.json',ROOT/'data'/'historico.json',ROOT/'dados'/'historico.json']:
        if not candidate.is_file():continue
        try:
            data=json.loads(candidate.read_text(encoding='utf-8'))
            if isinstance(data,dict) and 'periodo' in data:
                data={str(data['periodo']):data}
            for per, info in data.items():
                if not re.fullmatch(r'\d{4}-\d{2}',per) or not isinstance(info,dict):continue
                for group,kind in [('dr','DR'),('balanco','BLC'),('dfc','DFC'),('balancete','BA')]:
                    if isinstance(info.get(group),dict) and info[group]:out.add((norm(per),kind))
                for doc in info.get('documentos') or []:
                    name=str(doc.get('tipo','')).strip().lower()
                    kind={'balancete':'BA','balanco':'BLC','dr':'DR','dfc':'DFC'}.get(name)
                    if kind:out.add((norm(per),kind))
        except Exception:continue
    return out


def inventory():
    raw=catalog(ROOT)
    present={}
    for (period,kind),meta in raw.items():
        key=(norm(period),kind)
        old=present.get(key)
        if old is None or original_priority(period)>original_priority(old[0]): present[key]=(period,meta)
    return present


def matrix(existing, staged=None, until=None):
    staged=staged or {}
    end=until or pd.Period(date.today().strftime('%Y-%m'),freq='M')
    out=[]
    pdf=pdf_exists()
    for p in pd.period_range('2024-01',end,freq='M'):
        row={'Mês':str(p)}
        for kind in KINDS:
            key=(str(p),kind)
            if key in existing:status='XML'
            elif key in pdf:status='PDF'
            elif key in staged:status='Preparado'
            else:status='Em falta'
            row[kind]=status
        row['Por carregar']=sum(row[k]=='Em falta' for k in TARGET)
        out.append(row)
    return pd.DataFrame(out)


def source_version(blob, filename):
    """Distingue versoes pelo Data do cabecalho; em empate usa mtime, depois nome."""
    issued = ''
    try:
        for _, elem in ET.iterparse(io.BytesIO(blob), events=('end',)):
            if elem.tag.rsplit('}', 1)[-1] == 'Cabecalho':
                for c in elem:
                    if c.tag.rsplit('}', 1)[-1] == 'Data':
                        issued = (c.text or '').strip()
                break
    except Exception:
        pass
    mtime = 0.0
    try:
        if ' :: ' not in filename:
            mtime = Path(filename).stat().st_mtime
    except OSError:
        pass
    return (issued, mtime, filename.casefold())


def batch_months(mode, year, month, quarter, existing_months):
    if mode == 'all':
        return set(existing_months)
    if mode == 'year':
        return {p for p in existing_months if p.startswith(f'{year}-')}
    if mode == 'quarter':
        lo = (quarter-1)*3+1
        return {f'{year}-{i:02d}' for i in range(lo,lo+3)}
    return {f'{year}-{month:02d}'}


def preview_import(folder,uploads,automatic=False):
    valid=[];errors=[];observed=0;ignored=Counter()
    for filename,blob,error in xml_sources(folder,uploads,automatic):
        observed+=1
        if error:
            errors.append(f'{filename}: {error}')
            continue
        # Tipo determinado pela raiz XML, nao pelo nome (prefixos numericos variaveis).
        try:
            root_tag = next(ET.iterparse(io.BytesIO(blob),events=('start',)))[1].tag.rsplit('}',1)[-1]
        except Exception as exc:
            errors.append(f'{filename}: XML invalido: {exc}')
            continue
        if root_tag not in SUPPORTED:
            ignored[root_tag]+=1
            continue
        try:
            parsed=inspect(blob,filename)
            if parsed['entidade']!='510445152':
                ignored['outra entidade']+=1
                continue
            old=parsed['periodo']
            if int(old[:4])<2024:
                ignored['anterior a 2024']+=1
                continue
            parsed['periodo_original']=old
            parsed['periodo']=norm(old)
            parsed['_versao']=source_version(blob,filename)
            valid.append(parsed)
        except Exception as exc:
            errors.append(f'{filename}: {exc}')
    grouped={}
    for obj in valid:
        grouped.setdefault((obj['periodo'],obj['tipo']),[]).append(obj)
    selected={};duplicates=[]
    for key,values in grouped.items():
        winner=max(values,key=lambda v:(original_priority(v['periodo_original']),v['_versao']))
        selected[key]=winner
        duplicates.extend(x['ficheiro'] for x in values if x is not winner)
    return {'selected':selected,'errors':errors,'duplicates':duplicates,
            'ignored':dict(ignored),'conflicts':[], 'files':observed}


def table_status(selected, existing):
    rows=[]
    for (period,kind),obj in sorted(selected.items()):
        old=existing.get((period,kind))
        if old and old[1].get('hash')==obj['hash']:
            status='Já existe (idêntico)'
        elif old and original_priority(old[0])>original_priority(obj['periodo_original']): status='Já existe (fecho superior)'
        elif old:status='Já existe (diferente)'
        else:status='Novo'
        rows.append({'Mês':period,'Mapa':kind,'Período de origem':obj['periodo_original'],
                     'Ficheiro':obj['ficheiro'],'Versão XML':obj.get('_versao',('',0,''))[0], 'Estado':status})
    return pd.DataFrame(rows)

hero('ULSLA | Importação de Dados', 'Carga histórica e controlo dos ficheiros XML SNC-AP.', 'Dados financeiros, orçamentais e patrimoniais')
st.caption('Utilitário extraordinário para carregar os XML SNC-AP de 2024 em diante. Não é executado no arranque do Dashboard Financeiro.')
st.info('Os DR, BLC e DFC já importados por PDF não precisam de ser reenviados. O inventário assinala PDF apenas quando consegue identificar o respetivo registo histórico.')
left,right=st.columns([2,1])
with left:
    with st.form('preparar',clear_on_submit=False):
        automatic=st.checkbox('Pesquisar automaticamente U:\\CCM a Importar (inclui subpastas)',value=True)
        st.caption(f'Origem: {SOURCE_ROOT} (pesquisa recursiva em todas as subpastas)')
        folder=st.text_input('Outra pasta local com XML históricos (inclui subpastas e ZIP)',value='',disabled=automatic)
        uploads=st.file_uploader('Alternativa: escolher um ou mais ZIP/XML',type=['zip','xml'],accept_multiple_files=True,disabled=automatic)
        scan=st.form_submit_button('Analisar pastas e preparar importação',type='primary')
with right:
    st.markdown('**Regras de segurança**')
    st.caption('Não altera PDFs nem o histórico financeiro. Importa por mapa e mês, preserva o original em cópia de segurança quando autorizado a substituir.')
    st.caption('Dezembro incluído: períodos 12, 13 e 14 convergem para AAAA-12. Outros tipos XML são ignorados, sem erro.')

if scan:
    if not automatic and not folder and not uploads:st.warning('Indica uma pasta ou seleciona ficheiros.')
    else:
        with st.spinner('A analisar XML e verificar os períodos...'):
            try:st.session_state['historico_preparado']=preview_import(folder,uploads,automatic)
            except Exception as e:st.error(f'Não foi possível ler a origem: {e}')

existing=inventory()
prepared=st.session_state.get('historico_preparado')
if prepared:
    selected=prepared['selected']
    df=table_status(selected,existing)
    st.subheader('Âmbito do lote a gravar')
    mode_label=st.radio('Selecionar lote',list(BATCH_OPTIONS),horizontal=True,key='historico_batch_mode')
    mode=BATCH_OPTIONS[mode_label]
    years=sorted({int(k[0][:4]) for k in selected} or {date.today().year})
    ca,cb,cc=st.columns(3)
    with ca: byear=period_selectbox('Ano',years,index=len(years)-1,key='historico_batch_year',disabled=mode=='all')
    with cb: bquarter=period_selectbox('Trimestre',[1,2,3,4],key='historico_batch_quarter',disabled=mode!='quarter')
    with cc: bmonth=period_selectbox('Mês',list(range(1,13)),format_func=lambda m:f'{m:02d}',key='historico_batch_month',disabled=mode!='month')
    allowed=batch_months(mode,byear,bmonth,bquarter,{p for p,_ in selected})
    batch_selected={k:v for k,v in selected.items() if k[0] in allowed}
    df_batch=table_status(batch_selected,existing)
    st.caption(f'Lote selecionado: {len(batch_selected)} mapa(s) de {len(allowed)} período(s). A gravação é independente dos restantes lotes.')
    nnovos=int((df_batch['Estado']=='Novo').sum()) if not df_batch.empty else 0
    nrepetidos=int((df_batch['Estado']=='Já existe (idêntico)').sum()) if not df.empty else 0
    ndif=int((df_batch['Estado']=='Já existe (diferente)').sum()) if not df.empty else 0
    a,b,c,d=st.columns(4)
    a.metric('Ficheiros analisados',prepared['files']);b.metric('Mapas novos',nnovos)
    c.metric('Já existentes',nrepetidos);d.metric('Diferentes',ndif)
    st.subheader('Pré-visualização da importação')
    st.dataframe(df_batch,use_container_width=True,hide_index=True,height=310)
    if prepared['duplicates']:
        st.info(f"{len(prepared['duplicates'])} versão(ões) anterior(es) ignorada(s). Foi selecionada a mais recente por Data do cabeçalho XML, depois data de modificação.")
    if prepared['ignored']:
        st.info('Tipos fora dos nove mapas: '+', '.join(f'{k}: {v}' for k,v in sorted(prepared['ignored'].items()))+' — ignorados, não são erros.')
    if prepared['errors']:
        with st.expander(f"{len(prepared['errors'])} ficheiro(s) com erros"):
            for v in prepared['errors'][:100]:st.error(v)
    replace=st.checkbox('Autorizar substituição de mapas diferentes já guardados, com cópia de segurança',value=False)
    confirm=st.checkbox('Confirmo a importação histórica para a base do Dashboard Financeiro',value=False)
    if st.button('Gravar lote selecionado',disabled=not confirm or not batch_selected,type='primary'):
        saved=skipped=failed=0;messages=[]
        progress=st.progress(0)
        for idx,(key,obj) in enumerate(sorted(batch_selected.items())):
            old=existing.get(key)
            try:
                if old and old[1]['hash']==obj['hash']:
                    skipped+=1
                elif old and original_priority(old[0])>original_priority(obj['periodo_original']):
                    skipped+=1;messages.append(f'{key[0]} {key[1]}: mantido o período contabilístico superior já guardado')
                elif old and not replace:
                    skipped+=1;messages.append(f'{key[0]} {key[1]}: existente diferente; não substituído')
                else:
                    # Se já existir um período legado 13/14, o novo 12 fica escrito
                    # sem eliminar o ficheiro legado; a prioridade fica registada.
                    payload={k:v for k,v in obj.items() if not k.startswith('_')}
                    save(ROOT,payload,replace=bool(old and (ROOT/'dados_s3cp_xml'/obj['periodo']/(obj['tipo']+'.json.gz')).exists()))
                    saved+=1
            except Exception as e:
                failed+=1;messages.append(f'{key[0]} {key[1]}: {e}')
            progress.progress((idx+1)/max(len(batch_selected),1))
        st.session_state['historico_ultimo_resultado']={'guardados':saved,'ignorados':skipped,'erros':failed,'detalhes':messages,'hora':datetime.now().strftime('%d/%m/%Y %H:%M')}
        # Mantem a analise para permitir gravar os restantes lotes sem nova pesquisa.
        st.rerun()

if 'historico_ultimo_resultado' in st.session_state:
    item=st.session_state['historico_ultimo_resultado']
    st.success(f"Gravação concluída ({item['hora']}): {item['guardados']} mapas guardados; {item['ignorados']} ignorados; {item['erros']} erros.")
    if item['detalhes']:
        with st.expander('Observações de importação'):
            for line in item['detalhes']:st.write(line)

st.divider()
st.subheader('Mapas recebidos e em falta desde janeiro de 2024')
current=date.today();years=list(range(2024,current.year+1))
year=period_selectbox('Exercício a consultar',years,index=len(years)-1)
end=pd.Period(f'{current.year}-{current.month:02d}',freq='M')
m=matrix(existing,prepared['selected'] if prepared else {},until=end)
view=m[m['Mês'].str.startswith(str(year))].copy()
view['Mês']=view['Mês'].str[-2:]+'/'+view['Mês'].str[:4]
st.dataframe(view,use_container_width=True,hide_index=True,height=480)
st.caption('Preparado = presente na seleção mas ainda não gravado. Em falta = não localizado em XML ou no registo PDF detetável. Dezembro inclui os períodos contabilísticos 12, 13 e 14, sem duplicação do mês.')
st.download_button('Descarregar lista completa de faltas (CSV)',m.to_csv(index=False,sep=';').encode('utf-8-sig'),file_name='ULSLA_controlo_mapas_desde_2024.csv',mime='text/csv')
missing=m[['Mês']+TARGET].melt('Mês',var_name='Mapa',value_name='Estado')
missing=missing[missing.Estado=='Em falta'][['Mês','Mapa']]
st.download_button('Descarregar apenas mapas em falta (CSV)',missing.to_csv(index=False,sep=';').encode('utf-8-sig'),file_name='ULSLA_mapas_em_falta_desde_2024.csv',mime='text/csv')


st.divider()
with st.expander('Verificação de dados de todos os módulos',expanded=False):
    if st.checkbox('Abrir inventário completo',key='historico_abrir_global'):
        from verificacao_dados import render as render_verificacao
        render_verificacao(ROOT,key='historico_verificacao')
