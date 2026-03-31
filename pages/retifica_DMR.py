import streamlit as st

from dmr_txt import (
    processar_dmr_e_excel,
    pendentes_to_excel_bytes,
    resumo_to_excel_bytes,
    texto_para_bytes_utf8,
    ler_pendentes_excel,
)

st.set_page_config(page_title="Retificar DMR", layout="wide")

st.title("Retificação de DMR TXT")
st.write(
    "Carrega o ficheiro DMR em TXT e o Excel com situações pendentes. "
    "A aplicação procura linhas 006 com categoria 'A ' e atualiza rendimento e IRS."
)

with st.expander("Posições usadas nesta versão", expanded=False):
    st.markdown(
        """
- **NIF**: colunas **10 a 18**
- **Categoria de rendimento**: colunas **53 a 54**
- **Categoria válida**: exatamente **`A `**
- **Rendimento**: da coluna **38** até antes da **53**
- **IRS**: da coluna **58** até antes da **73**
        """
    )

dmr_file = st.file_uploader("Ficheiro DMR (TXT)", type=["txt"])
excel_file = st.file_uploader("Ficheiro Excel de pendentes", type=["xlsx", "xls"])
sheet_name = st.text_input("Nome da folha do Excel (opcional)")

if excel_file is not None:
    try:
        preview_df = ler_pendentes_excel(excel_file, sheet_name=sheet_name or None)
        st.subheader("Pré-visualização do Excel")
        st.dataframe(preview_df, use_container_width=True)
        excel_file.seek(0)
    except Exception as e:
        st.error(f"Erro ao ler Excel: {e}")

if dmr_file is not None and excel_file is not None:
    if st.button("Processar"):
        try:
            dmr_file.seek(0)
            excel_file.seek(0)

            dmr_corrigida, pendentes_out, resumo_df = processar_dmr_e_excel(
                dmr_file=dmr_file,
                excel_file=excel_file,
                sheet_name=sheet_name or None,
            )

            st.success("Processamento concluído.")

            c1, c2, c3 = st.columns(3)
            c1.metric("Linhas Excel", len(pendentes_out))
            c2.metric("Atualizadas", int((pendentes_out["Estado"] == "Atualizado").sum()))
            c3.metric("Com erro / não encontradas", int((pendentes_out["Estado"] != "Atualizado").sum()))

            st.subheader("Resumo das alterações")
            st.dataframe(resumo_df, use_container_width=True)

            st.subheader("Excel atualizado")
            st.dataframe(pendentes_out, use_container_width=True)

            st.download_button(
                "Descarregar DMR corrigida",
                data=texto_para_bytes_utf8(dmr_corrigida),
                file_name="DMR_corrigida.txt",
                mime="text/plain",
            )

            st.download_button(
                "Descarregar Excel atualizado",
                data=pendentes_to_excel_bytes(pendentes_out),
                file_name="pendentes_atualizado.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            st.download_button(
                "Descarregar resumo",
                data=resumo_to_excel_bytes(resumo_df),
                file_name="resumo_alteracoes.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        except Exception as e:
            st.error(f"Erro ao processar ficheiros: {e}")
