"""Gerador DFCx SISEE a partir dos DFC SNC-AP previamente arquivados (read-only)."""
from pathlib import Path
import gzip,json,tempfile
from decimal import Decimal

BASE=Path(__file__).resolve().parent
XML_ROOT=BASE/'dados_s3cp_xml'
# Linhas oficiais na folha Formulário; códigos obtidos da estrutura SNC-AP DFC.
LINES={10:'DFC01',11:'DFC02',12:'DFC37',13:'DFC03',14:'DFC04',15:'DFC05',
       16:'DFC38',17:'DFC39',18:'DFC40',20:'DFC41',21:'DFC06',
       25:'DFC07',26:'DFC08',27:'DFC09',28:'DFC10',29:'DFC11',
       32:'DFC12',33:'DFC13',34:'DFC14',35:'DFC15',36:'DFC16',37:'DFC17',38:'DFC18',39:'DFC19',40:'DFC20',
       45:'DFC21',46:'DFC22',47:'DFC23',48:'DFC24',49:'DFC25',
       52:'DFC26',53:'DFC27',54:'DFC28',55:'DFC29',56:'DFC30'}
SUMMARIES={19:'DFCX01',22:'DFCX02',42:'DFCX03',58:'DFCX04',59:'DFCX05',60:'DFCX06',
           61:'DFCX07',62:'DFCX10',64:'DFCX07',68:'DFCX07',69:'DFCX08',70:'DFCX09',
           71:'DFCX10',75:'DFCX10',76:'DFCX11',77:'DFCX12',82:'DFCX10'}
PAYMENT_ROWS={14,15,16,17,18,25,26,27,28,29,52,53,54,55,56}
NEGATIVE_FLOW_ROWS={14,15,16,17,18,25,26,27,28,29,52,53,54,55,56}
# Sinal do formulário para despesas e pagamentos: montante positivo
FORMATS='#,##0.00 "€";[Red](#,##0.00 "€");0.00 "€"'

def read_dfc(year,month):
    for mm in ([14,13,12] if month==12 else [month]):
        p=XML_ROOT/f'{year}-{mm:02d}'/'DFC.json.gz'
        if p.is_file():
            with gzip.open(p,'rt',encoding='utf-8') as f: data=json.load(f)
            if data.get('tipo')!='DFC' or str(data.get('entidade'))!='510445152':
                raise ValueError(f'DFC de entidade ou formato inesperado: {p}')
            return data,p
    return None,None

def _money(value):return round(float(Decimal(str(value))),2)

def monthly_values(obj):
    record={str(r.get('Rubrica')):_money(r['ValorAnoCorrente']) for r in obj.get('registos',[]) if 'ValorAnoCorrente' in r}
    totals={str(r.get('RubricaAgregadora')):_money(r['TotalAnoCorrente']) for r in obj.get('resumo',[]) if 'TotalAnoCorrente' in r}
    values={}
    for row,code in LINES.items():
        if code in record:
            v=record[code];values[row]=-v if row in NEGATIVE_FLOW_ROWS else v
    for row,code in SUMMARIES.items():
        if code in totals:values[row]=totals[code]
    # Totais de fluxos brutos, sem confundir com rubricas líquidas.
    for target,items in ((30,[25,26,27,28,29]),(41,[32,33,34,35,36,37,38,39,40]),(50,[45,46,47,48,49]),(57,[52,53,54,55,56])):
        if all(row in values for row in items):values[target]=round(sum(values[row] for row in items),2)
    # Movimentos de reconciliação não diretamente distinguíveis pelo DFC estruturado:
    # manter vazios (não inventar zeros). Valores de início/fim segregados estão nos agregados.
    return values

def make_dfcx(template,year,last_month,include_2025=True):
    from artifact_tool import Blob,SpreadsheetFile
    wb=SpreadsheetFile.import_xlsx(Blob.load(str(template)))
    sh=wb.worksheets.get_item('Formulário')
    sh.get_range('C2').values=[['ULSLA, E.P.E.']]
    sh.get_range('B2').values=[[None]] # ID do SISEE não pode ser herdado de outra entidade
    sh.get_range('C4').values=[[str(year)]]
    sh.get_range('B4').values=[[None]]
    warnings=[];source=[];filled=0
    mapped_rows=sorted(set(LINES)|set(SUMMARIES)|{30,41,50,57})
    for m in range(1,13):
        vals={};path=None
        if m<=last_month:
            obj,path=read_dfc(year,m)
            if obj is not None: vals=monthly_values(obj)
            else: warnings.append(f'{year}-{m:02d}: DFC XML em falta')
        for row in mapped_rows:
            cell=sh.get_cell(row-1,m+2)
            v=vals.get(row)
            cell.values=[[float(v) if v is not None else None]]
            if v is not None:filled+=1
        # Não preencher por aproximação as rubricas complementares sem mapeamento explícito.
        for row in [65,66,67,72,73,74,79,80,81]: sh.get_cell(row-1,m+2).values=[[None]]
        sh.get_range_by_indexes(9,m+2,73,1).set_number_format(FORMATS)
        if path:source.append((m,str(path)))
    # coluna do exercício anterior; não reutilizar números de outra entidade
    for row in mapped_rows + [65,66,67,72,73,74,79,80,81]:sh.get_cell(row-1,2).values=[[None]]
    if include_2025:
        obj,path=read_dfc(year-1,12)
        if obj is not None:
            for row,v in monthly_values(obj).items():sh.get_cell(row-1,2).values=[[float(v)]]
            source.append((0,str(path)))
        else:warnings.append(f'{year-1}-12: DFC do exercício anterior em falta')
    audit=wb.worksheets.get_or_add('VALIDAÇÃO ULSLA')
    info=[['SISEE | DFCx | VALIDAÇÃO ULSLA',''],['Exercício',year],['Mês de referência',last_month],
          ['Natureza','Valores acumulados no exercício'],['Entidade','ULSLA, E.P.E.'],
          ['ID SISEE','A confirmar no modelo oficial da ULSLA'],['Células preenchidas',filled],
          ['Observações',len(warnings)+1]]
    audit.get_range_by_indexes(0,0,len(info),2).values=info
    audit.get_range('A1:B1').format.fill='#18324F'
    audit.get_range('A1:B1').format.font.color='#FFFFFF'
    audit.get_range('A1:B1').format.font.bold=True
    audit.get_range('A:A').format.column_width=76
    audit.get_range('B:B').format.column_width=90
    notes=['Rubricas complementares 65-67, 72-74, 79-81 requerem validação do respetivo âmbito contabilístico.']+warnings
    for i,n in enumerate(notes,start=10):audit.get_cell(i-1,0).values=[[n]]
    base=11+len(notes)
    audit.get_cell(base-1,0).values=[['Fontes efetivamente utilizadas']]
    for i,(m,path) in enumerate(source,start=base+1):audit.get_range_by_indexes(i-1,0,1,2).values=[[('Ano anterior' if m==0 else f'{m:02d}/{year}'),path]]
    with tempfile.TemporaryDirectory() as td:
        out=Path(td)/'DFCx_ULSLA.xlsx'; SpreadsheetFile.export_xlsx(wb).save(str(out));binary=out.read_bytes()
    return binary,notes,filled
