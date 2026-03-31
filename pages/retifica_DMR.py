from __future__ import annotations

from decimal import Decimal

import pandas as pd
import streamlit as st

from dmr_txt import (
    descobrir_folhas_excel,
    ler_dmr_txt,
    ler_pendentes_excel,
    aplicar_retificacoes,
    dataframe_to_excel_bytes,
    POS_NIF_INI,
    POS_NIF_FIM,
    POS_REND_INI,
    POS_REND_FIM,
    POS_CAT_INI,
    POS_CAT_FIM,
    POS_IRS_INI,
    POS_IRS_FIM,
)


st.set_page_config(page_title="Retificar DMR TXT", layout="wide")

st.title("Retificação de DMR em TXT")
st.caption(
    "Carregue o ficheiro TXT da DMR e o Excel com situações pendentes. "
    "A aplicação identifica linhas de categoria A, aplica as diminuições e devolve os ficheiros atualizados."
)

with st.expander("Posições usadas no TXT da DMR", expanded=False):
    st.markdown(
        f"""
- **NIF**: colunas **{POS_NIF_INI + 1}** a **{POS_NIF_FIM}**
- **Rendimento**: colunas **{POS_REND_INI + 1}** a **{POS_REND_FIM}**
- **Categoria**: colunas **{POS_CAT_INI + 1}** a **{POS_CAT_FIM}**
- **IRS**: colunas **{POS_IRS_INI + 1}** a **{POS_IRS_FIM}**

Regras:
- Só é considerada a categoria **`A `**.
- **A21** não conta.
- Os valores do Excel já vêm negativos, por isso são **somados** aos da DMR para reduzir.
- O novo rendimento e o novo IRS **nunca podem ficar negativos**.
"""
    )

col1, col2 = st.columns(2)

with col1:
    dmr_file = st.file_uploader(
        "Ficheiro DMR TXT",
        type=["txt"],
        key="dmr_txt",
    )

with col2:
    excel_file = st.file_uploader(
        "Ficheiro Excel com pendentes",
        type=["xlsx", "xls"],
        key="pendentes_excel",
    )

sheet_name = None

if excel_file is not None:
    try:
        folhas = descobrir_folhas_excel(excel_file)
        if folhas:
            usar_folha = st.checkbox("Escolher folha do Excel", value=False)
            if usar_folha:
                sheet_name = st.selectbox(
                    "Nome da folha do Excel",
                    options=folhas,
                    index=0,
                )
            else:
                sheet_name = folhas[0]
                st.caption(f"Será usada a primeira folha encontrada: {sheet_name}")
    except Exception as e:
        st.warning(f"Não foi possível listar as folhas do Excel: {e}")

if st.button("Processar ficheiros", type="primary"):
    try:
        if dmr_file is None:
            st.error("Tem de carregar o ficheiro TXT da DMR.")
            st.stop()

        if excel_file is None:
            st.error("Tem de carregar o ficheiro Excel com pendentes.")
            st.stop()

        with st.spinner("A processar..."):
            linhas_originais, linhas_006 = ler_dmr_txt(dmr_file)
            pendentes_df = ler_pendentes_excel(excel_file, sheet_name=sheet_name)
            resultados_df, pendentes_out, dmr_corrigida_txt = aplicar_retificacoes(
                linhas_originais,
                linhas_006,
                pendentes_df,
            )

        st.success("Processamento concluído.")

        total_pendentes = len(pendentes_out)
        total_corrigidos = 0
        total_erro = 0

        if not resultados_df.empty and "Estado" in resultados_df.columns:
            total_corrigidos = int((resultados_df["Estado"] == "Corrigido").sum())
            total_erro = int((resultados_df["Estado"] != "Corrigido").sum())

        m1, m2, m3 = st.columns(3)
        m1.metric("Linhas no Excel", total_pendentes)
        m2.metric("Corrigidas", total_corrigidos)
        m3.metric("Com erro / validação", total_erro)

        st.subheader("Resumo das alterações")
        if resultados_df.empty:
            st.info("Não foram encontrados registos para apresentar.")
        else:
            st.dataframe(resultados_df, use_container_width=True)

        st.subheader("Excel atualizado")
        st.dataframe(pendentes_out, use_container_width=True)

        st.subheader("Pré-visualização da DMR corrigida")
        preview = "\n".join(dmr_corrigida_txt.splitlines()[:50])
        st.text_area("Primeiras linhas", preview, height=400)

        excel_bytes = dataframe_to_excel_bytes(pendentes_out)
        dmr_bytes = dmr_corrigida_txt.encode("utf-8")

        dl1, dl2 = st.columns(2)

        with dl1:
            st.download_button(
                label="Descarregar DMR corrigida TXT",
                data=dmr_bytes,
                file_name="DMR_corrigida.txt",
                mime="text/plain",
            )

        with dl2:
            st.download_button(
                label="Descarregar Excel atualizado",
                data=excel_bytes,
                file_name="pendentes_atualizado.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    except Exception as e:
        st.error(f"Erro ao processar ficheiros: {e}")
