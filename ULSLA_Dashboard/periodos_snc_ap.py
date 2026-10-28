"""Normalização: periodos contabilisticos 12, 13 e 14 = dezembro civil."""
import calendar,re
import pandas as pd
_MESES=("", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro")
_RE=re.compile(r'^(20\d{2})-(\d{1,2})$')
def parse_periodo(value):
    match=_RE.fullmatch(str(value))
    if not match:return None
    y,m=map(int,match.groups())
    return (y,min(m,12)) if 1<=m<=14 else None
def normalizar_periodo(value):
    part=parse_periodo(value)
    return f'{part[0]}-{part[1]:02d}' if part else str(value)
def prioridade_periodo(value):
    match=_RE.fullmatch(str(value))
    return int(match.group(2)) if match else 0
def periodo_legenda(value):
    part=parse_periodo(value)
    return f'{_MESES[part[1]]} de {part[0]}' if part else str(value)+' (período não reconhecido)'
def periodo_curto(value):
    part=parse_periodo(value)
    return f'{part[1]:02d}/{part[0]}' if part else str(value)
def referencia(value):
    part=parse_periodo(value)
    if not part:return 'Período contabilístico não reconhecido'
    y,m=part
    return f'{calendar.monthrange(y,m)[1]:02d}/{m:02d}/{y}'
def mes_civil(value):
    part=parse_periodo(value)
    return pd.Period(f'{part[0]}-{part[1]:02d}',freq='M') if part else None
