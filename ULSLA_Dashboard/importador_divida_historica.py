"""Carga extraordinária de Dívidas, Créditos e Pagamentos ULSLA, com dezembro."""
from __future__ import annotations
from collections import Counter
from datetime import datetime
from pathlib import Path
import hashlib
import json
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
import pandas as pd
import streamlit as st
from ulsla_branding import period_selectbox
from ulsla_branding import hero

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from divida_xml import parse_xml, write_snapshot, snapshots, load_snapshot

SOURCE = Path(r'U:\CCM a Importar')
KINDS = ('Dividas', 'Pagamentos', 'Creditos')
YEARS = (2024, 2025, 2026)
st.set_page_config(page_title='ULSLA | Histórico Dívidas', page_icon='📁', layout='wide')
hero('ULSLA | Histórico de Dívida', 'Importação de dívidas, pagamentos e créditos.', 'Histórico mensal · XML')
st.caption('Ferramenta extraordinária, independente do dashboard. Pesquisa recursiva em U:\\CCM a Importar, incluindo dezembro (períodos 12/13/14).')


def norm_kind(text):
    return {'dividas':'Dividas', 'pagamentos':'Pagamentos', 'creditos':'Creditos'}.get(text.casefold())


def discover():
    found=[]; problems=[]; ignored=Counter()
    if not SOURCE.is_dir():
        problems.append(f'Pasta não disponível: {SOURCE}')
        return {}, problems, dict(ignored), 0
    # A estrutura da pasta U: pode conter anos, meses ou ficheiros misturados.
    for p in SOURCE.rglob('*'):
        if not p.is_file() or p.is_symlink() or p.suffix.casefold() != '.xml':
            continue
        kind = norm_kind(p.stem)
        if kind is None:
            ignored['Outros ficheiros XML'] += 1
            continue
        try:
            s = p.stat()
            if s.st_size > 120*1024*1024:
                problems.append(f'{p}: XML superior a 120 MB'); continue
            root = ET.parse(p).getroot()
            actual = root.tag.rsplit('}', 1)[-1]
            if actual != kind:
                problems.append(f'{p}: nome {kind}, conteúdo {actual}'); continue
            cab = root.find('Cabecalho')
            ent = cab.findtext('./Entidade/Codigo') if cab is not None else None
            sy = cab.findtext('./Periodo/Ano') if cab is not None else None
            sm = cab.findtext('./Periodo/NumeroMes') if cab is not None else None
            if ent != '2069':
                problems.append(f'{p}: entidade {ent}, esperado 2069'); continue
            y, original_month = int(sy), int(sm)
            if y not in YEARS:
                ignored['Fora dos exercícios 2024–2026'] += 1; continue
            if not 1 <= original_month <= 14:
                problems.append(f'{p}: período inválido {original_month}'); continue
            m = min(original_month, 12)
            period=f'{y}-{m:02d}'
            timestamp = None
            if cab is not None:
                for tag in ('Data','DataGeracao','DataExtracao','DataCriacao'):
                    value = cab.findtext(tag)
                    if value:
                        try: timestamp = datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
                        except (ValueError,OverflowError): pass
                        if timestamp is not None: break
            found.append({'Periodo':period,'PeriodoContabilistico':original_month,'Mapa':kind,'Ficheiro':str(p),
                          'Alterado':s.st_mtime,'Versao':timestamp if timestamp is not None else s.st_mtime,
                          'OrigemVersao':'Cabeçalho XML' if timestamp is not None else 'Modificação do ficheiro',
                          'Tamanho':s.st_size})
        except Exception as exc:
            problems.append(f'{p}: {exc}')
    groups={}
    for x in found:
        key=(x['Periodo'],x['Mapa'])
        if key not in groups or (x['PeriodoContabilistico'],x['Versao'],x['Alterado'],x['Ficheiro'].casefold()) > (groups[key]['PeriodoContabilistico'],groups[key]['Versao'],groups[key]['Alterado'],groups[key]['Ficheiro'].casefold()):
            groups[key]=x
    return groups,problems,dict(ignored),len(found)


def inventory():
    """Determina a existência por ficheiro, sem confiar só no resumo.json."""
    rows=[]
    for year in YEARS:
        for month in range(1,13):
            period=f'{year}-{month:02d}'
            for kind in KINDS:
                present = (BASE/'dados_xml'/period/(kind+'.json.gz')).is_file()
                rows.append({'Período':period,'Mapa':kind,'Estado':'Guardado' if present else 'Em falta'})
    return pd.DataFrame(rows)


def backup_period(period):
    folder=BASE/'dados_xml'/period
    if not folder.exists():return None
    backup=BASE/'dados_xml_backups'/f'{period}_{datetime.now():%Y%m%d_%H%M%S_%f}'
    backup.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(folder,backup)
    return backup


def save_one(item,replace):
    kind,period,df=parse_xml(item['Ficheiro'])
    if (period[:5] + f'{min(int(period[5:]),12):02d}')!=item['Periodo'] or kind!=item['Mapa']:
        raise ValueError('O conteúdo mudou desde a análise. Reanalisa as pastas.')
    normalized_period=item['Periodo']
    existing={k:load_snapshot(BASE,normalized_period,k) for k in KINDS if (BASE/'dados_xml'/normalized_period/(k+'.json.gz')).is_file()}
    if kind in existing and not replace:return 'Ignorado: mapa existente'
    if existing:backup_period(normalized_period)
    existing[kind]=df
    write_snapshot(BASE,normalized_period,existing,replace=True)
    return 'Gravado'


with st.form('scan'):
    st.code(str(SOURCE) + '\\...')
    submitted=st.form_submit_button('Pesquisar ficheiros e verificar faltas',type='primary')
if submitted:
    with st.spinner('A pesquisar nas pastas de rede...'):
        st.session_state['divida_scan'] = discover()

prepared=st.session_state.get('divida_scan')
current=inventory()
if prepared:
    selected,problems,ignored,scanned=prepared
    st.success(f'Pesquisa concluída: {scanned} ficheiros elegíveis identificados; {len(selected)} mapas únicos após seleção da versão mais recente.')
    if ignored:st.info('Ignorados: '+', '.join(f'{k}: {v}' for k,v in ignored.items()))
    if problems:
        with st.expander(f'{len(problems)} avisos de leitura'):
            st.text('\n'.join(problems[:300]))
    choices=['Um mês','Um trimestre','Um ano','Todos os períodos']
    st.subheader('Escolher lote')
    # Os filtros ficam FORA do formulário para recalcular o lote em cada alteração.
    mode=st.radio('Âmbito',choices,horizontal=True,key='divida_scope_v13')
    col1,col2,col3=st.columns(3)
    year=period_selectbox('Ano',YEARS,key='divida_year_v13', target=col1)
    quarter=period_selectbox('Trimestre',[1,2,3,4],disabled=mode!='Um trimestre',key='divida_quarter_v13', target=col2)
    month=period_selectbox('Mês',range(1,13),format_func=lambda x:f'{x:02d}',disabled=mode!='Um mês',key='divida_month_v13', target=col3)
    if mode=='Um mês': allowed={f'{year}-{month:02d}'}
    elif mode=='Um trimestre': allowed={f'{year}-{m:02d}' for m in range((quarter-1)*3+1,quarter*3+1)}
    elif mode=='Um ano': allowed={f'{year}-{m:02d}' for m in range(1,13)}
    else: allowed={k[0] for k in selected}
    chosen=[dict(v) for (p,k),v in sorted(selected.items()) if p in allowed]
    for x in chosen:
        x['Estado']=('Já guardado' if (BASE/'dados_xml'/x['Periodo']/(x['Mapa']+'.json.gz')).exists() else 'Por importar')
    pending=sum(1 for x in chosen if x['Estado']=='Por importar')
    existing_count=len(chosen)-pending
    st.info(f'Lote selecionado: {len(chosen)} mapa(s) — {pending} por importar e {existing_count} já guardado(s).')
    if chosen:
        st.dataframe(pd.DataFrame(chosen)[['Periodo','PeriodoContabilistico','Mapa','Estado','Ficheiro','OrigemVersao']],hide_index=True,use_container_width=True,height=270)
    else:
        st.warning('Não existem ficheiros elegíveis neste lote. Seleciona outro mês/trimestre/ano ou repete a pesquisa.')
    # Confirmações reativas, sem formulário: o botão responde imediatamente.
    replace=st.checkbox('Substituir mapas existentes (com cópia de segurança)',value=False,key='divida_replace_v13')
    confirm=st.checkbox('Confirmo a gravação do lote selecionado',value=False,key='divida_confirm_v13')
    to_process=[x for x in chosen if replace or x['Estado']=='Por importar']
    if chosen and not to_process:
        st.info('Todos os mapas deste lote já estão guardados. Para os substituir, ativa a opção de substituição.')
    do_save=st.button('Gravar lote selecionado',disabled=not chosen,type='primary',key='divida_save_v13')
    if do_save and not to_process:
        st.warning('Não há mapas novos neste lote. Para voltar a gravar os existentes, assinala «Substituir mapas existentes».')
    elif do_save and not confirm:
        st.error('Assinala primeiro «Confirmo a gravação do lote selecionado» e volta a clicar em «Gravar lote selecionado».')
    if do_save and confirm and to_process:
        saved=skipped=failed=0;issues=[]
        bar=st.progress(0)
        for i,item in enumerate(to_process):
            try:
                result=save_one(item,replace)
                if result=='Gravado':saved+=1
                else:skipped+=1
            except Exception as exc:
                failed+=1;issues.append(f"{item['Periodo']} {item['Mapa']}: {exc}")
            bar.progress((i+1)/len(to_process))
        st.session_state['divida_feedback']=(saved,skipped,failed,issues,datetime.now().strftime('%d/%m/%Y %H:%M'))
        st.rerun()

if 'divida_feedback' in st.session_state:
    saved,skipped,failed,issues,when=st.session_state['divida_feedback']
    st.success(f'Gravação concluída em {when}: {saved} mapas guardados, {skipped} já existentes ignorados, {failed} erros.')
    if issues:
        with st.expander('Erros da gravação'):
            st.text('\n'.join(issues))
    if st.button('Fechar confirmação'):del st.session_state['divida_feedback'];st.rerun()

st.divider()
st.subheader('Situação por mês — janeiro de 2024 a dezembro de 2026')
status=inventory()
if prepared:
    available=prepared[0]
    status['Localizado na rede']=['Sim' if (p,k) in available else 'Não' for p,k in zip(status['Período'],status['Mapa'])]
else:
    status['Localizado na rede']='Por analisar'
view=status.pivot(index='Período',columns='Mapa',values='Estado').reset_index()
st.dataframe(view,use_container_width=True,hide_index=True,height=400)
missing=status[status['Estado']=='Em falta'].copy()
st.download_button('Descarregar mapas em falta (CSV)',missing.to_csv(index=False,sep=';').encode('utf-8-sig'),file_name='ULSLA_dividas_creditos_pagamentos_em_falta.csv',mime='text/csv')
st.caption('Dezembro incluído: períodos contabilísticos 12, 13 e 14 são gravados como dezembro, sem duplicar o mês. Não são substituídos mapas anteriores sem autorização.')
