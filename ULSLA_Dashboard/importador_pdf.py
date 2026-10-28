"""Importação SNC-AP: leitura por geometria de PDFs de texto (não OCR)."""
import re, hashlib, io
from datetime import date
import fitz

NUMBER=re.compile(r'^-?\d{1,3}(?:\.\d{3})*,\d{2}€?$|^-?\d+,\d{2}€?$')
MONTHS={'JANEIRO':1,'FEVEREIRO':2,'MARÇO':3,'MARCO':3,'ABRIL':4,'MAIO':5,'JUNHO':6,'JULHO':7,'AGOSTO':8,'SETEMBRO':9,'OUTUBRO':10,'NOVEMBRO':11,'DEZEMBRO':12}
MAP={
 'dr':{
'rendimentos_impostos':'Impostos, contribuições e taxas','vendas':'Vendas','prestacoes_servicos':'Prestações de serviços e concessões',
 'transferencias':'Transferências e subsídios correntes obtidos','outros_rendimentos':'Outros rendimentos',
 'consumos':'Custo das mercadorias vendidas','fse':'Fornecimentos e serviços externos','pessoal':'Gastos com pessoal',
 'outros_gastos':'Outros gastos','ebitda':'Resultados antes de depreciações','depreciacoes':'Gastos/reversões de depreciação',
 'operacional':'Resultado operacional (antes','resultado':'Resultado líquido do período',
 'imparidade_inventarios':'Imparidade de inventários e ativos biológicos',
 'imparidade_receber':'Imparidade de dívidas a receber',
 'provisoes':'Provisões (aumentos/reduções)',
 'imparidade_investimentos_nao_depreciaveis':'Imparidade de investimentos não depreciáveis/amortizáveis',
 'justo_valor':'Aumentos/reduções de justo valor',
 'imparidade_investimentos_depreciaveis':'Imparidade de investimentos depreciáveis/amortizáveis',
 'imposto_rendimento':'Imposto sobre o rendimento',
 'juros_obtidos':'Juros e rendimentos similares obtidos','juros_suportados':'Juros e gastos similares suportados'},
 'balanco':{
 'ativo_corrente':'Ativo corrente','ativo_nao_corrente':'Ativo não corrente','inventarios':'Inventários',
 'clientes':'Clientes, contribuintes e utentes','outras_contas_receber':'Outras contas a receber',
 'caixa':'Caixa e depósitos','passivo_corrente':'Passivo corrente','passivo_nao_corrente':'Passivo não corrente',
 'fornecedores':'Fornecedores','fornecedores_investimento':'Fornecedores de investimentos',
 'adiantamentos_clientes':'Adiantamentos de clientes, contribuintes e utentes',
 'outras_contas_pagar':'Outras contas a pagar', 'ativos_fixos':'Ativos fixos tangíveis',
 'patrimonio_resultado':'Resultado líquido do período', 'patrimonio':'Total Património Líquido',
 'ativo':'Total Ativo','passivo':'Total Passivo'},
 'dfc':{
 'clientes_recebimentos':'Recebimentos de clientes','utentes_recebimentos':'Recebimentos de utentes',
 'fornecedores_pagamentos':'Pagamentos a fornecedores','pessoal_pagamentos':'Pagamentos ao pessoal',
 'operacional':'Fluxos de caixa das atividades operacionais (a)',
 'investimento':'Fluxos de caixa das atividades de investimento (b)',
 'financiamento':'Fluxos de caixa das atividades de financiamento (c)',
 'cobertura_prejuizos':'Cobertura de prejuízos', 'variacao_caixa':'Variação de caixa e seus equivalentes',
 'caixa_inicial':'Caixa e seus equivalentes no início do período',
 'caixa_final':'Caixa e seus equivalentes no fim do período',
 'subsidios_investimento':'Subsídios ao investimento'} }
# A identificação por código de conta é independente das descrições (frequentemente truncadas).
ACCOUNTS={'igcp_aumento_capital':'1214','igcp_prr':'1215','igcp_hla':'1211',
 'fornecedores_factoring':'226','fornecedores_recepcao':'225',
 'acrescimos_rendimentos_acss':'2721911','adiantamentos_cp_2026':'218157',
 'investimentos_curso':'45','servicos_medicos_empresas':'6221911',
 'honorarios_medicos':'622491','transporte_doentes':'6255',
 'medicamentos_farmacias':'621131','medicamentos_consumo':'612411',
 'subcontratos_saude':'6211'}
NEEDED={ 'dr':['resultado','fse','pessoal','prestacoes_servicos'],
 'balanco':['ativo','passivo','patrimonio','caixa','fornecedores','patrimonio_resultado'],
 'dfc':['operacional','investimento','financiamento','variacao_caixa','caixa_final'],
 'balancete':['igcp_aumento_capital','igcp_hla','fornecedores_factoring']}

def decimal(s):return float(s.replace('€','').replace('.','').replace(',','.').strip())
def pdf_words(blob):
 doc=fitz.open(stream=blob,filetype='pdf')
 if doc.page_count>100:raise ValueError('PDF com número excessivo de páginas')
 pages=[]
 for page in doc:
  pages.append(page.get_text('words',sort=True))
 if not sum(len(x) for x in pages):raise ValueError('PDF sem texto selecionável; necessita de exportação SNC-AP com texto')
 return doc,pages

def rows(words):
 """Linhas por abcissa vertical, com separação de células pelo início da coluna."""
 bucket={}
 for x0,y0,x1,y1,word,*_ in words:
  ky=round(y0,1)
  bucket.setdefault(ky,[]).append((x0,word))
 out=[]
 for y,arr in sorted(bucket.items()):
  if out and y-out[-1][0]<=3.1:
   out[-1][1].extend(arr)
  else:out.append((y,arr.copy()))
 for y,arr in out:arr.sort()
 return out

def collect_statement(pages,kind):
 entries=[]
 for words in pages:
  for y,arr in rows(words):
   left=' '.join(t for x,t in arr if x<410).strip()
   n=[(x,t) for x,t in arr if x>=405 and NUMBER.fullmatch(t)]
   # Valores coluna N à esquerda de N-1 (distinguir por abcissa)
   values=[decimal(t) for x,t in sorted(n) if x<515]
   prev=[decimal(t) for x,t in sorted(n) if x>=515]
   if left and values:entries.append((left,values[0],prev[0] if prev else None))
 extracted={};prior={};missing=[]
 for code,match in MAP[kind].items():
  opts=[(l,n,p) for l,n,p in entries if l.casefold().startswith(match.casefold())]
  if kind=='balanco':
   if code=='patrimonio':opts=[(l,n,p) for l,n,p in entries if l.casefold().startswith('total património líquido') and 'passivo' not in l.casefold()]
   elif code=='passivo':opts=[(l,n,p) for l,n,p in entries if l.casefold().startswith('total passivo')]
   elif code=='ativo':opts=[(l,n,p) for l,n,p in entries if l.casefold().startswith('total ativo')]
   elif code=='fornecedores':opts=[(l,n,p) for l,n,p in entries if l.strip().casefold()=='fornecedores']
   elif code=='clientes':opts=opts[-1:] # no ativo corrente
   elif code=='outras_contas_receber':opts=opts[-1:]
   elif code=='outras_contas_pagar':opts=opts[-1:] # passivo corrente
   elif code=='ativos_fixos':opts=opts[:1]
  if kind=='dfc' and code in ('caixa_inicial','caixa_final'):opts=opts[:1]
  if opts:
   l,n,p=opts[-1];extracted[code]=abs(n) if kind=='dr' and code in ('consumos','fse','pessoal','outros_gastos','depreciacoes') else n
   if p is not None: prior[code]=abs(p) if kind=='dr' and code in ('consumos','fse','pessoal','outros_gastos','depreciacoes') else p
  elif code not in ('juros_obtidos','juros_suportados','imparidade_inventarios','imparidade_receber','provisoes','imparidade_investimentos_nao_depreciaveis','justo_valor','imparidade_investimentos_depreciaveis','imposto_rendimento'):missing.append(code)
 if kind=='dr':
  if 'juros_obtidos' in extracted or 'juros_suportados' in extracted:
   extracted['financeiros']=extracted.pop('juros_obtidos',0)+extracted.pop('juros_suportados',0)
   prior['financeiros']=prior.pop('juros_obtidos',0)+prior.pop('juros_suportados',0)
 return extracted,prior,missing,entries

def collect_ledger(pages):
 accounts={}
 for words in pages:
  for y,arr in rows(words):
   codes=[s for x,s in arr if x<95 and re.fullmatch(r'\d{1,12}',s)]
   if not codes:continue
   code=codes[0]
   # Balancete: colunas D entre datas ~285, C ~374, D acumulado ~465, C ~554, saldo D ~634, C ~723
   vals=[]
   for low,high in [(270,365),(365,455),(455,545),(545,630),(630,719),(719,830)]:
    matched=[t for x,t in arr if low<=x<high and NUMBER.fullmatch(t)]
    vals.append(decimal(matched[-1]) if matched else None)
   desc=' '.join(t for x,t in arr if 95<=x<270)
   if vals[4] is not None and vals[5] is not None:
    accounts[code]={'descricao':desc,'debito_periodo':vals[0], 'credito_periodo':vals[1],
      'debito_acumulado':vals[2],'credito_acumulado':vals[3],
      'saldo_devedor':vals[4], 'saldo_credor':vals[5]}
 picked={}
 for key,code in ACCOUNTS.items():
  if code in accounts:
   a=accounts[code];picked[key]=round(a['saldo_devedor']-a['saldo_credor'],2)
   if a['saldo_credor']>a['saldo_devedor']:picked[key]=a['saldo_credor']
  else:
   # Conta ausente do balancete: assumir saldo nulo, sem bloquear o fecho.
   picked[key]=0.0
 return picked,accounts,[key for key,code in ACCOUNTS.items() if code not in accounts]

def identify(doc,text):
 if 'SNCAP_DR' in text:return 'dr'
 if 'SNCAP_BLC' in text:return 'balanco'
 if 'SNCAP_DFC' in text:return 'dfc'
 if 'LISTAGEM_BALANCETES' in text:return 'balancete'
 raise ValueError('Documento não reconhecido como DR, Balanço, DFC ou Balancete SNC-AP')

def period(doc,kind):
 txt='\n'.join(p.get_text()[:1600] for p in doc)
 if kind!='balancete':
  dates=re.findall(r'\b(\d{2})-(\d{2})-(20\d{2})\b',txt)
  # Data de geração precede datas do período: escolher a última data (data fim) em primeira página
  if len(dates)<2:raise ValueError('Não foi possível identificar a data fim')
  d,m,y=dates[-1]
  if not 1<=int(m)<=12:raise ValueError('Data fim inválida')
  return f'{y}-{m}'
 m=re.search(r'\b(20\d{2})\s*\n\s*([A-ZÇÃÉ]+)\s*\n\s*([A-ZÇÃÉ]+)',txt)
 if m:
  yr,_,last=m.groups();month=MONTHS.get(last)
 else:
  yrm=re.search(r'\b20\d{2}\b',txt);yr=yrm.group(0) if yrm else None
  months=[(txt.upper().find(k),v) for k,v in MONTHS.items() if k in txt.upper()];month=max(months)[1] if months else None
 if not yr or not month:raise ValueError('Não foi possível identificar mês/ano do balancete')
 return f'{yr}-{month:02d}'

def parse_file(blob,filename):
 doc,pages=pdf_words(blob)
 head=' '.join(doc[i].get_text()[:500] for i in range(min(2,len(doc))))
 kind=identify(doc,head);per=period(doc,kind)
 if kind=='balancete':
  values,accounts,missing=collect_ledger(pages); prior={};detail=accounts
 else:
  values,prior,missing,detail=collect_statement(pages,kind)
 return {'tipo':kind,'periodo':per,'valores':values,'homologo':prior,'em_falta':missing,
  'detalhe':detail if kind=='balancete' else [],'ficheiro':filename,'sha256':hashlib.sha256(blob).hexdigest(),
  'paginas':len(doc)}

def validate_bundle(files):
 if len(files)!=4:raise ValueError('É obrigatório carregar exatamente quatro PDFs')
 parsed=[parse_file(f.read(),f.name) for f in files]
 kinds=[x['tipo'] for x in parsed];periods={x['periodo'] for x in parsed}
 if set(kinds)!=set(['dr','balanco','dfc','balancete']) or len(set(kinds))!=4:raise ValueError('Os ficheiros devem conter exatamente uma DR, um Balanço, uma DFC e um Balancete')
 if len(periods)!=1:raise ValueError('Os quatro documentos não correspondem ao mesmo mês: '+', '.join(sorted(periods)))
 missing={p['tipo']:[k for k in NEEDED[p['tipo']] if k not in p['valores']] for p in parsed}
 obj={'periodo':parsed[0]['periodo'],'origem':'Importação automática de quatro PDF SNC-AP',
  'natureza':'DR/DFC: acumulados a confirmar; Balanço/Balancete: saldos no fim do mês',
  'documentos':[{k:p[k] for k in ['tipo','periodo','ficheiro','sha256','paginas']} for p in parsed]}
 for p in parsed:
  obj[p['tipo']]=p['valores'];
  if p['homologo']:obj[p['tipo']+'_n1']=p['homologo']
  if p['tipo']=='balancete':obj['contas_balancete']=p['detalhe']
 return obj,missing,parsed
