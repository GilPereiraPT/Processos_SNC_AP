"""Importador XML S3CP/SNC-AP, independente do nome do ficheiro.
Mantem intactos os fechos PDF. Guarda uma copia comprimida por tipo/periodo.
"""
from pathlib import Path
from periodos_snc_ap import normalizar_periodo, prioridade_periodo
import xml.etree.ElementTree as ET
import hashlib, json, gzip, os, tempfile, shutil
from decimal import Decimal
from datetime import datetime

TIPOS={'BA','DR','BLC','DFC','DOREC','DODES','AFT','AI','DAPL'}

def _tag(element): return element.tag.rsplit('}',1)[-1]
def _child(node,name):
    for e in node:
        if _tag(e)==name:return e
    return None
def _txt(node,name,default=''):
    child=_child(node,name)
    return (child.text or '').strip() if child is not None else default

def inspect(blob,filename=''):
    if len(blob)>75*1024*1024:raise ValueError('XML superior a 75 MB')
    if b'<!DOCTYPE' in blob.upper() or b'<!ENTITY' in blob.upper(): raise ValueError('DTD/ENTITY não permitidos')
    root=ET.fromstring(blob)
    tipo=_tag(root)
    if tipo not in TIPOS:raise ValueError('Tipo SNC-AP não reconhecido: '+tipo)
    cab=_child(root,'Cabecalho')
    if cab is None:raise ValueError('XML sem Cabecalho')
    ano=_txt(cab,'Ano');mes=_txt(cab,'Periodo');entidade=_txt(cab,'Entidade')
    if not (ano.isdigit() and len(ano)==4 and mes.isdigit() and 1<=int(mes)<=14 and entidade):raise ValueError('Cabeçalho SNC-AP inválido')
    periodo=normalizar_periodo(f'{ano}-{int(mes):02d}')
    # Armazena códigos e campos NUMERICOS dos resumos, registos e conciliações.
    def flat(node):
        result={}
        for child in node:
            if len(child):continue
            text=(child.text or '').strip()
            if not text:continue
            if _tag(child) in ('ContaLocal','NIFEntidadeParceira','Economica','FonteFinanciamento','ID_Registo','TipoReceitaDespesa','Periodo','Ano','Programa','Medida','Funcional','Atividade','Projeto'):
                result[_tag(child)]=text
            else:
                try:result[_tag(child)]=float(Decimal(text))
                except Exception:result[_tag(child)]=text
        return result
    resumo=[];registos=[];conciliacoes=[]
    # Caminho directo Resumo / Registos / RegistosConciliacao, sem duplicar as linhas de resumo.
    for group in root:
        name=_tag(group)
        if name=='Resumo':
            for item in group:
                if len(item)==0:continue
                resumo.append({'nivel':_tag(item),**flat(item)})
        if name=='Registos':
            for item in group:
                if _tag(item)=='Registo':
                    obj=flat(item)
                    if tipo=='BA':
                        obj['detalhes']={_txt(det,'SaldosEMovimentos'): {'Debito':float(_txt(det,'Debito','0') or 0),'Credito':float(_txt(det,'Credito','0') or 0)} for det in item if _tag(det)=='DetalheResumo'}
                    registos.append(obj)
        if name=='RegistosConciliacao':
            conciliacoes=[flat(x) for x in group]
    # AFT e AI possuem blocos especializados com resumos e desagregações.
    especiais={}
    if tipo in ('AFT','AI'):
        for section in root:
            name=_tag(section)
            if name=='Cabecalho':continue
            rows=[]
            for record_list in section:
                if _tag(record_list)=='Registos':rows.extend(flat(x) for x in record_list if _tag(x)=='Registo')
            totals=[]
            for elem in section.iter():
                if _tag(elem) in ('MacroRubrica','Resumo','RubricasAgregadoras') and len(elem):
                    f=flat(elem)
                    if any(k.startswith('Total') for k in f):totals.append(f)
            especiais[name]={'resumos':totals,'registos':rows}
    return {'tipo':tipo,'periodo':periodo,'periodo_original':f'{ano}-{int(mes):02d}','entidade':entidade,'hash':hashlib.sha256(blob).hexdigest(),
            'ficheiro':filename,'resumo':resumo,'registos':registos,'conciliacoes':conciliacoes,'especiais':especiais}

def _base(root):return Path(root)/'dados_s3cp_xml'
def catalog(root):
    base=_base(root)
    if not base.exists():return {}
    out={}
    # Compatibilidade com ficheiros historicos guardados em 2024-13/14.
    for path in sorted(base.glob('*/*.json.gz')):
        try:
            with gzip.open(path,'rt',encoding='utf8') as f:obj=json.load(f)
            old=obj['periodo'];key=(normalizar_periodo(old),obj['tipo'])
            rank=prioridade_periodo(obj.get('periodo_original',old)) + (100 if path.parent.name==key[0] else 0)
            previous=out.get(key)
            if previous and previous['_rank']>rank:continue
            out[key]={'hash':obj['hash'],'ficheiro':obj.get('ficheiro',''),'path':str(path),'_rank':rank}
        except Exception:continue
    return out

def load(root,periodo,tipo):
    canonical=normalizar_periodo(periodo)
    entry=catalog(root).get((canonical,tipo))
    if not entry:return None
    with gzip.open(entry['path'],'rt',encoding='utf8') as f:return json.load(f)

def save(root,obj,replace=False):
    obj=dict(obj)
    obj['periodo']=normalizar_periodo(obj['periodo'])
    dest=_base(root)/obj['periodo']/(obj['tipo']+'.json.gz');dest.parent.mkdir(parents=True,exist_ok=True)
    prev=catalog(root).get((obj['periodo'],obj['tipo']))
    if prev and not replace:raise FileExistsError(str(prev['path']))
    if prev:
        backup=_base(root)/'_backups'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        backup.mkdir(parents=True,exist_ok=True)
        original=Path(prev['path'])
        shutil.copy2(original,backup/(original.parent.name+'_'+obj['tipo']+'.json.gz'))
    fd,tmp=tempfile.mkstemp(prefix='.import_',suffix='.gz',dir=str(dest.parent));os.close(fd)
    try:
        with gzip.open(tmp,'wt',encoding='utf8') as f:json.dump(obj,f,ensure_ascii=False,separators=(',',':'))
        os.replace(tmp,dest)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return dest

def summary_value(obj, key, group=None, kind='resumo'):
    for row in obj.get(kind,[]):
        if group is None or group in str(row.values()):
            if key in row:return row[key]
    return None

def series(root,tipo,field):
    result=[]
    for periodo,kind in sorted(catalog(root)):
        if kind!=tipo:continue
        obj=load(root,periodo,tipo)
        val=summary_value(obj,field)
        if val is not None: result.append({'Período':periodo,'Valor (€)':val})
    return result

def pmp_ba(obj):
    if obj is None or obj['tipo']!='BA':return {}
    groups={'Fornecedores':['221','222','225','226'], 'Investimentos':['2711','2716'], 'Outros credores':['278929'], 'FSE':['62']}
    res={}
    for title,prefixes in groups.items():
        total=0.0
        for row in obj['registos']:
            acc=str(row.get('ContaLocal','')).replace('.','').strip()
            if str(row.get('NIFEntidadeParceira',''))!='999999990':continue
            if not any(acc.startswith(k) for k in prefixes):continue
            v=row.get('detalhes',{}).get('BA04',{})
            total+=(v.get('Debito',0)-v.get('Credito',0)) if title=='FSE' else (v.get('Credito',0)-v.get('Debito',0))
        res[title]=total
    return res

def as_dashboard_period(root,periodo):
    """Adaptador conservador: só mapeia rubricas com correspondência identificada.
    Não pretende reconstruir todas as sub-rubricas de um balancete PDF.
    """
    result={'periodo':periodo,'referencia':periodo,'origem':'XML SNC-AP (S3CP)',
            'natureza':'DR/DFC acumulados; Balanço à data'}
    obj=load(root,periodo,'DR')
    if obj:
        records={r['Rubrica']:r['ValorAnoCorrente'] for r in obj['registos']}
        agg={r['RubricaAgregadora']:r['TotalAnoCorrente'] for r in obj['resumo']}
        mapping={'vendas':'DR01','prestacoes_servicos':'DR02','transferencias':'DR03','rendimentos_impostos':'DR04',
                 'consumos':'DR08','fse':'DR09','pessoal':'DR10','outros_rendimentos':'DR18',
                 'outros_gastos':'DR19','depreciacoes':'DR20'}
        dr={k:abs(records[code]) if k in ('consumos','fse','pessoal','outros_gastos','depreciacoes') else records[code]
            for k,code in mapping.items() if code in records}
        if 'DRX04' in agg:dr['resultado']=agg['DRX04']
        if 'DRX01' in agg:dr['ebitda']=agg['DRX01']
        if 'DRX02' in agg:dr['operacional']=agg['DRX02']
        result['dr']=dr
    obj=load(root,periodo,'BLC')
    if obj:
        agg={r['MacroRubrica']:r['TotalAnoCorrente'] for r in obj['resumo'] if r.get('nivel')=='ResumoMacroRubrica'}
        aggs={r['RubricaAgregadora']:r['TotalAnoCorrente'] for r in obj['resumo'] if 'RubricaAgregadora' in r}
        records={r['Rubrica']:r['ValorAnoCorrente'] for r in obj['registos']}
        bal={}
        for key,code in [('ativo','AT1'),('patrimonio','PL1'),('passivo','P1')]:
            if code in agg:bal[key]=agg[code]
        for key,code in [('ativo_nao_corrente','AT11'),('ativo_corrente','AT12'),('passivo_nao_corrente','P11'),('passivo_corrente','P12'),('ativos_fixos','B01'),('caixa','B23'),('patrimonio_resultado','B33')]:
            source=records if code.startswith('B') else aggs
            if code in source:bal[key]=source[code]
        result['balanco']=bal
    obj=load(root,periodo,'DFC')
    if obj:
        agg={r['RubricaAgregadora']:r['TotalAnoCorrente'] for r in obj['resumo']}
        mapping={'operacional':'DFCX02','investimento':'DFCX03','financiamento':'DFCX04',
                 'variacao_caixa':'DFCX05','caixa_inicial':'DFCX07','caixa_final':'DFCX10'}
        result['dfc']={k:agg[code] for k,code in mapping.items() if code in agg}
    return result
