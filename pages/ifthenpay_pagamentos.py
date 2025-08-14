# ifthenpay_pagamentos.py

import streamlit as st
import requests
import pandas as pd

def ifthenpay_app():
    st.header("📥 Exportar Pagamentos Ifthenpay")

    st.markdown("Insira os dados da API:")

    chave = st.text_input("🔑 Chave Backoffice", type="password")
    entidade = st.text_input("🏦 Entidade", value="12377")
    subentidade = st.text_input("🏢 Subentidade", value="143")
    dt_inicio = st.date_input("📅 Início", format="DD-MM-YYYY")
    dt_fim = st.date_input("📅 Fim", format="DD-MM-YYYY")

    if st.button("Obter Pagamentos"):
        if not chave:
            st.warning("⚠️ Insira a chave backoffice.")
            return

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

        with st.spinner("A obter dados..."):
            resp = requests.post(url, data=payload, headers=headers)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if data:
                        df = pd.DataFrame(data)
                        st.success(f"✅ {len(df)} pagamentos encontrados.")
                        st.dataframe(df)

                        # Exportar Excel
                        file = df.to_excel(index=False, engine='openpyxl')
                        st.download_button("💾 Descarregar Excel", file, file_name="pagamentos_ifthenpay.xlsx")
                    else:
                        st.info("Nenhum pagamento encontrado.")
                except Exception as e:
                    st.error(f"Erro ao processar resposta: {e}")
            else:
                st.error(f"Erro HTTP {resp.status_code}: {resp.text}")
