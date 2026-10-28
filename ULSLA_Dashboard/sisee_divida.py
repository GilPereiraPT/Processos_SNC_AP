"""ULSLA: antiguidade da divida a partir dos snapshots Dividas.xml.
Classificacao de entidades original preservada; Segurança Social sempre Estado.
Nao imputa, nao estima datas; documento sem vencimento bloqueia a submissao.
"""
from __future__ import annotations
import gzip,json,re,calendar
from pathlib import Path
from datetime import date,datetime,timedelta
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict,Counter

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'dados_xml'
Q=Decimal('0.01')
ACSS_LABELS=('Dívida vincenda','0–90 dias','91–180 dias','181–240 dias','241–360 dias','361–540 dias','541–720 dias','721 dias ou mais')
SISEE_LABELS=('Dívida vincenda','0–90 dias','91–120 dias','121–240 dias','241–360 dias','Mais de 360 dias')
ACSS_ROWS={
'SNS':['Restantes RCE','02.01.09, 02.01.10 e 02.01.11 Produtos Químicos e Farmacêuticos'],
'Estado':['01.01 - RCP','01.02 - AVE','01.03.05.A0 - CGA','01.03.05.A0 - SS','Restantes RCE','01.03.- OUTRAS','02.01.09, 02.01.10 e 02.01.11 Produtos Químicos e Farmacêuticos'],
'Externos':['Restantes RCE','02.01.09, 02.01.10 e 02.01.11 Produtos Químicos e Farmacêuticos','07.01 - AQUISIÇÃO CAPITAL']}
CGA_NIFS={'500792968'}  # NIF comprovado pelos documentos ULSLA; nao usar para sobrepor a conta economica
CGA_WORDS=('CAIXA GERAL DE APOSENTACOES','CAIXA GERAL APOSENTACOES','C G A','CGA')
SOCIAL_NIFS={'505305500'}
SOCIAL_CODES={'9964001','9964002'}
SOCIAL_WORDS=('SEGURANCA SOCIAL','INSTITUTO DA SEGURANCA SOCIAL','CENTRO DISTRITAL SEGURANCA SOCIAL','EXECUCAO DE DIVIDA A SEGURANCA SOCIAL','I S S I P')

def ntext(s):
 import unicodedata
 return ''.join(c for c in unicodedata.normalize('NFKD',str(s or '').upper()) if not unicodedata.combining(c))

def social(row):
 nif=re.sub(r'\D','',str(row.get('NifEntidade') or row.get('NifFornec') or ''))
 name=ntext(row.get('NomeEntidade') or row.get('NomeFornec'))
 supplier=str(row.get('CodFornec') or row.get('CodigoFornecedor') or row.get('CodEntidade') or '')
 return nif in SOCIAL_NIFS or supplier in SOCIAL_CODES or any(term in name for term in SOCIAL_WORDS)

def is_cga(row):
 nif=re.sub(r'\D','',str(row.get('NifEntidade') or row.get('NifFornec') or ''))
 name=ntext(row.get('NomeEntidade') or row.get('NomeFornec'))
 return nif in CGA_NIFS or any(term in name for term in CGA_WORDS)

def group(row, overrides=None):
 nif=str(row.get('NifEntidade') or row.get('NifFornec') or '').strip()
 name=ntext(row.get('NomeEntidade') or row.get('NomeFornec'))
 if social(row):return 'Estado'
 overrides=overrides or {}
 if nif in overrides:return overrides[nif]
 raw=ntext(row.get('TipoEntidadeCentral')).strip()
 # Mapeamento local configuravel; nunca confiar em 999999990 como classe.
 if raw in ('1','SNS','SERVICO NACIONAL DE SAUDE'):return 'SNS'
 if raw in ('2','ESTADO','ADMINISTRACAO PUBLICA'):return 'Estado'
 if raw in ('3','EXTERNOS','EXTERNO'):return 'Externos'
 raise ValueError(f'Tipo de entidade sem classificacao: {raw!r}, fornecedor {name[:55]}')

def _normaliza_conta(code):
 return str(code or '').strip().upper().replace(' ', '')

@__import__('functools').lru_cache(maxsize=1)
def _mapeamento_rce():
 path=ROOT/'sisee_mapeamento_rce.tsv'
 if not path.exists():
  raise FileNotFoundError(f'Mapeamento RCE em falta: {path}. Nao e seguro gerar o reporte.')
 mapping={}
 for line in path.read_text(encoding='utf-8-sig').splitlines()[1:]:
  cols=line.split('\t')
  if len(cols)>=2 and cols[0].strip() and cols[1].strip():mapping[_normaliza_conta(cols[0])]=cols[1].strip()
 return mapping

def economic(row, grp):
 # A imputacao vem da coluna «Conta Acumulação» do Excel de trabalho.
 # A designacao/NIF nao podem sobrepor-se a RCP e AVE nem ao codigo RCE.
 raw=_normaliza_conta(row.get('ClassificadorEconomico'))
 # Prioridade absoluta: rubrica economica por linha, independentemente do fornecedor.
 # Um mesmo documento da CGA pode conter linhas RCP, AVE e contribuicoes CGA.
 if grp=='Estado' and raw.startswith('01.01.'):
  return '01.01 - RCP'
 if grp=='Estado' and raw.startswith('01.02.'):
  return '01.02 - AVE'
 mapping=_mapeamento_rce()
 mapped=mapping.get(raw)
 if mapped is None:
  # Conta sintetica sem correspondencia exata: somente prefixos inequívocos.
  p=re.sub(r'[^0-9]','',raw)
  if p.startswith('0101'):mapped='01.01 - RCP'
  elif p.startswith('0102'):mapped='01.02 - AVE'
  elif p.startswith(('020109','020110','020111')):mapped='02.01.09, 02.01.10 e 02.01.11 Produtos Químicos e Farmacêuticos'
  elif p.startswith('0701'):mapped='07.01 - AQUISIÇÃO CAPITAL'
  elif p.startswith('010305'):
   if 'A0.A0' in raw:mapped='01.03.05.A0 - CGA'
   elif 'A0.B0' in raw:mapped='01.03.05.A0 - SS'
   else:mapped='01.03.- OUTRAS'
  elif p.startswith('0103'):mapped='01.03.- OUTRAS'
  else:mapped='Restantes RCE'
 if mapped in ('01.03.05.A0 - OUTRAS','01.03 - RESTANTES','01.03.01.A0 - ADSE'):
  mapped='01.03.- OUTRAS'
 if mapped.startswith('02.01.09,'):
  return '02.01.09, 02.01.10 e 02.01.11 Produtos Químicos e Farmacêuticos'
 if mapped.startswith('07.01'):
  return '07.01 - AQUISIÇÃO CAPITAL' if grp=='Externos' else 'Restantes RCE'
 if mapped in ACSS_ROWS.get(grp,[]):return mapped
 return 'Restantes RCE'

def capital(row):
 code=re.sub(r'[^0-9]','',str(row.get('ClassificadorEconomico') or ''))
 return code.startswith('07')

def dt(v):
 if v is None or str(v).strip() in ('','NaT','None'):return None
 try:
  from datetime import datetime
  if isinstance(v,(datetime,date)):return v.date() if isinstance(v,datetime) else v
  s=str(v).strip()
  for fmt in ('%Y-%m-%d','%d-%m-%Y','%d/%m/%Y','%Y-%m-%dT%H:%M:%S','%Y-%m-%dT%H:%M:%S.%f'):
   try:return datetime.strptime(s[:26],fmt).date()
   except ValueError:pass
 except Exception:pass
 return None

# Prazo maximo para efeitos de antiguidade, sem alterar o XML de origem.
MAX_PRAZO_PAGAMENTO_DIAS=60
DATA_EMISSAO_CAMPOS=('DataEmissaoDoc','DataEmissao','DataEmisDoc','DataEmis','DataDocumento','DataDoc','DataFatura','DataFactura','DataRegistoDoc')

def vencimento_ajustado(row):
 due=dt(row.get('DataVencDoc'))
 if due is None:raise ValueError('data de vencimento em falta/inválida')
 emission=None
 used=None
 for field in DATA_EMISSAO_CAMPOS:
  if row.get(field) not in (None,''):
   emission=dt(row.get(field))
   if emission is None:raise ValueError(f'data de emissão inválida no campo {field}')
   used=field
   break
 if emission is None:
  raise ValueError('data de emissão não encontrada; impossível verificar prazo máximo de 60 dias')
 if due<emission:
  raise ValueError('vencimento anterior à emissão; requer conferência manual')
 adjusted=min(due,emission+timedelta(days=MAX_PRAZO_PAGAMENTO_DIAS))
 return adjusted,adjusted!=due,used

def bucket(days, mode):
 if days<0:return 0
 if mode=='ACSS':return 1 if days<=90 else 2 if days<=180 else 3 if days<=240 else 4 if days<=360 else 5 if days<=540 else 6 if days<=720 else 7
 return 1 if days<=90 else 2 if days<=120 else 3 if days<=240 else 4 if days<=360 else 5

def load(year,month):
 p=DATA/f'{year}-{month:02d}'/'Dividas.json.gz'
 if not p.is_file():raise FileNotFoundError(f'Dividas.xml ainda não importado para {year}-{month:02d}. Esperado: {p}')
 with gzip.open(p,'rt',encoding='utf-8') as h: records=json.load(h)
 if not isinstance(records,list):raise ValueError('Formato de Dividas.json.gz inesperado')
 return records,p

def data_referencia_fim_mes(year, month):
 """Data contabilistica da fotografia: ultimo dia do mes seleccionado, nunca hoje."""
 if not (1 <= int(month) <= 12):
  raise ValueError('Mes invalido: utilizar 1 a 12')
 return date(int(year),int(month),calendar.monthrange(int(year),int(month))[1])

def analyze(year,month,overrides=None):
 rows,path=load(year,month)
 ref=data_referencia_fim_mes(year,month)
 acss=defaultdict(lambda:[Decimal('0')]*8)
 sisee=defaultdict(lambda:[Decimal('0')]*6)
 issues=[];errors_total=0;count=0;total=Decimal('0');raw_groups=Counter();reclasses=Counter();adjusted_count=0;adjusted_amount=Decimal('0');emission_sources=Counter();excluded_sisee=defaultdict(lambda:Decimal('0'));externos_total=Decimal('0');externos_count=0;excluidos_count=Counter()
 cf_count=0;cf_sum=Decimal('0')
 for i,row in enumerate(rows,1):
  if str(row.get('TipoDoc') or '').strip().upper()=='CF':
   try:cf_sum+=Decimal(str(row.get('ValorDoc','')).replace(',','.'))
   except Exception as e:raise ValueError(f'Valor CF invalido na linha {i}: {e}')
   cf_count+=1
   continue
  try:
   v=Decimal(str(row.get('ValorDoc','')).replace(',','.'))
   due,was_adjusted,emission_field=vencimento_ajustado(row)
   emission_sources[emission_field]+=1
   if was_adjusted:
    adjusted_count+=1
    adjusted_amount+=v
   grp=group(row,overrides)
   cat=economic(row,grp)
   raw=str(row.get('TipoEntidadeCentral','')).strip()
   if social(row) and raw=='3':reclasses['Segurança Social: Externos → Estado']+=1
   raw_groups[raw]+=1
   days=(ref-due).days
   acss[(grp,cat)][bucket(days,'ACSS')]+=v
   typ='Capital' if capital(row) else 'Bens e serviços'
   
   if grp=='Externos':
    sisee[typ][bucket(days,'SISEE')]+=v
    externos_total+=v
    externos_count+=1
   else:
    excluded_sisee[grp]+=v
    excluidos_count[grp]+=1
   total+=v;count+=1
  except Exception as e:
   errors_total+=1
   if len(issues)<100:issues.append(f'Linha {i}, documento {row.get("NumDoc", "?")}: {e}')
 if issues:raise ValueError(f'{errors_total} erros de classificação/vencimento (até 100 apresentados): '+ ' | '.join(issues[:8]))
 sisee_apurado=sum((sum(vec,Decimal('0')) for vec in sisee.values()),Decimal('0'))
 excluidos_apurados=sum(excluded_sisee.values(),Decimal('0'))
 if sisee_apurado != externos_total:
  raise ValueError(f'ERRO DE CONTROLO SISEE: total do SD ({sisee_apurado}) diferente de Externos ({externos_total})')
 if total != sisee_apurado+excluidos_apurados:
  raise ValueError('ERRO DE CONTROLO SISEE: total da divida nao reconcilia com Externos + SNS + Estado')
 return dict(acss),dict(sisee),{'periodo':f'{year}-{month:02d}','data_referencia':ref.isoformat(),'documentos':count,'total':total,'ficheiro':str(path),'seguranca_social_corrigida':sum(reclasses.values()),'tipos_origem':dict(raw_groups),'prazo_maximo_dias':MAX_PRAZO_PAGAMENTO_DIAS,'documentos_vencimento_ajustado':adjusted_count,'valor_documentos_vencimento_ajustado':adjusted_amount,'campos_emissao':dict(emission_sources),'sisee_excluidos':dict(excluded_sisee),'sisee_total_externos':sisee_apurado,'sisee_documentos_externos':externos_count,'sisee_documentos_excluidos':dict(excluidos_count),'sisee_validado_apenas_externos':True,'documentos_cf_excluidos':cf_count,'valor_cf_excluido':cf_sum}

def acss_table(grouped):
 rows=[]
 for grp in ('SNS','Estado','Externos'):
  subt=[Decimal('0')]*8
  for (g,cat),vec in grouped.items():
   if g==grp:subt=[a+b for a,b in zip(subt,vec)]
  rows.append((grp,subt,True))
  for cat in ACSS_ROWS[grp]:
   v=grouped.get((grp,cat),[Decimal('0')]*8)
   rows.append(('    '+cat,v,False))
 grand=[sum((v[i] for (g,c),v in grouped.items()),Decimal('0')) for i in range(8)]
 rows.append(('Total Geral',grand,True))
 return rows

def fill_sd(model_bytes,year,month,overrides=None):
 from io import BytesIO
 from openpyxl import load_workbook
 acss,sisee,meta=analyze(year,month,overrides)
 if not meta.get('sisee_validado_apenas_externos'):
  raise ValueError('SISEE SD bloqueado: nao foi possivel validar o filtro de fornecedores externos')
 if meta['data_referencia'] != data_referencia_fim_mes(year,month).isoformat():
  raise ValueError('SISEE SD bloqueado: data de referencia inesperada')
 wb=load_workbook(BytesIO(model_bytes))
 if 'Formulário' not in wb.sheetnames:raise ValueError('Modelo SD sem folha Formulário')
 sh=wb['Formulário']
 # Confirmar estrutura antes de alterar: modelos SISEE variam entre tarefas.
 if 'Aquisições de bens e serviços' not in str(sh['B14'].value or '') or 'Aquisições de capital' not in str(sh['B15'].value or ''):
  raise ValueError('Estrutura SD não reconhecida nas linhas 14 e 15')
 # O template tem 6 colunas de escalões, C:H, 2 linhas de natureza e dois totais.
 bens=sisee.get('Bens e serviços',[Decimal('0')]*6)
 cap=sisee.get('Capital',[Decimal('0')]*6)
 for ix,col in enumerate(range(3,9)):
  for row,value in ((14,bens[ix]),(15,cap[ix]),(16,bens[ix]+cap[ix])):
   c=sh.cell(row,col)
   if c.data_type=='f':raise ValueError(f'Fórmula preexistente em {c.coordinate}')
   c.value=float(value.quantize(Q,rounding=ROUND_HALF_UP))
   if c.number_format in ('General','0'):c.number_format='#,##0.00'
 # Linha 17 e uma celula unica C17:H17, com o total de fornecedores.
 c=sh['C17']
 if c.data_type=='f':raise ValueError('Fórmula preexistente em C17')
 c.value=float(sum(bens+cap,Decimal('0')).quantize(Q))
 if c.number_format in ('General','0'):c.number_format='#,##0.00'
 # Os mapas SISEE nao sao submetidos se o Excel nao conservar os valores.
 # Nao alterar o numero do mes, as formulas nem a restante estrutura do modelo.
 out=BytesIO();wb.save(out)
 resultado=out.getvalue()
 check=load_workbook(BytesIO(resultado),read_only=False,data_only=False)
 f=check['Formulário']
 esperado=sum(bens+cap,Decimal('0'))
 total_guardado=Decimal('0')
 for ix,col in enumerate(range(3,9)):
  for linha,valor in ((14,bens[ix]),(15,cap[ix]),(16,bens[ix]+cap[ix])):
   cel=f.cell(linha,col)
   if not isinstance(cel.value,(int,float)):
    raise ValueError(f'SD nao preenchido: {cel.coordinate} ficou vazio ou nao numerico')
   if abs(Decimal(str(cel.value))-valor)>Decimal('0.005'):
    raise ValueError(f'SD nao reconciliado na celula {cel.coordinate}')
  total_guardado+=Decimal(str(f.cell(16,col).value))
 if abs(total_guardado-esperado)>Decimal('0.005'):
  raise ValueError('SD bloqueado: total dos escaloes difere do valor dos fornecedores Externos')
 if abs(Decimal(str(f['C17'].value))-esperado)>Decimal('0.005'):
  raise ValueError('SD bloqueado: saldo total de fornecedores nao foi gravado corretamente')
 if abs(esperado-meta['sisee_total_externos'])>Decimal('0.005'):
  raise ValueError('SD bloqueado: o mapa inclui valores fora do universo Externos')
 meta['sisee_celulas_verificadas']=19
 meta['sisee_celulas_preenchidas']={f'{f.cell(r,col).coordinate}':f.cell(r,col).value for r in (14,15,16) for col in range(3,9)}
 meta['sisee_celulas_preenchidas']['C17']=f['C17'].value
 return resultado,meta

def acss_excel(year,month,overrides=None):
 from io import BytesIO
 from openpyxl import Workbook
 from openpyxl.styles import Font,PatternFill,Alignment,Border,Side
 from openpyxl.utils import get_column_letter
 acss,sisee,meta=analyze(year,month,overrides)
 wb=Workbook();sh=wb.active;sh.title='ACSS Antiguidade'
 sh.merge_cells('A1:J1');sh['A1']=f'ULSLA | Antiguidade da Dívida · {month:02d}/{year}'
 sh['A1'].font=Font(size=17,bold=True,color='FFFFFF');sh['A1'].fill=PatternFill('solid',fgColor='142E49');sh.row_dimensions[1].height=32
 for j,title in enumerate(('Classificação',)+ACSS_LABELS+('Total Geral',),1):
  c=sh.cell(3,j,title);c.font=Font(bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='246184');c.alignment=Alignment(wrap_text=True)
 sh.row_dimensions[3].height=42
 for r,(label,values,is_total) in enumerate(acss_table(acss),4):
  sh.cell(r,1,label)
  for j,value in enumerate(values,2):sh.cell(r,j,float(value.quantize(Q)));sh.cell(r,j).number_format='#,##0.00 "€";[Red](#,##0.00 "€");0.00 "€"'
  sh.cell(r,10,f'=SUM(B{r}:I{r})').number_format='#,##0.00 "€";[Red](#,##0.00 "€");0.00 "€"'
  if is_total:
   for c in sh[r][:10]:c.font=Font(bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='285372' if label!='Total Geral' else '18334D')
 sh.column_dimensions['A'].width=66
 for col in 'BCDEFGHIJ':sh.column_dimensions[col].width=19
 sh.freeze_panes='B4';sh.sheet_view.showGridLines=False
 # Metadados para auditoria, nao enviados na SISEE.
 src=wb.create_sheet('Controlo');src.append(['Origem',meta['ficheiro']]);src.append(['Data referência',meta['data_referencia']]);src.append(['Documentos',meta['documentos']]);src.append(['Total contabilizado',float(meta['total'])]);src.append(['Segurança Social reclassificada',meta['seguranca_social_corrigida']]);src.append(['Prazo máximo considerado (dias)',meta['prazo_maximo_dias']]);src.append(['Documentos com vencimento ajustado',meta['documentos_vencimento_ajustado']]);src.append(['Valor dos documentos ajustados',float(meta['valor_documentos_vencimento_ajustado'])]);src.column_dimensions['A'].width=35;src.column_dimensions['B'].width=100
 out=BytesIO();wb.save(out)
 return out.getvalue(),meta
