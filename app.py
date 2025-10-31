import streamlit as st

# Configuração da página
st.set_page_config(
    page_title="Ferramenta Integrada — ULSLA",
    page_icon="🛠️",
    layout="wide"
)

# Título principal
st.title("🛠️ Ferramenta Integrada: Receita Alheia + Validador SNC-AP")

st.markdown("""
Bem-vindo!

Esta aplicação integra várias ferramentas do **Serviço de Gestão Financeira e Patrimonial da ULSLA**, 
permitindo processar e validar ficheiros contabilísticos no formato **SNC-AP** e outras rotinas internas.

Utiliza o **menu lateral à esquerda 👉** para aceder à funcionalidade pretendida.
""")

st.divider()

st.subheader("📂 Módulos disponíveis")
st.markdown("""
- **📊 Balancete BA** — valida balancetes BA em formato SNC-AP  
- **🧭 Conversor de Centros de Custo** — converte mapas de custos para SNC-AP  
- **🔁 Converte CM** — transforma ficheiros *INFOCB* em *FicheiroCMYYYYMMDD.csv*  
- **📅 Converte Vencimentos** — gera mapas de vencimentos no formato SNC-AP  
- **🧾 Criador de Receita Alheia (RA)** — produz ficheiros de Receita Alheia a partir das listagens internas  
- **💳 Ifthenpay Pagamentos** — extrai informação de recebimentos Ifthenpay  
- **✅ Validador SNC-AP** — verifica estrutura e coerência de ficheiros SNC-AP
""")

st.divider()

st.caption("Versão 2025 — Unidade Local de Saúde do Litoral Alentejano, E.P.E.")
