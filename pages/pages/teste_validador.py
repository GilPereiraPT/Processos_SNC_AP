# pages/teste_validador.py

import streamlit as st

st.set_page_config(page_title="Teste Validador", layout="wide")
st.write("✅ A página de teste carregou sem erros!")

uploaded = st.file_uploader("Eis o uploader — carrega um CSV para testar", type="csv")
if uploaded:
    st.success("Recebi o ficheiro: " + uploaded.name)
else:
    st.info("Ainda não carregaste nenhum ficheiro.")
