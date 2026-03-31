from io import BytesIO
from decimal import Decimal
import pandas as pd
import streamlit as st

from dmr_txt import (
    processar_dmr_txt,
    ler_pendentes_excel,
    criar_excel_saida,
)

st.set_page_config(page_title="Retificação DMR TXT", layout="wide")
st.title("Retificação de DMR em TXT")

st.write(
    "Carrega o ficheiro DMR em TXT e o Excel com os NIFs pendentes. "
    "A aplicação procura linhas 006 da categoria A, exclui A21, "
    "e reduz rendimento e IRS conforme os valores negativos do Excel."
)

col1, col2 = st.columns(2)

with col1:
    dmr_file = st.file_uploader("DMR TXT", type=["txt"])

with col2:
    excel_file = st.file_uploader("Excel de pendentes", type=["xlsx", "xls"])

sheet_name = st.text_input("Nome da folha do Excel (opcional)", value="")

if st.button("Processar", type="primary"):
    if dmr_file is None or excel_file is None:
        st.error("Tens de carregar os dois ficheiros.")
        st.stop()

    try:
        pendentes_df = ler_pendentes_excel(excel_file, sheet_name=sheet_name or None)

        resultado = processar_dmr_txt(
            dmr_bytes=dmr_file.getvalue(),
            pendentes_df=pendentes_df,
            encoding="latin1",
        )

        dmr_corrigida_bytes = resultado["dmr_corrigida_bytes"]
        pendentes_out = resultado["pendentes_out"]
        log_df = resultado["log_df"]
        resumo = resultado["resumo"]

        st.success("Processamento concluído.")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Pendentes lidos", int(resumo["pendentes_lidos"]))
        c2.metric("Linhas DMR alteradas", int(resumo["linhas_alteradas"]))
        c3.metric("Pendentes resolvidos", int(resumo["pendentes_resolvidos"]))
        c4.metric("Pendentes por resolver", int(resumo["pendentes_por_resolver"]))

        st.subheader("Resumo")
        st.json(resumo)

        st.subheader("Log de alterações")
        st.dataframe(log_df, use_container_width=True, height=350)

        st.subheader("Pendentes atualizados")
        st.dataframe(pendentes_out, use_container_width=True, height=350)

        excel_saida = criar_excel_saida(
            pendentes_out=pendentes_out,
            log_df=log_df,
            resumo=resumo,
        )

        st.download_button(
            "Descarregar DMR corrigida TXT",
            data=dmr_corrigida_bytes,
            file_name="DMR_corrigida.txt",
            mime="text/plain",
        )

        st.download_button(
            "Descarregar Excel de resultados",
            data=excel_saida,
            file_name="resultado_retificacao_dmr.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    except Exception as e:
        st.exception(e)
