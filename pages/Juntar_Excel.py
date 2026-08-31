import io
import re
import zipfile
from pathlib import Path

import pandas as pd
import rarfile
import streamlit as st


st.set_page_config(
    page_title="Juntar Excel — ULSLA",
    page_icon="📚",
    layout="wide",
)

st.title("📚 Juntar ficheiros Excel")
st.markdown(
    """
Carregue vários ficheiros Excel, ou um arquivo **ZIP/RAR** com vários Excel, para obter
**um único ficheiro consolidado**.

Por defeito, a aplicação **inclui todas as linhas**, mesmo quando existem números de documento repetidos.
Se pretender, pode ativar a opção de remover duplicados.
"""
)

EXTENSOES_EXCEL = {".xlsx", ".xlsm", ".xls"}


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
    if pd.isna(valor):
        return ""
    texto = str(valor).strip()
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


def ler_excel_bytes(conteudo, nome_ficheiro, todas_as_folhas=False):
    extensao = Path(nome_ficheiro).suffix.lower()
    if extensao not in EXTENSOES_EXCEL:
        return []

    engine = "xlrd" if extensao == ".xls" else "openpyxl"
    buffer = io.BytesIO(conteudo)

    folhas = pd.read_excel(
        buffer,
        sheet_name=None,
        dtype=str,
        keep_default_na=False,
        engine=engine,
    )

    blocos = []

    for indice, (_, df) in enumerate(folhas.items()):
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


def extrair_excels_zip(conteudo):
    encontrados = []
    with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo:
        for info in arquivo.infolist():
            if info.is_dir():
                continue
            nome = info.filename
            if Path(nome).suffix.lower() in EXTENSOES_EXCEL and not Path(nome).name.startswith("~$"):
                encontrados.append((nome, arquivo.read(info)))
    return encontrados


def extrair_excels_rar(conteudo):
    encontrados = []
    with rarfile.RarFile(io.BytesIO(conteudo)) as arquivo:
        for info in arquivo.infolist():
            if info.isdir():
                continue
            nome = info.filename
            if Path(nome).suffix.lower() in EXTENSOES_EXCEL and not Path(nome).name.startswith("~$"):
                encontrados.append((nome, arquivo.read(info)))
    return encontrados


def recolher_excels(uploaded_files):
    excels = []
    erros = []

    for ficheiro in uploaded_files:
        nome = ficheiro.name
        extensao = Path(nome).suffix.lower()
        conteudo = ficheiro.getvalue()

        try:
            if extensao in EXTENSOES_EXCEL:
                excels.append((nome, conteudo))
            elif extensao == ".zip":
                internos = extrair_excels_zip(conteudo)
                if not internos:
                    erros.append(f"{nome}: o ZIP não contém ficheiros Excel suportados.")
                excels.extend([(f"{nome} → {interno}", dados) for interno, dados in internos])
            elif extensao == ".rar":
                internos = extrair_excels_rar(conteudo)
                if not internos:
                    erros.append(f"{nome}: o RAR não contém ficheiros Excel suportados.")
                excels.extend([(f"{nome} → {interno}", dados) for interno, dados in internos])
        except rarfile.NeedFirstVolume:
            erros.append(f"{nome}: RAR multipartes — carregue o primeiro volume e os restantes volumes necessários.")
        except rarfile.PasswordRequired:
            erros.append(f"{nome}: o RAR está protegido por palavra-passe.")
        except Exception as exc:
            erros.append(f"{nome}: {exc}")

    return excels, erros


def nome_excel_real(nome_origem):
    return nome_origem.split(" → ", 1)[-1]


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
    "Selecione Excel, ZIP ou RAR",
    type=["xlsx", "xlsm", "xls", "zip", "rar"],
    accept_multiple_files=True,
    help="Pode carregar vários Excel diretamente ou um ZIP/RAR contendo vários ficheiros Excel.",
)

if ficheiros:
    st.success(f"{len(ficheiros)} ficheiro(s)/arquivo(s) selecionado(s).")

    todas_as_folhas = st.checkbox(
        "Juntar todas as folhas de cada Excel",
        value=False,
        help="Por defeito é utilizada apenas a primeira folha de cada ficheiro Excel.",
    )

    excels, erros = recolher_excels(ficheiros)
    blocos = []

    for nome_origem, conteudo in excels:
        try:
            nome_real = nome_excel_real(nome_origem)
            blocos.extend(ler_excel_bytes(conteudo, nome_real, todas_as_folhas))
        except Exception as exc:
            erros.append(f"{nome_origem}: {exc}")

    if erros:
        st.warning("Alguns ficheiros não puderam ser processados:")
        for erro in erros:
            st.write(f"- {erro}")

    if excels:
        st.caption(f"Foram encontrados {len(excels)} ficheiro(s) Excel para consolidação.")

    if blocos:
        total = pd.concat(blocos, ignore_index=True, sort=False).fillna("")

        st.subheader("Configuração")

        remover_duplicados = st.checkbox(
            "Remover números de documento repetidos",
            value=False,
            help="Desativado por defeito: todas as linhas são incluídas no ficheiro final.",
        )

        consolidado = total.copy()
        total_documentos_repetidos = 0
        linhas_removidas = 0

        if remover_duplicados:
            colunas = list(total.columns)
            sugestao = sugerir_coluna_documento(colunas)
            indice_sugerido = colunas.index(sugestao) if sugestao in colunas else 0

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

        if remover_duplicados:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Excel processados", len(excels))
            c2.metric("Linhas originais", f"{len(total):,}".replace(",", "."))
            c3.metric("Linhas finais", f"{len(consolidado):,}".replace(",", "."))
            c4.metric("Documentos repetidos", f"{total_documentos_repetidos:,}".replace(",", "."))

            if linhas_removidas > 0:
                st.info(f"Foram retiradas {linhas_removidas} linha(s) do resultado final.")
            else:
                st.info("Não foi necessário retirar linhas por duplicação.")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Excel processados", len(excels))
            c2.metric("Linhas incluídas", f"{len(consolidado):,}".replace(",", "."))
            c3.metric("Duplicados removidos", "0")
            st.info("Todas as linhas foram incluídas, incluindo números de documento repetidos.")

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
            "Por defeito, todas as linhas são mantidas. A remoção de duplicados só é aplicada quando ativada manualmente."
        )
