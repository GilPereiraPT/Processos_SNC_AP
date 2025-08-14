import streamlit as st
import requests
import pandas as pd
from io import BytesIO
from datetime import date

st.set_page_config(page_title="Pagamentos Ifthenpay", layout="wide")

st.header("📥 Exportar Pagamentos Ifthenpay")

# 🔐 Lê chave secreta do ficheiro .streamlit/secrets.toml ou da Cloud
chave = st.secrets["ifthenpay"]["backoffice_key"]

# 📋 Formulário com campos ajustáveis
with st.form("form_pagamentos"):
    entidade = st.text_input("🏦 Entidade", value="12377")
    subentidade = st.text_input("🏢 Subentidade", value="143")
    dt_inicio = st.date_input("📅 Data Início", value=date(2025, 7, 1), format="DD-MM-YYYY")
    dt_fim = st.date_input("📅 Data Fim", value=date(2025, 7, 30), format="DD-MM-YYYY")
    submit = st.form_submit_button("🔄 Obter Pagamentos")

# 🚀 Executa chamada à API
if submit:
    st.info("A contactar a API Ifthenpay...")
    url = "https://ifthenpay.com/ifmbws/ifmbws.asmx/getPaymentsJsonWithSandBoxV2"
    payload = {
        "chavebackoffice": chave,
        "entidade": entidade,
        "subentidade": subentidade,
        "dtHrInicio": dt_inicio.strftime("%d-%m-%Y"),
        "dtHrFim": dt_fim.strftime("%d-%m-%Y"),
        "referencia": "",
        "valor": "",
        "sandbox": "0"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    response = requests.post(url, data=payload, headers=headers)

    if response.status_code == 200:
        try:
            dados = response.json()
            if not dados:
                st.info("⚠️ Nenhum pagamento encontrado.")
            else:
                df = pd.DataFrame(dados)
                st.success(f"✅ Foram encontrados {len(df)} pagamentos.")
                st.dataframe(df)

                # Exportar Excel
                output = BytesIO()
                df.to_excel(output, index=False, engine='openpyxl')
                output.seek(0)

                st.download_button(
                    "💾 Descarregar Excel",
                    output,
                    file_name="pagamentos_ifthenpay.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        except Exception as e:
            st.error(f"Erro ao processar resposta da API: {e}")
            st.code(response.text)
    else:
        st.error(f"Erro HTTP {response.status_code}: {response.text}")

