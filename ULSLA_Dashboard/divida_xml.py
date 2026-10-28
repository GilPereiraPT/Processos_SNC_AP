"""Leitor e métricas de stocks de dívida/crédito e fluxos de pagamento SNC-AP."""
from collections import defaultdict
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from io import BytesIO
import gzip
from pathlib import Path
import json
import xml.etree.ElementTree as ET
import pandas as pd

KINDS={'Dividas':'Dividas','Pagamentos':'Pagamentos','Creditos':'Creditos'}
FIELDS=('NomeFornec','NifFornec','NomeCliente','NifCliente','DataDoc','NumDoc','TipoDoc','ValorDoc','DataLancDoc','DataPagamento','DataVencDoc','TipoDocCentral','ClassificadorEconomico','TipoEntidadeCentral','Factoring')

def parse_xml(source):
    """Devolve tipo, periodo, dataframe; valida entidade e campos basicos."""
    payload=source.read() if hasattr(source,'read') else Path(source).read_bytes()
    if hasattr(source,'seek'):source.seek(0)
    # Rejeita DTD e entidades externas antes de passar ao parser.
    if b'<!DOCTYPE' in payload.upper() or b'<!ENTITY' in payload.upper():raise ValueError('DTD/ENTITIES não permitidas nos XML')
    root=ET.fromstring(payload)
    kind=root.tag.split('}')[-1]
    if kind not in KINDS:raise ValueError(f'Tipo de XML não suportado: {kind}')
    codigo=root.findtext('./Cabecalho/Entidade/Codigo')
    if codigo!='2069':raise ValueError(f'Entidade {codigo!r} diferente da ULSLA (2069)')
    y=int(root.findtext('./Cabecalho/Periodo/Ano'))
    m=int(root.findtext('./Cabecalho/Periodo/NumeroMes'))
    periodo=f'{y:04d}-{m:02d}'
    rows=[]
    for ln in root.findall('./Corpo/Linha'):
        obj={field:ln.findtext(field) or '' for field in FIELDS}
        try:obj['ValorDoc']=float(Decimal(obj['ValorDoc']))
        except (InvalidOperation,ValueError):raise ValueError(f'ValorDoc inválido no documento {obj["NumDoc"]}')
        obj['NomeEntidade']=obj['NomeFornec'] or obj['NomeCliente']
        obj['NifEntidade']=obj['NifFornec'] or obj['NifCliente']
        for field in ['DataDoc','DataLancDoc','DataPagamento','DataVencDoc']:
            obj[field]=pd.to_datetime(obj[field],format='%d-%m-%Y',errors='coerce')
        rows.append(obj)
    df=pd.DataFrame(rows)
    if df.empty:raise ValueError(f'XML {kind} sem linhas')
    return kind,periodo,df

def summary(df,kind,period):
    sums=df.groupby('TipoDocCentral').ValorDoc.agg(['sum','count'])
    result={x:{'valor':round(float(row['sum']),2),'documentos':int(row['count'])} for x,row in sums.iterrows()}
    if kind=='Dividas':
        p2=result.get('P2',{}).get('valor',0)
        nc=result.get('NC',{}).get('valor',0)
        result['P2_LIQUIDO']={'valor':round(p2+nc,2),'documentos':None}
    if kind=='Pagamentos':
        docs=df[df['DataPagamento'].notna() & df['DataDoc'].notna() & df['ValorDoc'].gt(0)].copy()
        if not docs.empty:
            docs['dias']=(docs.DataPagamento-docs.DataDoc).dt.days
            docs=docs[docs.dias.ge(0)]
            result['PRAZO_PAGAMENTO_OBSERVADO']={'valor':round(float((docs['dias']*docs.ValorDoc).sum()/docs.ValorDoc.sum()),1) if docs.ValorDoc.sum() else None,'documentos':len(docs)}
    return result

def write_snapshot(root,period,dfs,replace=False):
    base=Path(root)/'dados_xml';dest=base/period
    if dest.exists() and not replace:raise ValueError(f'O período {period} já existe')
    dest.mkdir(parents=True,exist_ok=True)
    # JSON comprimido dispensa motores binários de Parquet no Windows.
    for kind,df in dfs.items():
        tmp=dest/(kind+'.tmp.json.gz')
        with gzip.open(tmp,'wt',encoding='utf8') as out:
            out.write(df.to_json(orient='records',date_format='iso',force_ascii=False))
        tmp.replace(dest/(kind+'.json.gz'))
    meta={'periodo':period,'tipos':sorted(dfs),'totais':{k:summary(v,k,period) for k,v in dfs.items()}}
    t=dest/'resumo.tmp';t.write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf8');t.replace(dest/'resumo.json')
    return meta

def snapshots(root):
    base=Path(root)/'dados_xml';out={}
    for file in sorted(base.glob('????-??/resumo.json')):
        try:out[file.parent.name]=json.loads(file.read_text(encoding='utf8'))
        except Exception:continue
    return out

def load_snapshot(root,period,kind):
    path=Path(root)/'dados_xml'/period/(kind+'.json.gz')
    if not path.exists():return pd.DataFrame()
    with gzip.open(path,'rt',encoding='utf8') as src: df=pd.DataFrame(json.load(src))
    for field in ['DataDoc','DataLancDoc','DataPagamento','DataVencDoc']:
        if field in df: df[field]=pd.to_datetime(df[field],errors='coerce')
    return df

def enriched_debt(df,period):
    df=df.copy();ref=(pd.Period(period,freq='M').end_time).normalize()
    df['Dias vencidos']=(ref-df.DataVencDoc).dt.days
    df['Estado vencimento']=pd.cut(df['Dias vencidos'],bins=[-100000,-1,0,30,60,90,180,365,100000],labels=['Não vencida','Vence hoje','1–30 dias','31–60 dias','61–90 dias','91–180 dias','181–365 dias','>365 dias'])
    return df

def supplier_summary(df):
    return df.groupby(['NifEntidade','NomeEntidade'],dropna=False,as_index=False).ValorDoc.sum().sort_values('ValorDoc',ascending=False)

def payment_days(df):
    valid=df[(df.ValorDoc>0)&df.DataDoc.notna()&df.DataPagamento.notna()].copy()
    valid['dias']=(valid.DataPagamento-valid.DataDoc).dt.days
    valid=valid[valid.dias.ge(0)]
    return float((valid.ValorDoc*valid.dias).sum()/valid.ValorDoc.sum()) if len(valid) and valid.ValorDoc.sum() else None
