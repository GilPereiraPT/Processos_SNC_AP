import streamlit as st

# Configuração da página
st.set_page_config(
    page_title="Ferramenta Integrada — ULSLA",
    page_icon="🛠️",
    layout="wide"
)

# Título principal
st.title("🛠️ Ferramenta Integrada: Serviços Financeiros da ULSLA EPE")

st.markdown("""
**Bem-vindo!**

Esta aplicação integra um conjunto de ferramentas desenvolvidas para apoiar o  
**Serviço de Gestão Financeira e Patrimonial da ULSLA** no processamento, conversão e validação  
de ficheiros contabilísticos no âmbito do **SNC-AP**, bem como noutras rotinas financeiras internas.

Utilize o **menu lateral à esquerda 👉** para aceder à funcionalidade pretendida.
""")

st.divider()

st.subheader("📂 Módulos disponíveis")

st.markdown("""
- **📊 Balancete BA** — Validação de balancetes BA em formato SNC-AP  
- **🧭 Conversor de Centros de Custo** — Conversão e harmonização de centros de custo para SNC-AP  
- **🔁 Converte CM** — Transformação de ficheiros *INFOCB* em ficheiros *CMYYYYMMDD.csv*  
- **🔁 Converte FD de Migrantes** — Ajusta o ficheiro de faturas a migrantes para colocar nas rubricas corretas  
- **📅 Converte Vencimentos** — Geração de mapas de vencimentos no formato SNC-AP  
- **🧾 Criador de Receita Alheia (RA)** — Produção de ficheiros de Receita Alheia a partir de listagens internas  
- **📝 Criar NC CSV** — Geração de ficheiros CSV de Notas de Crédito para importação contabilística  
- **💳 Faturas para P2** — Extração de informação de faturas em PDF e criação de ficheiro para importar no SICC  
- **📚 Juntar Excel** — Consolidação de vários ficheiros Excel num único ficheiro, eliminando n.ºs de documento duplicados  
- **🗂 Mapeamentos CCM** — Consulta e aplicação de tabelas de mapeamento transversal  
- **💊 PAYBACK APIFARMA NC** — Apoio ao tratamento contabilístico de processos de payback APIFARMA  
- **✅ Validador SNC-AP** — Verificação da estrutura e coerência de ficheiros SNC-AP
""")

st.divider()

st.caption("Versão 2025 — Unidade Local de Saúde do Litoral Alentejano, E.P.E.")
