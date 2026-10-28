"""DR/Balanço trimestrais e UTE com movimentos exclusivos do trimestre."""
from decimal import Decimal as D, ROUND_HALF_UP
from io import BytesIO
from openpyxl import load_workbook
from pathlib import Path
import json,gzip
VERSION='2.6.0'
ROOT=Path(__file__).resolve().parent
DR_MAP={**{r:f'DR{r-9:02d}' for r in range(10,29)},30:'DR20',31:'DR21',33:'DR22',34:'DR23',36:'DR24'}
DR_TOTAL={29:'DRX01',32:'DRX02',35:'DRX03',37:'DRX04'}
B_MAP={**{r:f'B{r-10:02d}' for r in range(11,17)},17:'B54',18:'B07',19:'B08',20:'B09',21:'B10',22:'B56',
 **{r:f'B{r-14:02d}' for r in range(25,38)},**{r:f'B{r-17:02d}' for r in range(41,52)},
 55:'B36',56:'B37',57:'B38',58:'B55',59:'B39',60:'B40',61:'B41',62:'B42',**{r:f'B{r-22:02d}' for r in range(65,76)}}
B_TOTAL={23:'AT11',38:'AT12',39:'AT1',52:'PL11',63:'P11',76:'P12',77:'P1',78:'PL1P1'}

def money(x):
 v=D(str(x))
 if not v.is_finite():raise ValueError('Montante inválido.')
 return v.quantize(D('.01'),rounding=ROUND_HALF_UP)


def load_source(year,month,kind,root=ROOT):
 # Movimentos bancários: dezembro civil, nunca fechos 13/14.
 months=[14,13,12] if month==12 and kind!='BA' else [month]
 for mm in months:
  p=Path(root)/'dados_s3cp_xml'/f'{year}-{mm:02d}'/(kind+'.json.gz')
  if p.exists():
   obj=json.load(gzip.open(p,'rt',encoding='utf-8'))
   if obj.get('tipo')!=kind or str(obj.get('entidade'))!='510445152':raise ValueError('Tipo ou entidade inesperados em '+str(p))
   return obj
 raise ValueError(f'{kind} de {year}-{month:02d} não importado.')


def check(total,parts,label):
 if abs(total-sum(parts,D(0)))>D('.01'):raise ValueError('Reconciliação falhou: '+label)


def statement(obj,kind):
 data={}
 for r in obj.get('registos',[]):
  code=r.get('Rubrica')
  if code in data:raise ValueError('Rubrica repetida: '+str(code))
  data[code]=money(r['ValorAnoCorrente'])
 totals={}
 for r in obj.get('resumo',[]):
  code=r.get('RubricaAgregadora') or r.get('MacroRubrica')
  if code in totals and totals[code]!=money(r['TotalAnoCorrente']):raise ValueError('Resumo contraditório: '+code)
  totals[code]=money(r['TotalAnoCorrente'])
 mapping,aggregate=(DR_MAP,DR_TOTAL) if kind=='DR' else (B_MAP,B_TOTAL)
 missing=set(mapping.values())-set(data)
 missing.update(set(aggregate.values())-set(totals))
 if missing:raise ValueError('Rubricas XML em falta: '+', '.join(sorted(missing)))
 values={r:data[c] for r,c in mapping.items()};values.update({r:totals[c] for r,c in aggregate.items()})
 # XML SNC-AP já contém o sinal económico, incluindo reversões positivas.
 if kind=='DR':
  for total,rows in [(29,range(10,29)),(32,[29,30,31]),(35,[32,33,34]),(37,[35,36])]:check(values[total],[values[r] for r in rows],f'DR linha {total}')
 else:
  if data.get('B35',D(0))!=0:raise ValueError('B35 não nula sem linha correspondente no formulário Balanço fornecido.')
  for total,rows in [(23,range(11,23)),(38,range(25,38)),(39,[23,38]),(52,range(41,52)),(63,range(55,63)),(76,range(65,76)),(77,[63,76]),(78,[52,77])]:check(values[total],[values[r] for r in rows],f'Balanço linha {total}')
  check(values[39],[values[78]],'Ativo = património líquido + passivo')
 return values


def bank_accounts(obj):
 # Somar dimensões/parceiros antes de escolher fronteira hierárquica.
 out={};seen=set()
 for row in obj.get('registos',[]):
  code=''.join(c for c in str(row.get('ContaLocal','')) if c.isdigit())
  if not code.startswith(('11','12','13')):continue
  record=str(row.get('ID_Registo','')).strip()
  if record:
   if record in seen:raise ValueError('ID_Registo bancário repetido: '+record)
   seen.add(record)
  for detail in ('BA02','BA04'):
   v=row.get('detalhes',{}).get(detail)
   if v is None:raise ValueError(f'{detail} em falta para a conta {code}')
   pair=out.setdefault(code,{}).setdefault(detail,[D(0),D(0)])
   pair[0]+=money(v['Debito']);pair[1]+=money(v['Credito'])
 return out


def bank_sum(accounts,prefix,detail):
 codes=sorted(k for k in accounts if k.startswith(prefix))
 frontier=[k for k in codes if not any(k.startswith(p) and p!=k for p in codes)]
 return [sum((accounts[k][detail][i] for k in frontier),D(0)) for i in (0,1)]


def ute(year,month,extras,loader=load_source):
 if month not in (3,6,9,12):raise ValueError('Mês de fecho trimestral inválido.')
 previous=bank_accounts(loader(year,month-3,'BA') if month>3 else loader(year-1,12,'BA'))
 monthly=[bank_accounts(loader(year,m,'BA')) for m in range(month-2,month+1)]
 current=monthly[-1];rows={};warnings=[]
 for prefix,start,manual_gain in [('121',34,'juros_igcp'),('122',39,'juros_outros')]:
  d,c=bank_sum(previous,prefix,'BA04');opening=d-c
  d,c=bank_sum(current,prefix,'BA04');closing=d-c
  debits=sum((bank_sum(a,prefix,'BA02')[0] for a in monthly),D(0))
  credits=sum((bank_sum(a,prefix,'BA02')[1] for a in monthly),D(0))
  check(closing,[opening,debits,-credits],f'UTE {prefix}: saldo inicial + débitos − créditos = saldo final')
  rows.update({start:opening,start+1:money(extras.get(manual_gain,0)),start+2:credits,start+3:debits,start+4:closing})
 # Subcontas 129 (imparidades) não representam disponibilidades bancárias.
 for a in monthly+[previous]:
  for code,details in a.items():
   if code.startswith('12') and not code.startswith(('121','122')) and any(v!=0 for pair in details.values() for v in pair):
    raise ValueError('Conta bancária fora da classificação IGCP/Outras: '+code)
 # Aplicações: distinguir tesouraria/financeiras exige prazo/tipo, não inferível só por 13.
 detected=any(any(v!=0 for pair in details.values() for v in pair) for a in monthly+[previous] for code,details in a.items() if code.startswith('13'))
 if detected and not extras.get('aplicacoes_confirmadas'):raise ValueError('Há movimentos/saldos na classe 13. Preenche e confirma a classificação das aplicações na página.')
 for start in (11,16,22,27):
  vals=[money(extras.get(f'ap_{start}_{key}',0)) for key in ('inicio','ganhos','diminuicoes','aumentos')]
  for i,v in enumerate(vals):rows[start+i]=v
  rows[start+4]=vals[0]-vals[2]+vals[3]
  if rows[start+4]<0:raise ValueError('Saldo de aplicações negativo: linha '+str(start+4))
 rows[10]=rows[15]+rows[20];rows[21]=rows[26]+rows[31];rows[32]=rows[10]+rows[21]
 rows[44]=rows[38]+rows[43];rows[45]=rows[32]+rows[44]
 rows[46]=rows[15]+rows[26]+rows[38];rows[47]=rows[20]+rows[31]+rows[43]
 for row,key in [(48,'dispensa'),(50,'ganhos_dispensa'),(51,'ganhos_entregues')]:rows[row]=money(extras.get(key,0))
 rows[49]=(rows[46]/rows[45]) if rows[45] else D(0)  # Excel percentual, sem arredondar a cêntimos.
 rows[52]=rows[46]
 d,c=bank_sum(current,'11','BA04');rows[53]=d-c;rows[54]=rows[53]+rows[44];rows[55]=D(int(bool(extras.get('autorizacao',False))))
 check(rows[45],[rows[46],rows[47]],'UTE total IGCP e Outras')
 # Caixa/bancos no Balanço: o confronto é feito ao mesmo fecho.
 try:
  balance=statement(loader(year,month,'BLC'),'BAL')
  check(balance[37],[rows[54]],'UTE caixa + depósitos à ordem = Balanço caixa e depósitos')
 except ValueError as exc:
  if 'não importado' in str(exc):warnings.append(str(exc)+' Não foi possível confrontar o caixa e bancos com o Balanço.')
  else:raise
 if detected:warnings.append('Aplicações preenchidas e classificadas pelo utilizador; confirmar correspondência ao detalhe das contas 13 e respetiva maturidade.')
 warnings.append(f'Movimentos UTE: soma BA02 dos meses {month-2:02d} a {month:02d}/{year}; não usa o acumulado BA03.')
 return rows,warnings


def fill(content,kind,year,month,values):
 w=load_workbook(BytesIO(content));s=w['Formulário']
 from sisee_modelo_tipo import identificar_modelo
 if identificar_modelo(content)!=kind:raise ValueError('Modelo diferente do selecionado: '+kind)
 code=str(year*10000+(month//3)*10)
 cols=[c.column for c in s[6] if str(c.value)==code]
 if len(cols)!=1:raise ValueError('Coluna trimestral não encontrada no modelo.')
 col=cols[0]
 for row,v in values.items():
  cell=s.cell(row,col)
  if cell.data_type=='f' or cell.__class__.__name__=='MergedCell':raise ValueError('Não é possível substituir '+cell.coordinate)
  cell.value=float(v)
 out=BytesIO();w.save(out);return out.getvalue(),len(values)
