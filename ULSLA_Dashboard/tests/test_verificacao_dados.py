import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from verificacao_dados import audit

class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def json(self,name,obj):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
        opener=gzip.open if name.endswith('.gz') else open
        with opener(path,'wt',encoding='utf-8') as f:json.dump(obj,f)
    def row(self,frame,area,item,per='2026-01'):
        return frame[(frame['Área']==area)&(frame.Dado==item)&(frame['Período']==per)].iloc[0]
    def xml(self,kind='BA',period='2026-01',entity='510445152'):
        return {'tipo':kind,'periodo':period,'entidade':entity,'resumo':[],'registos':[]}
    def test_absent_database_is_not_created(self):
        x=audit(self.root,start='2026-01',end='2026-01')
        self.assertEqual(self.row(x,'Contabilidade analítica','Extrato analítico').Estado,'Em falta')
        self.assertFalse((self.root/'dados_analitica').exists())
    def test_december_legacy_14_and_wrong_entity(self):
        self.json('dados_s3cp_xml/2025-14/BA.json.gz',self.xml(period='2025-14'))
        self.json('dados_s3cp_xml/2025-12/DR.json.gz',self.xml('DR','2025-12','WRONG'))
        x=audit(self.root,start='2025-12',end='2025-12')
        self.assertEqual(self.row(x,'XML SNC-AP','BA','2025-12').Estado,'Recebido — XML')
        self.assertEqual(self.row(x,'XML SNC-AP','DR','2025-12').Estado,'Ilegível')
        self.assertEqual(len(x[(x['Área']=='XML SNC-AP') & (x.Dado=='BA')]),1)
    def test_history_is_available_but_does_not_replace_xml_reporting(self):
        self.json('dados_mensais.json',{'2026-01':{'dr':{'resultado':1}}})
        x=audit(self.root,start='2026-01',end='2026-01')
        self.assertEqual(self.row(x,'XML SNC-AP','DR').Estado,'Recebido — histórico')
        self.assertEqual(self.row(x,'Reporte SISEE','DR XML para reporte').Estado,'Em falta')
    def test_monthly_coverage_and_no_movement_confirmation(self):
        path=self.root/'dados_pmp_extratos/extrato_2026.csv.gz';path.parent.mkdir()
        with gzip.open(path,'wt',encoding='utf-8') as f:
            f.write('Conta;Data contabilização;Tipo;Debito;Credito;Valor líquido (€)\n431;2026-01-10;FT;1;0;1\n31;2026-02-10;FT;1;0;1\n')
        x=audit(self.root,start='2026-01',end='2026-03')
        self.assertEqual(self.row(x,'Extratos contabilísticos','Extrato da classe 4').Estado,'Recebido — movimentos')
        self.assertEqual(self.row(x,'Extratos contabilísticos','Extrato da classe 4','2026-02').Estado,'Por confirmar')
        self.assertEqual(self.row(x,'Extratos contabilísticos','Extrato da classe 4','2026-03').Estado,'Em falta')
    def test_import_log_is_compared_with_actual_rows_and_db_unchanged(self):
        path=self.root/'dados_analitica/analitica.sqlite3';path.parent.mkdir()
        with sqlite3.connect(path) as c:
            c.executescript('CREATE TABLE importacoes(ano,mes,linhas);CREATE TABLE movimentos(ano,mes);CREATE TABLE ba_esperado(ano,mes);INSERT INTO importacoes VALUES(2026,1,2);INSERT INTO movimentos VALUES(2026,1);INSERT INTO ba_esperado VALUES(2026,1);')
        before=hashlib.sha256(path.read_bytes()).digest()
        x=audit(self.root,start='2026-01',end='2026-01')
        self.assertEqual(self.row(x,'Contabilidade analítica','Extrato analítico').Estado,'Por confirmar')
        self.assertEqual(hashlib.sha256(path.read_bytes()).digest(),before)
    def test_invalid_database_does_not_report_everything_as_missing(self):
        p=self.root/'dados_analitica/analitica.sqlite3';p.parent.mkdir();p.write_bytes(b'invalid')
        x=audit(self.root,start='2026-01',end='2026-01')
        self.assertEqual(self.row(x,'Contabilidade analítica','Extrato analítico').Estado,'Ilegível')
    def test_empty_manual_quarter_and_optional_config(self):
        self.json('dados_sisee/cgo_dados_complementares.json',{'periodos':{'2026-T1':{}},'ultimos':{'doentes':5}})
        x=audit(self.root,start='2026-03',end='2026-03')
        self.assertEqual(self.row(x,'Reporte SISEE','Dados complementares CGO','2026-03').Estado,'Por confirmar')
        optional=x[(x['Área']=='Contratualização') & x.Dado.eq('Calendarização ACSS')].iloc[0]
        self.assertEqual(optional.Estado,'Opcional — ausente')

if __name__=='__main__':unittest.main()
