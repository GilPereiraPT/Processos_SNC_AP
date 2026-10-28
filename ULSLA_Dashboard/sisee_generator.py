"""SISEE PMP: ferramenta isolada para gerar formulário a partir dos dados ULSLA.
Regra local expressa: todas as aquisições em acumulado anual (contrária às instruções do modelo).
Não altera nem grava dados do dashboard.
"""
from pathlib import Path
import gzip, json, io
from decimal import Decimal
from collections import defaultdict

ROOT = Path(__file__).resolve().parent
BA_ROOT = ROOT / 'dados_s3cp_xml'
EX_ROOT = ROOT / 'dados_pmp_extratos'
NIF = '999999990'
ENTIDADE = '510445152'
DATA_ROWS = (10,11,12,13,15,16,17,18,19,20,21)
AGREEMENT_ROWS = tuple(range(24,38))
FORMAT_EUR = '#,##0.00 "€";[Red](#,##0.00 "€");0.00 "€"'


def period_obj(year,month,kind):
    for p in ([BA_ROOT / f'{year}-{suffix}' / f'{kind}.json.gz' for suffix in ('14','13','12')] if month==12 else [BA_ROOT / f'{year}-{month:02d}' / f'{kind}.json.gz']):
        if p.is_file():
            with gzip.open(p,'rt',encoding='utf-8') as handle: obj=json.load(handle)
            if str(obj.get('entidade')) != ENTIDADE:
                raise ValueError(f'Entidade inesperada no ficheiro {p}')
            return obj
    return None


def ba_saldo(obj, prefixes, debit=False, codigo_nif=NIF):
    if not obj:return None
    found=False; total=Decimal('0')
    for row in obj.get('registos',[]):
        if str(row.get('NIFEntidadeParceira','')) != codigo_nif:continue
        acc=''.join(ch for ch in str(row.get('ContaLocal','')) if ch.isdigit())
        if not any(acc.startswith(p) for p in prefixes):continue
        vals=row.get('detalhes',{}).get('BA04')
        if vals is None:continue
        found=True
        d=Decimal(str(vals.get('Debito',0)));c=Decimal(str(vals.get('Credito',0)))
        total+=d-c if debit else c-d
    return total if found else None


def ba_values(year,month):
    obj=period_obj(year,month,'BA')
    if obj is None:return {}, ['BA em falta']
    # Mapeamento adotado pelo PMP da ULSLA, não a totalidade indiscriminada das classes 22/271/278.
    mapping={10:(['221','222','225','226'],False),11:(['2513'],False),
             12:(['2711','2716'],False),13:(['278929'],False),21:(['62'],True)}
    vals={i:ba_saldo(obj,*v) for i,v in mapping.items()}
    # 2513 pode estar ausente porque não existe movimento/saldo: confirmar antes de assumir 0.
    return vals, ([] if vals.get(10) is not None and vals.get(21) is not None else ['BA incompleto nas contas principais'])


def stored_extract(year):
    path=EX_ROOT/f'extrato_{year}.csv.gz'
    if not path.is_file():return None
    import pandas as pd
    df=pd.read_csv(path,sep=';',compression='gzip',low_memory=False,dtype={'Conta':str,'Tipo':str})
    df['Data contabilização']=pd.to_datetime(df['Data contabilização'],errors='coerce')
    df=df.loc[df['Data contabilização'].notna() & df['Tipo'].astype(str).str.upper().ne('OD')].copy()
    df['ContaNormalizada']=df['Conta'].astype(str).str.replace('.','',regex=False).str.strip()
    df['Valor líquido (€)']=pd.to_numeric(df['Valor líquido (€)'],errors='coerce').fillna(0)
    return df


def acquisition_from_extract(df,year,month,prefixes):
    if df is None:return None
    # Acumulado no ano até ao mês de referência, apenas linhas importadas.
    m=df.loc[(df['Data contabilização'].dt.year==year)&(df['Data contabilização'].dt.month<=month)]
    m=m.loc[m['ContaNormalizada'].str.startswith(tuple(prefixes))]
    return Decimal(str(round(m['Valor líquido (€)'].sum(),2)))


def asset_from_xml(year,month):
    obj=period_obj(year,month,'AFT')
    if not obj:return None
    for section in obj.get('especiais',{}).values():
        for total in section.get('resumos',[]):
            if str(total.get('MacroRubrica',''))=='AFT' and 'TotalAdicoes' in total:
                return Decimal(str(total['TotalAdicoes']))
    return None


def compile_year(year, last_month=12, source='extratos'):
    if not 1<=last_month<=12:raise ValueError('Mês inválido')
    extrato=stored_extract(year)
    matrix={}; notes=[]
    mapping={15:['31'],16:['372'],17:['43'],18:['443','447'],19:['453'],20:['454']}
    for m in range(1,13):
        if m>last_month:continue
        vals,warnings=ba_values(year,m);notes += [f'{year}-{m:02d}: {w}' for w in warnings]
        for row,pref in mapping.items():
            vals[row]=acquisition_from_extract(extrato,year,m,pref)
        if source=='xml_aft' and (v:=asset_from_xml(year,m)) is not None:
            vals[17]=v
            notes.append(f'{year}-{m:02d}: conta 43 estimada por adições AFT; validar correspondência contabilística (pode incluir transferências).')
        elif source=='xml_aft':
            notes.append(f'{year}-{m:02d}: AFT indisponível; usada conta 43 do extrato, se existir.')
        if extrato is None: notes.append(f'{year}-{m:02d}: extrato de aquisições não encontrado')
        for r in DATA_ROWS:
            if vals.get(r) is None:notes.append(f'{year}-{m:02d}: rubrica da linha {r} sem fonte confirmada')
        matrix[m]=vals
    return matrix,sorted(set(notes))


def make_workbook(template,year,last_month,source='extratos',allow_other_entity=False):
    from artifact_tool import Blob,SpreadsheetFile
    template=Path(template)
    wb=SpreadsheetFile.import_xlsx(Blob.load(str(template)))
    sh=wb.worksheets.get_item('Formulário')
    current_entity=str(sh.get_range('C2').values[0][0] or '')
    if ('Companhia das Lezírias' in current_entity or '235'==str(sh.get_range('B2').values[0][0])) and not allow_other_entity:
        raise ValueError('Este modelo pertence à Companhia das Lezírias, não à ULSLA. Seleciona o modelo SISEE da ULSLA ou gera apenas um rascunho assinalado.')
    data,notes=compile_year(year,last_month,source)
    notes.append('Identificadores internos SISEE da entidade/tarefa requerem validacao no modelo ULSLA.')
    # Modelo de referencia: nao herdar a identificacao da Companhia das Lezirias.
    sh.get_range('C2').values=[['ULSLA, E.P.E.']]
    sh.get_range('B2').values=[[None]]
    sh.get_range('B4').values=[[None]]
    sh.get_range('C4').values=[[str(year)]]
    notes_identificacao='Identificadores internos SISEE da entidade/tarefa requerem validacao no modelo ULSLA.'
    for month in range(1,13):
        col=month+2
        if month>last_month:continue
        vals=data[month]
        for row in DATA_ROWS:
            if vals.get(row) is not None:
                sh.get_cell(row-1,col-1).values=[[float(vals[row])]]
            else:
                # Limpa os dados da OUTRA entidade: ausente significa vazio, nunca zero.
                sh.get_cell(row-1,col-1).values=[[None]]
        for row in AGREEMENT_ROWS:sh.get_cell(row-1,col-1).values=[[0]]
        # 14/22 são somas apenas quando todas as componentes têm fonte.
        for total_row,parts in ((14,[10,11,12,13]),(22,[15,16,17,18,19,20,21])):
            v=sum((vals[r] for r in parts),Decimal(0)) if all(vals.get(r) is not None for r in parts) else None
            sh.get_cell(total_row-1,col-1).values=[[float(v) if v is not None else None]]
        # Linhas globais 9 e 24 preservam a estrutura do formulário, mas sem valores de outra entidade.
        sh.get_cell(8,col-1).values=[[None]]
        notes.append(f'{year}-{month:02d}: linha 9 (valores totais) requer confirmação do perímetro; não será inferida da linha 14')
        sh.get_cell(23,col-1).values=[[0]]
        sh.get_range_by_indexes(8,col-1,29,1).set_number_format(FORMAT_EUR)
    # Também limpar os meses seguintes, sem mascarar incompletude do ano corrente.
    for month in range(last_month+1,13):
        col=month+2
        for row in [9,14,22]+list(DATA_ROWS)+list(AGREEMENT_ROWS): sh.get_cell(row-1,col-1).values=[[None]]
    audit=wb.worksheets.get_or_add('VALIDAÇÃO ULSLA')
    audit.get_range('A1:B6').values=[['SISEE | CONTROLO DE GERAÇÃO',''],['Exercício',year],['Até ao mês',last_month],['Regra de aquisições','ACUMULADO ANUAL (orientação ULSLA)'],['Acordos de pagamento','0,00 € em todos os meses'],['Fonte dos ativos',source]]
    audit.get_range('A8:B8').values=[['Alertas de qualidade',len(notes)]]
    if notes:
        audit.get_range_by_indexes(8,0,len(notes),1).values=[[n] for n in notes]
    audit.get_range('A:A').format.column_width=90
    audit.get_range('B:B').format.column_width=30
    audit.get_range('A1:B1').format.fill='#18324F'
    audit.get_range('A1:B1').format.font.color='#FFFFFF'
    audit.get_range('A1:B1').format.font.bold=True
    stream=io.BytesIO()
    # artifact_tool exports to file; file is a temporary output and never updates the source template.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        outfile=Path(tmp)/'SISEE_PMP.xlsx'
        SpreadsheetFile.export_xlsx(wb).save(str(outfile))
        stream.write(outfile.read_bytes())
    return stream.getvalue(),notes
