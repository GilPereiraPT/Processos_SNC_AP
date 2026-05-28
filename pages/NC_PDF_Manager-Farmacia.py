import hashlib
import io
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from openpyxl import load_workbook
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
        texto = []
        for page in reader.pages:
            texto.append(page.extract_text() or "")
        return "\n".join(texto)
    except Exception:
        return ""


def normalizar_texto(texto: str) -> str:
    return re.sub(r"\s+", " ", texto or "").strip()


def extrair_data_nc(texto: str) -> str:
    texto_norm = normalizar_texto(texto or "")

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
    texto_norm = normalizar_texto(texto or "")

    m = re.search(
        r"Documento\s*n[.ºo]*\s*[:\-]?\s*([A-Z]{1,5}\s+[A-Z0-9]+\/[0-9]+)",
        texto_norm,
        flags=re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    m = re.search(
        r"\b(RE\s+[A-Z0-9]+\/[0-9]+)\b",
        texto_norm,
        flags=re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    return ""


def extrair_fornecedor(texto: str, tipo: str) -> str:
    texto_norm = normalizar_texto(texto or "")

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

    if tipo == "Apifarma":
        return "APIFARMA"

    return ""


def processar_pdf(uploaded_file, tipo: str) -> dict:
    data = uploaded_file.read()
    texto = ler_texto_pdf(data)

    return {
        "Fornecedor": extrair_fornecedor(texto, tipo),
        "Nº NC": extrair_numero_nc(texto),
        "Data NC": extrair_data_nc(texto),
        "Data de registo": "",
        "Valor de registo": "",
        "Nome ficheiro": uploaded_file.name,
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
            "B": 22,
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
    page_title="Notas de Crédito - Upload PDF",
    page_icon="📄",
    layout="wide",
)

st.title("📄 Notas de Crédito - Upload PDF")
st.caption("Carrega PDFs e gera/atualiza o Excel sem depender de pastas locais ou rede.")

tipo = st.selectbox(
    "Tipo de documentos",
    ["Apifarma", "Payback"],
)

excel_existente = st.file_uploader(
    "Carregar Excel existente, se já existir",
    type=["xlsx"],
)

pdfs = st.file_uploader(
    "Carregar PDFs de Notas de Crédito",
    type=["pdf"],
    accept_multiple_files=True,
)

if st.button("Gerar Excel", type="primary"):
    df_existente = carregar_excel(excel_existente)

    registos = []

    for pdf in pdfs or []:
        try:
            registos.append(processar_pdf(pdf, tipo))
        except Exception as e:
            st.warning(f"Erro ao processar {pdf.name}: {e}")

    df_lidos = pd.DataFrame(registos, columns=COLUNAS)
    df_final, novos = atualizar_mapa(df_existente, df_lidos)

    st.success("Excel gerado com sucesso.")
    st.write(f"**PDFs carregados:** {len(pdfs or [])}")
    st.write(f"**Novos documentos adicionados:** {novos}")
    st.write(f"**Total de linhas no Excel:** {len(df_final)}")

    st.dataframe(df_final, use_container_width=True, hide_index=True)

    nome_excel = (
        "Mapa_Notas_Credito_Apifarma.xlsx"
        if tipo == "Apifarma"
        else "Mapa_Notas_Credito_Payback.xlsx"
    )

    st.download_button(
        label="⬇️ Descarregar Excel",
        data=excel_bytes(df_final),
        file_name=nome_excel,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
