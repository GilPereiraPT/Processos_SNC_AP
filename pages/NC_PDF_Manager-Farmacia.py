import hashlib
import io
import re
import zipfile
from datetime import datetime

import pandas as pd
import streamlit as st
from pypdf import PdfReader


COLUNAS = [
    "Fornecedor",
    "Nº NC",
    "Data NC",
    "Data de registo",
    "Valor de registo",
    "Nome ficheiro",
    "Hash ficheiro",
    "Data leitura",
    "Observações",
]


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ler_texto_pdf(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


def normalizar_texto(texto: str) -> str:
    return re.sub(r"\s+", " ", texto or "").strip()


def extrair_data_nc(texto: str) -> str:
    texto_norm = normalizar_texto(texto)

    m = re.search(
        r"Data\s+do\s+documento\s+(\d{2}[/-]\d{2}[/-]\d{4})",
        texto_norm,
        flags=re.IGNORECASE,
    )

    if not m:
        m = re.search(r"\b(\d{2}[/-]\d{2}[/-]\d{4})\b", texto_norm)

    if m:
        valor = m.group(1)
        for fmt in ("%d-%m-%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(valor, fmt).strftime("%Y-%m-%d")
            except ValueError:
                pass

    return ""


def extrair_numero_nc(texto: str) -> str:
    texto_norm = normalizar_texto(texto)

    padroes = [
        r"Documento\s*n[.ºo]*\s*[:\-]?\s*([A-Z]{1,5}\s+[A-Z0-9]+\/[0-9]+)",
        r"\b(RE\s+[A-Z0-9]+\/[0-9]+)\b",
        r"\b(NC\s+[A-Z0-9\/\-_\.]+)\b",
        r"(?:Nota\s+de\s+Cr[eé]dito|NC|N\.?\s*C\.?)\s*(?:n[.ºo]*|n[uú]mero)?\s*[:\-]?\s*([A-Z0-9\/\-_\.]+)",
    ]

    for padrao in padroes:
        m = re.search(padrao, texto_norm, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip(" .;:")

    return ""


def extrair_fornecedor(texto: str, tipo: str) -> str:
    texto_norm = normalizar_texto(texto)

    if tipo == "Payback":
        return "PAYBACK"

    fornecedores = [
        "Lilly Portugal",
        "ASTRAZENECA",
        "Glaxosmith",
        "GlaxoSmithKline",
        "SERVIER",
        "BAYER",
        "NOVARTIS",
        "PFIZER",
        "SANOFI",
        "JANSSEN",
        "MSD",
        "ROCHE",
        "BOEHRINGER",
        "TEVA",
        "MERCK",
        "BIAL",
    ]

    for fornecedor in fornecedores:
        if fornecedor.lower() in texto_norm.lower():
            return fornecedor.upper()

    return "APIFARMA" if tipo == "Apifarma" else ""


def processar_pdf(nome_ficheiro: str, data: bytes, tipo: str) -> dict:
    texto = ler_texto_pdf(data)

    return {
        "Fornecedor": extrair_fornecedor(texto, tipo),
        "Nº NC": extrair_numero_nc(texto),
        "Data NC": extrair_data_nc(texto),
        "Data de registo": "",
        "Valor de registo": "",
        "Nome ficheiro": nome_ficheiro,
        "Hash ficheiro": hash_bytes(data),
        "Data leitura": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Observações": "",
    }


def carregar_excel(uploaded_excel) -> pd.DataFrame:
    if uploaded_excel is None:
        return pd.DataFrame(columns=COLUNAS)

    df = pd.read_excel(uploaded_excel, dtype=str).fillna("")

    for col in COLUNAS:
        if col not in df.columns:
            df[col] = ""

    return df[COLUNAS]


def extrair_pdfs_de_zip(uploaded_zip) -> list[tuple[str, bytes]]:
    ficheiros = []

    data_zip = uploaded_zip.read()

    with zipfile.ZipFile(io.BytesIO(data_zip), "r") as z:
        for nome in z.namelist():
            if nome.lower().endswith(".pdf"):
                ficheiros.append((nome.split("/")[-1], z.read(nome)))

    return ficheiros


def atualizar_mapa(df_existente: pd.DataFrame, df_lidos: pd.DataFrame):
    if df_lidos.empty:
        return df_existente, 0

    if df_existente.empty:
        return df_lidos[COLUNAS], len(df_lidos)

    hashes_existentes = set(df_existente["Hash ficheiro"].astype(str))

    df_novos = df_lidos[
        ~df_lidos["Hash ficheiro"].astype(str).isin(hashes_existentes)
    ].copy()

    df_final = pd.concat([df_existente, df_novos], ignore_index=True)

    return df_final[COLUNAS], len(df_novos)


def excel_bytes(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Notas de Crédito")

        ws = writer.book["Notas de Crédito"]
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

        larguras = {
            "A": 35,
            "B": 24,
            "C": 14,
            "D": 18,
            "E": 18,
            "F": 45,
            "G": 70,
            "H": 22,
            "I": 45,
        }

        for col, largura in larguras.items():
            ws.column_dimensions[col].width = largura

    return output.getvalue()


st.set_page_config(
    page_title="Notas de Crédito - Upload",
    page_icon="📄",
    layout="wide",
)

st.title("📄 Notas de Crédito - Upload")
st.caption("Gera o Excel do zero ou atualiza um Excel existente.")

tipo = st.selectbox("Tipo de documentos", ["Apifarma", "Payback"])

st.subheader("1. Excel existente, se já houver")
excel_existente = st.file_uploader(
    "Opcional — carregar Excel existente para preservar Data de registo, Valor de registo e Observações",
    type=["xlsx"],
)

st.subheader("2. Carregar PDFs em lote")

pdfs = st.file_uploader(
    "Carregar vários PDFs de uma vez",
    type=["pdf"],
    accept_multiple_files=True,
)

zip_pdf = st.file_uploader(
    "Ou carregar um ZIP com vários PDFs",
    type=["zip"],
)

if st.button("Gerar Excel", type="primary"):
    df_existente = carregar_excel(excel_existente)

    ficheiros_pdf = []

    for pdf in pdfs or []:
        ficheiros_pdf.append((pdf.name, pdf.read()))

    if zip_pdf is not None:
        ficheiros_pdf.extend(extrair_pdfs_de_zip(zip_pdf))

    registos = []

    for nome, data in ficheiros_pdf:
        try:
            registos.append(processar_pdf(nome, data, tipo))
        except Exception as e:
            st.warning(f"Erro ao processar {nome}: {e}")

    df_lidos = pd.DataFrame(registos, columns=COLUNAS)
    df_final, novos = atualizar_mapa(df_existente, df_lidos)

    nome_excel = (
        "Mapa_Notas_Credito_Apifarma.xlsx"
        if tipo == "Apifarma"
        else "Mapa_Notas_Credito_Payback.xlsx"
    )

    st.success("Excel gerado com sucesso.")
    st.write(f"**PDFs carregados/processados:** {len(ficheiros_pdf)}")
    st.write(f"**Novos documentos adicionados:** {novos}")
    st.write(f"**Total de linhas no Excel:** {len(df_final)}")

    st.dataframe(df_final, use_container_width=True, hide_index=True)

    st.download_button(
        label="⬇️ Descarregar Excel",
        data=excel_bytes(df_final),
        file_name=nome_excel,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
