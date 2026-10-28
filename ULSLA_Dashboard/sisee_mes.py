"""Atualiza unicamente as celulas de um mes de modelo SISEE carregado pelo utilizador.
Preserva folhas, formularios, cabecalhos, outros meses e formatos existentes.
Os valores monetarios sao numericos, nunca strings com virgula.
"""
from io import BytesIO
from decimal import Decimal
from openpyxl import load_workbook
from sisee_generator import ba_values, stored_extract, acquisition_from_extract, asset_from_xml
from sisee_dfcx import read_dfc, monthly_values, LINES, SUMMARIES

PMP_ROWS=(10,11,12,13,15,16,17,18,19,20,21)
PMP_AGREEMENTS=tuple(range(24,38))
PMP_MAP={15:['31'],16:['372'],17:['43'],18:['443','447'],19:['453'],20:['454']}
DFC_ROWS=set(LINES)|set(SUMMARIES)|{30,41,50,57}

def _set_number(sh,row,col,value):
    cell=sh.cell(row,col)
    if cell.data_type=='f':
        raise ValueError(f'A celula {cell.coordinate} contem uma formula e nao sera substituida.')
    if cell.__class__.__name__ == 'MergedCell':
        raise ValueError(f'A celula {cell.coordinate} pertence a uma regiao unida.')
    cell.value=float(Decimal(str(value)).quantize(Decimal('0.01')))
    # Manter a formatacao original do modelo, que ja tem #,##0.00.
    # O Excel em configuracao PT apresenta decimal com virgula.
    if cell.number_format in ('General','0'):
        cell.number_format='#,##0.00'

def atualizar_mes(model_bytes,kind,year,month,source='extratos'):
    if not 1<=month<=12:raise ValueError('Mês inválido.')
    wb=load_workbook(BytesIO(model_bytes))
    if 'Formulário' not in wb.sheetnames:raise ValueError('O ficheiro nao contem a folha Formulário.')
    sh=wb['Formulário'];warnings=[]; count=0
    if kind=='DFCx':
        obj,path=read_dfc(year,month)
        if obj is None:raise ValueError(f'DFC XML de {year}-{month:02d} ainda não está disponível no Dashboard Financeiro.')
        vals=monthly_values(obj)
        col=month+3  # C=ano anterior, D=janeiro
        for row in sorted(DFC_ROWS):
            if row in vals:
                _set_number(sh,row,col,vals[row]);count+=1
            else:warnings.append(f'DFCx: rubrica da linha {row} não encontrada; mantido valor original.')
    elif kind=='PMP':
        vals,notes=ba_values(year,month)
        if 'BA em falta' in notes:raise ValueError(f'BA XML de {year}-{month:02d} em falta.')
        warnings.extend(notes)
        extrato=stored_extract(year)
        for row,prefixes in PMP_MAP.items():
            vals[row]=acquisition_from_extract(extrato,year,month,prefixes)
        if source=='xml_aft':
            v=asset_from_xml(year,month)
            if v is not None:
                vals[17]=v
                warnings.append('AFT: confirmar que o total de adições corresponde à linha 17.')
            else:warnings.append('AFT não encontrado: utilizada conta 43 do extrato, se disponível.')
        col=month+2  # C=janeiro
        for row in PMP_ROWS:
            if vals.get(row) is not None:
                _set_number(sh,row,col,vals[row]);count+=1
            else:warnings.append(f'PMP: linha {row} sem fonte; mantido valor original.')
        for row,parts in ((14,[10,11,12,13]),(22,[15,16,17,18,19,20,21])):
            if all(vals.get(r) is not None for r in parts):
                _set_number(sh,row,col,sum((Decimal(str(vals[r])) for r in parts),Decimal('0')));count+=1
            else:warnings.append(f'PMP: total da linha {row} não alterado porque há componentes em falta.')
        # Linha 9 não tem correspondência segura: preservar, não inventar.
        warnings.append('PMP: linha 9 preservada; validar o âmbito dos valores totais.')
        for row in PMP_AGREEMENTS:
            _set_number(sh,row,col,0);count+=1
    else:raise ValueError('Tipo de formulário desconhecido.')
    out=BytesIO();wb.save(out)
    return out.getvalue(),warnings,count
