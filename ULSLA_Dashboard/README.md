# ULSLA — Plataforma Financeira local

Dashboard financeiro, contabilidade analítica, importação XML, produção de mapas, contratualização ACSS e verificação de dados. Versão de código de 28/10/2026, com logótipo/cabeçalhos comuns e seletores temporais destacados.

## Windows: instalar e abrir

1. Descarregar o repositório em **Code → Download ZIP** e extrair.
2. Entrar na pasta **ULSLA_Dashboard**.
3. Com Python 3.10 ou superior instalado (recomendado 3.11), abrir **INSTALAR_LOCAL.bat**. A primeira instalação precisa de acesso à Internet para obter as dependências.
4. Abrir **INICIAR_LOCAL.bat**. O portal abre em **http://127.0.0.1:8500**.
5. No portal, carregar em **Iniciar módulo** e depois **Abrir módulo** na área pretendida.

O ambiente `.venv` é independente das restantes aplicações do repositório. Os módulos só ficam acessíveis no computador local.

| Módulo | Porta |
|---|---:|
| Portal | 8500 |
| Dashboard Financeiro | 8501 |
| Contabilidade Analítica | 8502 |
| Importação de Dados | 8503 |
| Produção de Mapas | 8505 |
| Contratualização | 8506 |
| Verificação de Dados | 8507 |

Em Linux/macOS: `python3 instalar_local.py`, seguido de `.venv/bin/python iniciar_local.py`.

## Dados locais

O repositório contém os scripts, logótipo e mapas de classificação. **Não inclui históricos financeiros, movimentos contabilísticos, bases SQLite, cadastros de entidades, produção realizada ou contratos.** Uma instalação nova começa sem fechos; o Dashboard permite importar os primeiros dados pela barra lateral. A Verificação de Dados funciona mesmo sem movimentos importados.

Para continuar uma instalação existente, guardar primeiro uma cópia dessa pasta e copiar para ela os ficheiros de código desta pasta, mantendo os dados locais. Em alternativa, copiar para esta pasta os dados da instalação antiga, depois de fechar os módulos. Não adicionar esses dados ao GitHub.

Fontes locais reconhecidas:

- `dados_mensais.json` e, se existir, `seed_2026_09.json`: histórico financeiro;
- `dados_s3cp_xml/`: BA, DR, BLC, DFC, DOREC, DODES, AFT, AI e DAPL importados;
- `dados_xml/`: dívidas, pagamentos e créditos;
- `dados_pmp_extratos/`: extratos contabilísticos 3–5, incluindo classe 4;
- `dados_analitica/analitica.sqlite3`: movimentos e importações da analítica;
- `dados_sisee/`: dados complementares CGO/UTE;
- `contratualizacao/`: bases e configurações anuais;
- `LIST_ENTIDADES_15102026.CSV`, `LIST_PCONTAS_15102026.CSV` (ou `plano_contas_dashboard.csv`): cadastros usados pela analítica;
- `producao_cp_2026_03.csv`: fonte da simulação de produção CP, quando se utilizar essa função.

Os modelos oficiais Excel são carregados no momento de gerar cada reporte. Os mapas de centros, Pools, RCE e correspondência de produção acompanham o código. O `.gitignore` exclui as principais pastas e fontes de dados locais.

## Verificação de Dados

No portal, abrir **Verificação de Dados**, ou usar a área Avançada do Dashboard. Inclui filtros por exercício, mês e área, instruções de resolução e exportação CSV.

Distingue **Em falta**, **Ilegível** e **Por confirmar**. Um mês sem movimentos não prova falta do extrato nem valor zero. A presença de um ficheiro não comprova cobertura integral nem reconciliação contabilística. O controlo é apenas de leitura e não cria bases nem confirma dados automaticamente.

## Testes

Na pasta ULSLA_Dashboard, com o ambiente ativo:

```bash
python -m unittest discover -s tests -v
```

Os testes abrangem fontes ausentes/ilegíveis, entidade XML, dezembro 12/13/14, alternativas do histórico, cobertura mensal de extratos, importações versus movimentos da analítica e preservação dos dados SQLite. Os seis módulos foram também testados com Streamlit AppTest em cópias locais. Os ficheiros `.bat` destinam-se a Windows e devem ser confirmados no computador de instalação.
