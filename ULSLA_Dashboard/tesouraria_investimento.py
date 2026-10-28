"""Comparações DFC/AFT/AI em resultados preparados, sem somar resumos e detalhe."""
from pathlib import Path
from decimal import Decimal
import gzip,json
from analise_executiva import number,variation

DFC_SUMMARY={'operacional':'DFCX02','investimento':'DFCX03','financiamento':'DFCX04','caixa_final':'DFCX10'}
DFC_DETAIL={'fornecedores_pagamentos':'DFC04','pessoal_pagamentos':'DFC05'}


def source_names(period):
    y,m=map(int,period.split('-'))
    months=(12,13,14) if m==12 else (m,)
    return [f'dados_s3cp_xml/{year}-{month:02d}/{kind}.json.gz'
            for year in (y-1,y) for month in months for kind in ('DFC','AFT','AI')]


def load(root,period,kind):
    y,m=map(int,period.split('-'))
    candidates=[]
    for month in ((12,13,14) if m==12 else (m,)):
        p=Path(root)/'dados_s3cp_xml'/f'{y}-{month:02d}'/(kind+'.json.gz')
        if p.is_file():
            obj=json.load(gzip.open(p,'rt',encoding='utf8'))
            # Mesma prioridade do catálogo: pasta canónica, depois último fecho.
            original=int(str(obj.get('periodo_original',f'{y}-{month:02d}')).split('-')[-1])
            candidates.append((100*(month==m)+original,obj))
    return max(candidates,key=lambda item:item[0])[1] if candidates else None


def leaf_rows(rows):
    """AFT/AI: uma rubrica observada uma vez; não adicionar pai às filhas."""
    codes=[str(r.get('Rubrica','')) for r in rows]
    if not all(codes) or len(set(codes))!=len(codes):return None
    return [r for r in rows if not any(c!=r['Rubrica'] and c.startswith(r['Rubrica']) for c in codes)]


def summed(rows,key,select=None):
    if not rows:return None
    rows=leaf_rows(rows)
    if rows is None:return None
    chosen=[r for r in rows if select is None or select(r['Rubrica'])]
    if not chosen or any(number(r.get(key)) is None for r in chosen):return None
    return float(sum((Decimal(str(r[key])) for r in chosen),Decimal(0)))


def asset_metrics(obj,kind):
    name='AtivosFixosTangiveis' if kind=='AFT' else 'AtivosIntangiveis'
    code='AFT38' if kind=='AFT' else 'AI7'
    sections=(obj or {}).get('especiais',{})
    balances=sections.get(name,{}).get('registos',[])
    additions=sections.get(name+'DesagregacaoAdicoes',{}).get('registos',[])
    return {'compras':summed(additions,'Compra'),
            'compras_curso':summed(additions,'Compra',lambda c:c==code),
            'curso_liquido':summed(balances,'QuantiaEscrituradaFinal',lambda c:c==code),
            'final_liquido':summed(balances,'QuantiaEscrituradaFinal')}


def dfc_metrics(record,obj,prior_column=False):
    observed=record.get('dfc',{})
    column='TotalAnoAnterior' if prior_column else 'TotalAnoCorrente'
    value_col='ValorAnoAnterior' if prior_column else 'ValorAnoCorrente'
    out={}
    for key,code in DFC_SUMMARY.items():
        rows=[r for r in (obj or {}).get('resumo',[]) if r.get('RubricaAgregadora')==code]
        fallback=number(rows[0].get(column)) if len(rows)==1 else None
        out[key]=number(observed.get(key)) if key in observed else fallback
    for key,code in DFC_DETAIL.items():
        rows=[r for r in (obj or {}).get('registos',[]) if r.get('Rubrica')==code]
        fallback=number(rows[0].get(value_col)) if len(rows)==1 else None
        out[key]=number(observed.get(key)) if key in observed else fallback
    return out


def collect(data,period,root):
    y,m=map(int,period.split('-'));prior=f'{y-1}-{m:02d}'
    current=data.get(period,{})
    previous=data.get(prior) or {'dfc':current.get('dfc_n1',{})}
    dfc=load(root,period,'DFC');old_dfc=load(root,prior,'DFC')
    a=dfc_metrics(previous,old_dfc or dfc,prior_column=not bool(old_dfc))
    b=dfc_metrics(current,dfc)
    assets={}
    for key in (prior,period):
        assets[key]={kind:asset_metrics(load(root,key,kind),kind) for kind in ('AFT','AI')}
    def card(title,a,b,kind,scope,source):
        delta,pct=variation(a,b)
        return {'Nome':title,'N-1':a,'N':b,'Diferença':delta,'Percentagem':pct,
                'Natureza':kind,'Âmbito':scope,'Fonte':source}
    dfc_cards=[card(title,a.get(key),b.get(key),'fluxo' if key!='caixa_final' else 'saldo',scope,'DFC') for title,key,scope in [
        ('Fluxo operacional','operacional','Fluxo acumulado'),
        ('Fluxo de investimento','investimento','Fluxo acumulado'),
        ('Fluxo de financiamento','financiamento','Fluxo acumulado'),
        ('Pagamentos a fornecedores','fornecedores_pagamentos','Saída de caixa acumulada'),
        ('Pagamentos ao pessoal','pessoal_pagamentos','Saída de caixa acumulada'),
        ('Caixa no fim do período','caixa_final','Saldo à data')]]
    specs=[('Compras de ativos tangíveis','AFT','compras','Compras acumuladas'),
           ('Compras de ativos intangíveis','AI','compras','Compras acumuladas'),
           ('Compras para tangíveis em curso','AFT','compras_curso','Incluídas nas compras de tangíveis'),
           ('Tangíveis em curso','AFT','curso_liquido','Saldo líquido à data · inclui obras'),
           ('Intangíveis em curso','AI','curso_liquido','Saldo líquido à data')]
    asset_cards=[card(title,assets[prior][kind][field],assets[period][kind][field],
                'saldo' if field=='curso_liquido' else 'aquisição',scope,kind) for title,kind,field,scope in specs]
    def combined(key):
        vals=[assets[key][k]['final_liquido'] for k in ('AFT','AI')]
        return sum(vals) if all(v is not None for v in vals) else None
    asset_cards.append(card('Tangíveis e intangíveis · total líquido',combined(prior),combined(period),
                            'saldo','Saldo líquido à data · em uso e em curso','AFT + AI'))
    return {'dfc':dfc_cards,'ativos':asset_cards,
        'nota_dfc':'Fluxos acumulados com os sinais da DFC; caixa final é um saldo à data.',
        'nota_ativos':'As compras dos mapas de ativos são aquisições reconhecidas, não pagamentos. Os saldos em curso incluem obras e outros investimentos. As compras para tangíveis em curso já integram as compras totais de tangíveis.'}
