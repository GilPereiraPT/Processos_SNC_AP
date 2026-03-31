from __future__ import annotations

import streamlit as st
import pandas as pd

from dmr_txt import (
    ler_pendentes_excel,
    processar_dmr_txt,
    criar_excel_resumo,
)

st.set_page_config(page_title="Retificar DMR", layout="wide")
st.title("Retificar DMR (TXT) com base em Excel de pendentes")

st.write(
    """
Carregue:
- o ficheiro **DMR em TXT**
- o ficheiro **Excel com pendentes**

O Excel deve ter colunas equivalentes a:
- **NIF**
- **Rendimento**
- **Valor**
- **IRS**

Só serão tratadas linhas com:
- rendimento **A**
- excluem-se **A21** e **A22**
"""
)

col1, col2 = st.columns(2)

with col1:
    dmr_file = st.file_uploader("Ficheiro DMR (TXT)", type=["txt"])

with col2:
    excel_file = st.file_uploader("Ficheiro Excel pendentes", type=["xlsx", "xls"])

sheet_name = st.text_input("Nome da folha do Excel (opcional)", value="")

if dmr_file and excel_file:
    try:
        pendentes_df = ler_pendentes_excel(excel_file, sheet_name=sheet_name or None)

        dmr_bytes = dmr_file.read()
        dmr_text = dmr_bytes.decode("latin-1", errors="replace")

        dmr_corrigida, resumo_df = processar_dmr_txt(dmr_text, pendentes_df)

        st.success("Processamento concluído.")

        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Pendentes Excel", int(len(pendentes_df)))
        with c2:
            st.metric("Corrigidos", int((resumo_df["Estado"] == "Corrigido").sum()))
        with c3:
            st.metric(
                "Com erro / validação",
                int((resumo_df["Estado"] != "Corrigido").sum())
            )

        st.subheader("Resumo")
        st.dataframe(resumo_df, use_container_width=True)

        excel_bytes = criar_excel_resumo(resumo_df)

        st.download_button(
            "Descarregar DMR corrigida (TXT)",
            data=dmr_corrigida.encode("latin-1", errors="replace"),
            file_name="DMR_corrigida.txt",
            mime="text/plain",
        )

        st.download_button(
            "Descarregar resumo (Excel)",
            data=excel_bytes,
            file_name="Resumo_retificacao_DMR.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        with st.expander("Pré-visualização da DMR corrigida"):
            st.text(dmr_corrigida[:15000])

    except Exception as e:
        st.error(f"Erro ao processar ficheiros: {e}")
else:
    st.info("Carregue os dois ficheiros para continuar.")
