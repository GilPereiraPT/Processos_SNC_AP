# Conversor CCF — execução local Windows

Esta pasta é independente da aplicação SNC-AP existente.

## Instalação
1. Instale Python 3.11+ e execute `pip install -r requirements-local.txt` na raiz desta pasta.
2. Configure no Windows uma variável de ambiente **CCF_ZIP_PASSWORD** com a palavra-passe que já utiliza para os ZIPs recebidos. **Não coloque a palavra-passe em ficheiros do GitHub**.
3. Garanta acesso à unidade de rede G: e ao Outlook clássico com perfil configurado.
4. Execute `streamlit run ccf_app.py` a partir da pasta `ccf`.

O ficheiro `mapeamentos.csv` é mantido na raiz do repositório; copie-o para `ccf` ou defina o caminho local adequado. O histórico Excel e o estado das pesquisas permanecem na unidade de rede (não são publicados no GitHub).

## Estado do processamento
Os ficheiros com códigos de convenção desconhecidos **não são publicados como concluídos**; guarda-se o ZIP original, apresenta-se o detalhe de convenções por TXT e o email fica pendente para nova tentativa depois de completar os mapeamentos.

A pesquisa incremental mostra a data da última pesquisa, retoma pendentes, identifica períodos de reclamação a partir dos anexos e sinaliza processamento parcial. A integração Outlook exige validação no Windows.
