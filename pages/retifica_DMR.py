from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from dmr_txt import (
    ler_pendentes_excel,
    processar_retificacao_dmr,
)

st.set_page_config(page_title="Retificar DMR TXT", layout="wide")

st.title("Retificação de DMR em TXT")
st.caption(
    "Carrega o ficheiro DMR em TXT e o Excel com situações pendentes. "
    "A app identifica o NIF, procura linha elegível de categoria A (exceto A21), "
    "aplica a diminuição e devolve a DMR corrigida e o Excel atualizado."
)

with st.expander("Regras usadas", expanded=False):
    st.markdown(
        """
- Coluna **A** do Excel = **NIF**
- Coluna **C** = **Valor**
- Coluna **D** = **IRS**
- Os valores do Excel já vêm, em regra, **negativos**
- A correção é feita por **soma algébrica**
- Exemplo:
  - DMR rendimento = 643,87
  - Excel valor = -100,00
  - Novo rendimento = 543,87
- A linha da DMR tem de ser da categoria **A**
- **A21 não serve**
- O rendimento e o IRS resultantes **nunca podem ficar negativos**
        """
    )

col1, col2 = st.columns(2)

with col1:
    dmr_file = st.file_uploader(
        "Ficheiro DMR TXT",
        type=["txt"],
        accept_multiple_files=False,
    )

with col2:
    excel_file = st.file_uploader(
        "Ficheiro Excel com pendências",
        type=["xlsx", "xlsm", "xls"],
        accept_multiple_files=False,
    )

sheet_name = st.text_input("Nome da folha do Excel (opcional)", value="")

processar = st.button("Processar ficheiros", type="primary", use_container_width=True)

if processar:
    if dmr_file is None:
        st.error("Falta carregar o ficheiro DMR em TXT.")
        st.stop()

    if excel_file is None:
        st.error("Falta carregar o ficheiro Excel com pendências.")
        st.stop()

    try:
        dmr_text = dmr_file.read().decode("utf-8", errors="replace")
    except Exception:
        st.error("Não foi possível ler o ficheiro DMR TXT.")
        st.stop()

    try:
        pendentes_df = ler_pendentes_excel(excel_file, sheet_name=sheet_name or None)
    except Exception as e:
        st.error(f"Erro ao ler o Excel: {e}")
        st.stop()

    try:
        novo_dmr, resumo_df, pendentes_out = processar_retificacao_dmr(
            dmr_text=dmr_text,
            pendentes_df=pendentes_df,
        )
    except Exception as e:
        st.error(f"Erro ao processar ficheiros: {e}")
        st.stop()

    st.success("Processamento concluído.")

    c1, c2, c3 = st.columns(3)

    with c1:
        st.metric("Pendências lidas", int(len(pendentes_out)))

    with c2:
        atualizados = 0
        if "Estado" in pendentes_out.columns:
            atualizados = int((pendentes_out["Estado"] == "Atualizado").sum())
        st.metric("Atualizados", atualizados)

    with c3:
        erros = 0
        if "Estado" in pendentes_out.columns:
            erros = int((pendentes_out["Estado"] != "Atualizado").sum())
        st.metric("Com erro / validação", erros)

    st.subheader("Resumo das alterações")
    if resumo_df is not None and not resumo_df.empty:
        st.dataframe(resumo_df, use_container_width=True)
    else:
        st.info("Não houve alterações efetuadas.")

    st.subheader("Excel atualizado")
    st.dataframe(pendentes_out, use_container_width=True)

    # download DMR corrigida
    st.download_button(
        label="Descarregar DMR corrigida (.txt)",
        data=novo_dmr.encode("utf-8"),
        file_name="DMR_corrigida.txt",
        mime="text/plain",
        use_container_width=True,
    )

    # download Excel atualizado
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
        pendentes_out.to_excel(writer, index=False, sheet_name="Pendentes_Atualizado")
        if resumo_df is not None and not resumo_df.empty:
            resumo_df.to_excel(writer, index=False, sheet_name="Resumo_Alteracoes")

    st.download_button(
        label="Descarregar Excel atualizado (.xlsx)",
        data=excel_buffer.getvalue(),
        file_name="Pendentes_atualizado.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
