# Hub Financeiro ULSLA — Processos SNC-AP

Conjunto integrado de ferramentas dos Serviços Financeiros e Patrimoniais da ULSLA para processamento, conversão, reconciliação e validação de ficheiros contabilísticos e administrativos.

## Utilização local no Windows

A versão local corre no próprio computador e **não depende do Streamlit Cloud**.

### Primeira utilização

1. Descarregar/clonar o repositório.
2. Fazer duplo clique em **INSTALAR_LOCAL.bat**.
3. Quando a instalação terminar, fazer duplo clique em **INICIAR_LOCAL.bat**.
4. O Hub abre automaticamente no navegador, em `127.0.0.1`.

Enquanto a janela do Hub estiver aberta, o servidor local está ativo. Para terminar, fechar essa janela ou premir `Ctrl+C`.

### Atualizações

Se a pasta tiver sido clonada com Git, executar **ATUALIZAR_LOCAL.bat** para fazer `git pull` e atualizar as dependências Python.

## Ferramentas incluídas

### Contabilidade e SNC-AP
- Validador SNC-AP
- Validador de Balancete BA
- Retificação XML BA / DTAS
- Conferência Contabilidade × Ativos
- Conversor INFOCB → CM
- Conversor de Centros de Custo

### Faturação e Notas de Crédito
- Faturas para P2
- Criar NC CSV
- NC APIFARMA / PAYBACK por PDF
- PAYBACK APIFARMA NC
- Conversor FD Migrantes

### Recursos Humanos e Fiscal
- Conversor de ficheiro de vencimentos
- Retificação DMR

### Dados e Apoio
- Gerador de Receita Alheia
- Juntar Excel
- Conversor CCF / MCDT / Termas, mapeamentos CCM e automatização CCMSNS (Outlook local)

## Registos locais

Quando a aplicação é iniciada por `INICIAR_LOCAL.bat`, o log técnico é guardado em:

`logs/streamlit-local.log`

Isso permite diagnosticar erros sem depender da consola do Streamlit Cloud.
