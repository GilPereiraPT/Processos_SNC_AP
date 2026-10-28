"""Classificação de contas por Pools, sem dupla contagem de contas hierárquicas."""
import csv
from pathlib import Path
import pandas as pd
from comparador import value

CATALOG = Path(__file__).with_name('mapa_pools.tsv')

def read_map(path=CATALOG):
    with open(path, encoding='utf-8-sig', newline='') as f:
        entries=list(csv.DictReader(f, delimiter='\t'))
    result={}
    for row in entries:
        code=row['Conta'].strip()
        if code and code in result:raise ValueError(f'Conta repetida no mapa: {code}')
        if code:result[code]={'designacao':row['Designação'].strip(),'tipo':row['Tipo'].strip(), 'pool1':row['Pool 1'].strip(), 'pool2':row['Pool 2'].strip()}
    return result

def terminal_codes(record):
    accounts=record.get('contas_balancete',{})
    codes=list(accounts)
    # Mesmo que a conta esteja marcada como M, não acumular se tem subcontas no PDF.
    return [c for c in codes if not any(other!=c and other.startswith(c) for other in codes)]

def resolve_pool(code, mapping):
    # Correspondência estrita do código; opcionalmente herdar classificação
    # apenas quando o código não consta do mapa e há ancestral classificado.
    item=mapping.get(code)
    if item and (item['pool1'] or item['pool2']):return item,code,'Exata'
    # Contas expressamente listadas sem classificação permanecem sem pool:
    # não inferir sem autorização do utilizador.
    return None,None,'Sem classificação'

def pool_details(record, mapping, measure='acumulado'):
    rows=[]
    for code in terminal_codes(record):
        item,origin,status=resolve_pool(code,mapping)
        amount=value(record,code,measure)
        account=record['contas_balancete'][code]
        rows.append({'Conta':code,'Designação':account.get('descricao') or mapping.get(code,{}).get('designacao',''),
                     'Pool 1':item['pool1'] if item else '', 'Pool 2':item['pool2'] if item else '',
                     'Valor (€)':amount, 'Estado':status})
    return pd.DataFrame(rows,columns=['Conta','Designação','Pool 1','Pool 2','Valor (€)','Estado'])

def pool_series(history,mapping,measure='acumulado',level='Pool 1'):
    rows=[]
    for period,rec in sorted(history.items()):
        if not rec.get('contas_balancete'):continue
        detail=pool_details(rec,mapping,'saldo' if measure=='saldo' else 'acumulado')
        if measure=='mensal':
            y,m=map(int,period.split('-'))
            if m!=1:
                previous=history.get(f'{y}-{m-1:02d}')
                if previous is None or not previous.get('contas_balancete'):continue
                prev=pool_details(previous,mapping,'acumulado').set_index('Conta')['Valor (€)']
                # Contas que surgiram/desapareceram entre dois balancetes devem
                # ser tratadas explicitamente, não convertidas a zero.
                detail['Valor (€)']=detail.apply(lambda r:round(r['Valor (€)']-prev[r['Conta']],2) if r['Conta'] in prev.index and pd.notna(r['Valor (€)']) and pd.notna(prev[r['Conta']]) else None,axis=1)
        grouped=detail[(detail[level]!='') & detail['Valor (€)'].notna()].groupby(level)['Valor (€)'].sum()
        for pool,amount in grouped.items():rows.append({'Período':period,'Pool':pool,'Valor (€)':round(float(amount),2)})
    return pd.DataFrame(rows,columns=['Período','Pool','Valor (€)'])
