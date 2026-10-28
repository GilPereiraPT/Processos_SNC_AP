"""Interpretação local e reconciliações auditáveis do sumário executivo."""
from pathlib import Path
from decimal import Decimal
import json, gzip, math, os, tempfile

VERSION = 2

def number(v):
    try:
        n = float(v)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None

def money(v):
    v = number(v)
    return 'indisponível' if v is None else f'{v/1e6:,.2f} M€'.replace(',', '§').replace('.', ',').replace('§', '.')

def variation(a, b):
    a, b = number(a), number(b)
    if a is None or b is None: return None, None
    return b-a, (b-a)/abs(a)*100 if a else None

def comparison(name, a, b, scope='acumulado'):
    a, b = number(a), number(b)
    if b is None: return f'{name} ({scope}): dados indisponíveis.'
    d, p = variation(a,b)
    text = f'{name} ({scope}): {money(b)}'
    if d is None: return text + '; comparação homóloga indisponível.'
    text += f'; variação homóloga de {money(d)}'
    return text + (f' ({p:+.1f}%)'.replace('.', ',') if p is not None else ' (percentagem não calculável: base homóloga zero)') + '.'

def _net(items, dkey, ckey):
    total = Decimal('0')
    for row in items:
        if number(row.get(dkey)) is None or number(row.get(ckey)) is None: return None
        total += Decimal(str(row[ckey])) - Decimal(str(row[dkey]))
    return float(total)

def account_27892(rec, root=None, period=None):
    """Preferir a conta exata do balancete; nunca juntar mãe e filhas.
    No BA, somar dimensões da mesma conta e excluir pais quando há filhas.
    BA04 são saldos finais; não somar BA01/02/03 ao saldo.
    """
    codes = {str(k).replace('.','').replace(' ',''): v for k,v in rec.get('contas_balancete',{}).items() if str(k).replace('.','').replace(' ','').startswith('27892')}
    pdf = None
    if '27892' in codes:
        pdf = _net([codes['27892']], 'saldo_devedor','saldo_credor')
    ba = None
    if root is not None and period:
        path = Path(root)/'dados_s3cp_xml'/period/'BA.json.gz'
        if path.exists():
            obj = json.load(gzip.open(path,'rt',encoding='utf8'))
            rows = [(str(r.get('ContaLocal','')).replace('.','').replace(' ',''),r) for r in obj.get('registos',[])]
            rows = [(c,r) for c,r in rows if c.startswith('27892')]
            leaves = {c for c,r in rows if not any(k!=c and k.startswith(c) for k,_ in rows)}
            amounts = [r.get('detalhes',{}).get('BA04',{}) for c,r in rows if c in leaves]
            if amounts: ba = _net(amounts,'Debito','Credito')
    if pdf is not None:
        value,source = pdf, 'Balancete: saldo da conta 27892 (sem adicionar subcontas)'
    elif ba is not None:
        value,source = ba, 'BA XML: saldos finais BA04 de contas terminais 27892'
    elif codes:
        leaves = [v for c,v in codes.items() if not any(k!=c and k.startswith(c) for k in codes)]
        value = _net(leaves,'saldo_devedor','saldo_credor')
        source = 'Balancete: subcontas terminais 27892; agregadora indisponível'
    else: value,source = None, 'Conta 27892 indisponível no BA/balancete'
    mismatch = pdf is not None and ba is not None and abs(pdf-ba) > .02
    if mismatch:
        value = None
        source = 'Divergência entre BA e balancete da conta 27892; total indisponível até conferência'
    return {'saldo_liquido':value,'saldo_credor_liquido':max(value,0) if value is not None else None,
            'fonte':source,'balancete':pdf,'ba':ba,'divergencia':mismatch}

def accounting(rec, root=None, period=None):
    b = rec.get('balanco',{})
    a,c = number(b.get('fornecedores')),number(b.get('fornecedores_investimento'))
    acc = account_27892(rec,root,period)
    base = a+c if a is not None and c is not None else None
    extra = acc['saldo_credor_liquido']
    return {'fornecedores':a,'imobilizado':c,'base_balanco':base,'conta_27892':acc,
            'total':base+extra if base is not None and extra is not None else None}

def enrich(info, current, previous, cards_previous, monthly_cards, root):
    info['cards_prior'] = cards_previous
    info['monthly_cards'] = monthly_cards
    info['contabilistica'] = accounting(current,root,info['period'])
    info['cards']['Dívida a fornecedores'] = info['contabilistica']['total']
    info['balanco_atual'] = current.get('balanco',{})
    info['balanco_anterior'] = (previous or {}).get('balanco',{})
    info['pessoal_dr'] = current.get('dr',{}).get('pessoal')
    dr = number(info['pessoal_dr']); rem = number(info.get('remuneracoes',{}).get('total'))
    info['pessoal_restante'] = dr-rem if dr is not None and rem is not None else None
    # Conta 63 fora das três rubricas remuneratórias, com valores observados.
    from pools import pool_details
    from visao_executiva import REMUNERATION_GROUPS
    from pools import read_map
    detail = pool_details(current,read_map())
    rest=[]
    if not detail.empty:
        subset=detail[detail['Conta'].str.startswith('63') & ~detail['Pool 1'].isin(REMUNERATION_GROUPS)]
        rest=[{'Conta':r['Conta'],'Nome':r['Designação'],'Valor':number(r['Valor (€)'])} for _,r in subset.iterrows()]
    info['pessoal_restante_contas']=rest
    return info

def reconciliation(info):
    a = info.get('contabilistica',{})
    d = info.get('debt')
    doc = d.get('total') if d else None
    total = a.get('total')
    return {'Dívida documental (P1 + P2 + NC)':doc,
            'Fornecedores - Balanço':a.get('fornecedores'),
            'Fornecedores de imobilizado - Balanço':a.get('imobilizado'),
            'Subtotal fornecedores - Balanço':a.get('base_balanco'),
            '27892 - saldo credor líquido':a.get('conta_27892',{}).get('saldo_credor_liquido'),
            'Dívida contabilística a fornecedores':total,
            'Diferença documental menos contabilística':doc-total if doc is not None and total is not None else None}

def narratives(info, pmp):
    """Só resultados preparados; nenhuma chamada externa e nenhuma causa inferida."""
    out=[]
    def add(title,text):out.append({'titulo':title,'texto':text})
    c=info['cards']; old=info.get('cards_prior',{})
    text=' '.join(comparison(n,old.get(n),c.get(n)) for n in ['Rendimentos','Gastos','Resultado líquido'])
    dr,_=variation(old.get('Rendimentos'),c.get('Rendimentos')); dg,_=variation(old.get('Gastos'),c.get('Gastos'))
    if dr is not None and dg is not None and dg>dr:
        text+=' O aumento absoluto dos gastos foi superior à variação dos rendimentos.'
    change,_=variation(old.get('Resultado líquido'),c.get('Resultado líquido'))
    if change is not None:
        text+=' O resultado líquido '+('agravou-se em ' if change<0 else 'melhorou em ' if change>0 else 'manteve-se: ')+money(abs(change))+'.'
    add('Resultados e comparação homóloga',text)
    monthly=info.get('monthly_cards',{})
    add('Resultados do mês',' '.join(comparison(n,monthly.get('prior',{}).get(n),monthly.get('current',{}).get(n),'mensal') for n in ['Rendimentos','Gastos','Resultado líquido']))
    rows=[r for r in info.get('dr',[]) if r['Nome'] in ('Consumos','FSE','Gastos com pessoal','Outros gastos','Depreciações') and r.get('Diferença') is not None]
    rows.sort(key=lambda r:abs(r['Diferença']),reverse=True)
    text=' '.join(comparison(r['Nome'],r['N-1'],r['N']) for r in rows[:3]) or 'Comparações acumuladas indisponíveis.'
    monthly_rows=[r for r in info.get('gastos',{}).get('rubricas',[]) if number(r.get('Diferença')) is not None]
    monthly_rows.sort(key=lambda r:abs(r['Diferença']),reverse=True)
    text+=' '+(' '.join(comparison(r['Nome'],r['N-1'],r['N'],'mensal') for r in monthly_rows[:3]) or 'Variações mensais por grupo indisponíveis.')
    add('Principais variações dos gastos',text)
    row=next((r for r in info['dr'] if r['Nome']=='Gastos com pessoal'),{})
    text=comparison('Gastos com pessoal na DR',row.get('N-1'),row.get('N'))+' '+comparison('Gastos com pessoal na DR',monthly.get('prior',{}).get('Pessoal'),monthly.get('current',{}).get('Pessoal'),'mensal')
    text+=f" O subtotal de remunerações e encargos classificado no balancete é {money(info.get('remuneracoes',{}).get('total'))}; a parcela restante face à DR é {money(info.get('pessoal_restante'))}."
    rest=info.get('pessoal_restante_contas',[])
    if rest and all(r['Valor'] is not None for r in rest):
        text+=' A composição da parcela restante é identificada por conta no anexo de pessoal e na reconciliação do Excel.'
        diff=info.get('pessoal_restante')
        if diff is not None and abs(diff-sum(r['Valor'] for r in rest))>.02:
            text+=' O detalhe disponível não reconcilia integralmente a parcela restante.'
    else:text+=' A composição da parcela restante não está demonstrada nos dados disponíveis.'
    add('Pessoal',text)
    contract='Serviços Saúde - Contrato Programa'
    for title,select in [('Contrato Programa',lambda n:n==contract),('Rendimentos extra Contrato Programa',lambda n:n!=contract)]:
        parts=[]
        for scope,rows in [('acumulado',info.get('rendimentos_contribuintes',[])),('mensal',info.get('rendimentos',{}).get('rubricas',[]))]:
            rows=[r for r in rows if select(r['Nome'])]
            def total(k):return sum(r[k] for r in rows) if rows and all(number(r.get(k)) is not None for r in rows) else None
            parts.append(comparison(title,total('N-1'),total('N'),scope))
        add(title,' '.join(parts))
    b=info.get('balanco_atual',{}); a=info.get('balanco_anterior',{})
    text=' '.join(comparison(name,a.get(k),b.get(k),'saldo à data') for name,k in [('Ativo','ativo'),('Passivo','passivo'),('Outras contas a receber','outras_contas_receber'),('Adiantamentos de clientes','adiantamentos_clientes')])
    ac,pc=number(b.get('ativo_corrente')),number(b.get('passivo_corrente'))
    text+=(' Liquidez corrente: '+f'{ac/pc:.2f}'.replace('.',',')+'.' if ac is not None and pc is not None and pc else ' Liquidez corrente indisponível (dados em falta ou passivo corrente zero).')
    add('Balanço e liquidez',text)
    valid=[r for r in pmp if number(r[1]) is not None]
    text='PMP indisponível.'
    if valid:
        text=f"O PMP em {valid[-1][0]} foi de {str(round(valid[-1][1],1)).replace('.',',')} dias."
        if len(valid)>1:text+=f" Variação face a {valid[-2][0]}: {format(valid[-1][1]-valid[-2][1],'+.1f').replace('.',',')} dias."
        text+=' O prazo de pagamento e o stock de dívida são indicadores distintos.'
    add('Prazo médio de pagamento',text)
    d=info.get('debt'); ac=info.get('contabilistica',{})
    text=f"A dívida a fornecedores totaliza {money(ac.get('total'))}."
    if d:
        text+=f" A dívida documental totaliza {money(d['total'])} e inclui também descontos e encargos associados aos vencimentos. Estes totais têm perímetros distintos."
        for sector,rows in d.get('rankings',{}).items():
            den=next((r['Valor'] for r in d['sector'] if r['Nome']==sector),None)
            top=sum(r['Valor'] for r in rows)
            pct=top/den*100 if den is not None and den>0 else None
            text+=f' {sector}: os {len(rows)} maiores credores somam {money(top)}'+((' ('+f'{pct:.1f}'.replace('.',',')+'% do setor).') if pct is not None else ' (percentagem indisponível).')
    else:text+=' A informação de dívida documental não está disponível para este período.'
    add('Estrutura e concentração da dívida',text)
    return out

def comment_path(root, period):
    from resultados_preparados import path_for
    path_for(root,period,'executivo') # valida o período
    return Path(root)/'comentarios_gestao'/(period+'.json')

def read_comment(root, period):
    path=comment_path(root,period)
    if not path.exists():return ''
    # Erros não são silenciados para evitar substituir um comentário corrompido.
    return json.loads(path.read_text(encoding='utf8'))['comentario']

def save_comment(root, period, text):
    path=comment_path(root,period);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,suffix='.tmp')
    try:
        with os.fdopen(fd,'w',encoding='utf8') as f:
            json.dump({'periodo':period,'comentario':str(text)},f,ensure_ascii=False)
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
