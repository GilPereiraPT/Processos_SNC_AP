import streamlit as st

from dmr_txt import processar_dmr_e_pendentes

st.set_page_config(page_title="Retificação DMR", page_icon="📄", layout="wide")

st.title("Retificação de DMR em TXT")
st.write(
    "Carregue o ficheiro DMR em formato TXT e o Excel com situações pendentes. "
    "O sistema procura o NIF, encontra uma linha elegível da categoria A "
    "(excluindo A21), aplica a diminuição ao rendimento e ao IRS, "
    "e devolve a DMR corrigida, o Excel atualizado e um resumo do processamento."
)

with st.sidebar:
    st.header("Ficheiros")
    dmr_file = st.file_uploader("DMR (TXT)", type=["txt"])
    excel_file = st.file_uploader("Excel pendentes", type=["xlsx", "xls"])
    sheet_name = st.text_input("Nome da folha do Excel (opcional)", value="")

processar = st.button("Processar")

if processar:
    if dmr_file is None:
        st.error("Falta carregar o ficheiro DMR em TXT.")
    elif excel_file is None:
        st.error("Falta carregar o ficheiro Excel.")
    else:
        try:
            novo_txt, pendentes_out, resumo, excel_out = processar_dmr_e_pendentes(
                dmr_file=dmr_file,
                excel_file=excel_file,
                sheet_name=sheet_name,
            )

            st.success("Processamento concluído com sucesso.")

            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric("Total pendentes", int(resumo["total_pendentes"]))
            c2.metric("Corrigidos", int(resumo["corrigidos"]))
            c3.metric("NIF não encontrado", int(resumo["nao_encontrados"]))
            c4.metric("Sem linha elegível", int(resumo["sem_linha_elegivel"]))
            c5.metric("Saldo insuficiente", int(resumo["sem_saldo_suficiente"]))
            c6.metric("Com erro", int(resumo["com_erro"]))

            st.subheader("Resultado detalhado")
            st.dataframe(pendentes_out, use_container_width=True)

            st.download_button(
                label="Descarregar DMR corrigida (TXT)",
                data=novo_txt.encode("utf-8"),
                file_name="DMR_corrigida.txt",
                mime="text/plain",
            )

            st.download_button(
                label="Descarregar Excel atualizado",
                data=excel_out,
                file_name="pendentes_atualizados.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        except Exception as e:
            st.exception(e)
