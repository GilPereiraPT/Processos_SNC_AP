import io
import re
from pathlib import Path

import pandas as pd
import streamlit as st


st.set_page_config(
    page_title="Juntar Excel — ULSLA",
    page_icon="📚",
    layout="wide",
)

st.title("📚 Juntar ficheiros Excel")
st.markdown(
    """
Carregue vários ficheiros Excel com a mesma estrutura para obter **um único ficheiro consolidado**.

A aplicação permite escolher a coluna que identifica o **n.º de documento** e elimina automaticamente
as ocorrências repetidas, mantendo apenas uma linha por documento.
"""
)


def normalizar_nome_coluna(valor):
    texto = str(valor).strip().lower()
    substituicoes = {
        "º": "",
        "ª": "",
        "á": "a",
        "à": "a",
        "ã": "a",
        "â": "a",
        "é": "e",
        "ê": "e",
        "í": "i",
        "ó": "o",
        "ô": "o",
        "õ": "o",
        "ú": "u",
        "ç": "c",
    }
    for origem, destino in substituicoes.items():
        texto = texto.replace(origem, destino)
    texto = re.sub(r"[.\-_/\\]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def normalizar_documento(valor):
    """Normaliza apenas para comparação, sem alterar o valor apresentado."""
    if pd.isna(valor):
        return ""

    texto = str(valor).strip()

    # Evita que 12345 e 12345.0 sejam considerados documentos diferentes.
    if re.fullmatch(r"\d+\.0", texto):
        texto = texto[:-2]

    return texto.upper()


def sugerir_coluna_documento(colunas):
    candidatos = [
        "nº documento",
        "n.º documento",
        "numero documento",
        "número documento",
        "numero de documento",
        "número de documento",
        "num documento",
        "nº doc",
        "n.º doc",
        "documento",
    ]

    mapa = {normalizar_nome_coluna(c): c for c in colunas}

    for candidato in candidatos:
        chave = normalizar_nome_coluna(candidato)
        if chave in mapa:
            return mapa[chave]

    for coluna in colunas:
        if "documento" in normalizar_nome_coluna(coluna):
            return coluna

    return colunas[0] if colunas else None


def ler_ficheiro_excel(ficheiro, todas_as_folhas=False):
    """Lê o Excel como texto para preservar números de documento."""
    folhas = pd.read_excel(
        ficheiro,
        sheet_name=None,
        dtype=str,
        keep_default_na=False,
    )

    blocos = []

    for indice, (nome_folha, df) in enumerate(folhas.items()):
        if not todas_as_folhas and indice > 0:
            break

        if df.empty:
            continue

        df = df.replace("", pd.NA).dropna(how="all").fillna("")
        if df.empty:
            continue

        df.columns = [str(c).strip() for c in df.columns]
        blocos.append(df)

    return blocos


def criar_excel(df):
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name="Consolidado", index=False)

        workbook = writer.book
        worksheet = writer.sheets["Consolidado"]

        formato_cabecalho = workbook.add_format(
            {
                "bold": True,
                "border": 1,
                "text_wrap": True,
                "valign": "top",
            }
        )

        for col_num, valor in enumerate(df.columns):
            worksheet.write(0, col_num, valor, formato_cabecalho)

        worksheet.freeze_panes(1, 0)
        worksheet.autofilter(0, 0, max(len(df), 1), max(len(df.columns) - 1, 0))

        for idx, coluna in enumerate(df.columns):
            valores = df[coluna].astype(str).head(1000)
            largura = max(
                len(str(coluna)),
                valores.map(len).max() if not valores.empty else 0,
            )
            worksheet.set_column(idx, idx, min(max(largura + 2, 10), 45))

    output.seek(0)
    return output.getvalue()


st.divider()

ficheiros = st.file_uploader(
    "Selecione os ficheiros Excel",
    type=["xlsx", "xlsm", "xls"],
    accept_multiple_files=True,
)

if ficheiros:
    st.success(f"{len(ficheiros)} ficheiro(s) selecionado(s).")

    todas_as_folhas = st.checkbox(
        "Juntar todas as folhas de cada ficheiro",
        value=False,
        help="Por defeito é utilizada apenas a primeira folha de cada ficheiro.",
    )

    blocos = []
    erros = []

    for ficheiro in ficheiros:
        try:
            blocos.extend(ler_ficheiro_excel(ficheiro, todas_as_folhas))
        except Exception as exc:
            erros.append(f"{ficheiro.name}: {exc}")

    if erros:
        st.warning("Alguns ficheiros não puderam ser lidos:")
        for erro in erros:
            st.write(f"- {erro}")

    if blocos:
        # Mantém a união de colunas caso exista alguma pequena diferença de estrutura.
        total = pd.concat(blocos, ignore_index=True, sort=False).fillna("")

        colunas = list(total.columns)
        sugestao = sugerir_coluna_documento(colunas)
        indice_sugerido = colunas.index(sugestao) if sugestao in colunas else 0

        st.subheader("Configuração")

        coluna_documento = st.selectbox(
            "Coluna que identifica o n.º de documento",
            options=colunas,
            index=indice_sugerido,
        )

        manter = st.radio(
            "Quando o mesmo documento aparece mais do que uma vez:",
            options=["Manter a primeira ocorrência", "Manter a última ocorrência"],
            horizontal=True,
        )

        remover_linhas_sem_documento = st.checkbox(
            "Excluir linhas sem n.º de documento",
            value=False,
        )

        resultado = total.copy()
        resultado["__chave_documento__"] = resultado[coluna_documento].map(normalizar_documento)

        com_documento = resultado[resultado["__chave_documento__"] != ""].copy()
        sem_documento = resultado[resultado["__chave_documento__"] == ""].copy()

        duplicados = com_documento.duplicated(
            subset=["__chave_documento__"],
            keep=False,
        )

        total_documentos_repetidos = com_documento.loc[
            duplicados, "__chave_documento__"
        ].nunique()

        keep = "first" if manter == "Manter a primeira ocorrência" else "last"
        com_documento = com_documento.drop_duplicates(
            subset=["__chave_documento__"],
            keep=keep,
        )

        if remover_linhas_sem_documento:
            consolidado = com_documento
        else:
            consolidado = pd.concat(
                [com_documento, sem_documento],
                ignore_index=True,
                sort=False,
            )

        consolidado = consolidado.drop(columns=["__chave_documento__"], errors="ignore")

        linhas_removidas = len(total) - len(consolidado)

        st.divider()
        st.subheader("Resultado")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Ficheiros", len(ficheiros))
        c2.metric("Linhas originais", f"{len(total):,}".replace(",", "."))
        c3.metric("Linhas finais", f"{len(consolidado):,}".replace(",", "."))
        c4.metric("Documentos repetidos", f"{total_documentos_repetidos:,}".replace(",", "."))

        if linhas_removidas > 0:
            st.info(f"Foram retiradas {linhas_removidas} linha(s) do resultado final.")
        else:
            st.info("Não foi necessário retirar linhas por duplicação.")

        with st.expander("Pré-visualizar resultado"):
            st.dataframe(consolidado.head(200), use_container_width=True)

        excel = criar_excel(consolidado)

        st.download_button(
            "⬇️ Descarregar Excel consolidado",
            data=excel,
            file_name="Excel_Consolidado.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )

        st.caption(
            "O ficheiro descarregado contém uma única folha chamada 'Consolidado'. "
            "Os valores originais da coluna de documento são preservados; a normalização é utilizada apenas para detetar duplicados."
        )
