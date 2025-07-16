import streamlit as st
import camelot
import pandas as pd
import io

st.set_page_config(page_title="Extrair Orçamento PDF", layout="centered")
st.title("📄 Extrair Orçamento de Estado PDF para Excel")

uploaded_file = st.file_uploader("Selecione o ficheiro PDF:", type=["pdf"])

if uploaded_file:
    with open("temp.pdf", "wb") as f:
        f.write(uploaded_file.getbuffer())
    st.info("A extrair tabelas com Camelot...")
    tables = camelot.read_pdf("temp.pdf", pages="all", flavor="stream")

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for i, table in enumerate(tables):
            df = table.df
            df.columns = [c.strip() for c in df.iloc[0]]
            df = df[1:]
            df.to_excel(writer, sheet_name=f"Tabela_{i+1}", index=False)

    st.success("✅ Excel gerado com sucesso.")
    st.download_button(
        "📥 Descarregar Excel",
        data=output.getvalue(),
        file_name="orcamento_extraido.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
