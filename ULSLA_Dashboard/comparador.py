"""Comparação histórica de contas SNC-AP, com proteção contra períodos em falta."""
import pandas as pd

COLUMNS = {'saldo':'Saldo líquido à data (D−C)', 'acumulado':'Movimento líquido acumulado (D−C)', 'mensal':'Movimento líquido do mês (D−C)'}

def account_names(history):
    names={}
    for period,record in sorted(history.items()):
        for code,info in record.get('contas_balancete',{}).items():
            desc=str(info.get('descricao') or '').strip()
            if code not in names or len(desc)>len(names[code]):names[code]=desc
    return names

def value(record,code,measure):
    item=record.get('contas_balancete',{}).get(code)
    if item is None:return None
    if measure=='saldo':
        a,b=item.get('saldo_devedor'),item.get('saldo_credor')
    elif str(code).replace('.', '').startswith(('6', '7')) and (
        'debito_acumulado' in item and 'credito_acumulado' in item
    ):
        # Nas contas de resultados, usar o acumulado anual, incluindo acertos.
        # Em dezembro, as colunas entre datas podem conter apenas o fecho.
        # Não substituir acumulados ausentes/nulos por movimentos parciais.
        a,b=item.get('debito_acumulado'),item.get('credito_acumulado')
    else:
        # Compatibilidade com registos antigos e movimento das outras classes:
        # no PDF, o acumulado dessas classes também inclui saldos de abertura.
        a,b=item.get('debito_periodo'),item.get('credito_periodo')
    return round(float(a)-float(b),2) if a is not None and b is not None else None

def series(history,codes,measure):
    """Devolve observações verificadas; 'mensal' só calcula com fecho anterior existente.
    O campo entre datas do balancete de janeiro a setembro é movimento acumulado.
    """
    result=[]
    for p,record in sorted(history.items()):
        for code in codes:
            current=value(record,code,'saldo' if measure=='saldo' else 'acumulado')
            if current is None:continue
            amount=current; status='Observado'
            if measure=='mensal':
                y,m=map(int,p.split('-'))
                if m==1:status='Janeiro (acumulado)'
                else:
                    previous=f'{y}-{m-1:02d}'
                    base=value(history.get(previous,{}),code,'acumulado')
                    amount=round(current-base,2) if base is not None else None
                    status='Calculado de fechos consecutivos' if base is not None else 'Indisponível: falta '+previous
            result.append({'Período':p,'Conta':code,'Valor (€)':amount,'Estado':status})
    return pd.DataFrame(result,columns=['Período','Conta','Valor (€)','Estado'])

def compare(history,codes,period_a,period_b,measure,names):
    s=series(history,codes,measure)
    rows=[]
    for code in codes:
        a=s[(s['Período']==period_a)&(s['Conta']==code)]
        b=s[(s['Período']==period_b)&(s['Conta']==code)]
        av=float(a.iloc[0]['Valor (€)']) if len(a) and pd.notna(a.iloc[0]['Valor (€)']) else None
        bv=float(b.iloc[0]['Valor (€)']) if len(b) and pd.notna(b.iloc[0]['Valor (€)']) else None
        delta=round(bv-av,2) if av is not None and bv is not None else None
        pct=round(delta/abs(av)*100,2) if delta is not None and av!=0 else None
        rows.append({'Conta':code,'Rubrica':names.get(code,''),period_a:av,period_b:bv,'Variação (€)':delta,'Variação (%)':pct})
    return pd.DataFrame(rows)
