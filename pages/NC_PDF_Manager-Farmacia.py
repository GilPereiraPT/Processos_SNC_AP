import hashlib
import io
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from pypdf import PdfReader


PASTAS_NC = {
    "Apifarma": {
        "pasta": r"G:\Comum\Notas de Crédito\Apifarma",
        "excel": r"G:\Comum\Notas de Crédito\Apifarma\Mapa_Notas_Credito_Apifarma.xlsx",
    },
    "Payback": {
        "pasta": r"G:\Comum\Notas de Crédito\Payback",
        "excel": r"G:\Comum\Notas de Crédito\Payback\Mapa_Notas_Credito_Payback.xlsx",
    },
}


COLUNAS = [
    "Fornecedor",
    "Nº NC",
    "Data NC",
    "Data de registo",
    "Valor de registo",
    "Nome ficheiro",
    "Caminho ficheiro",
    "Hash ficheiro",
    "Data leitura",
    "Observações",
]


def hash_ficheiro(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def ler_texto_pdf(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        texto = []
        for page in reader.pages:
            texto.append(page.extract_text() or "")
        return "\n".join(texto)
    except Exception:
        return ""


def normalizar_texto(texto: str) -> str:
    return re.sub(r"\s+", " ", texto or "").strip()


def extrair_data_nc(texto: str) -> str:
    texto = normalizar_texto(texto)

    padroes = [
        r"\b(\d{2}[/-]\d{2}[/-]\d{4})\b",
        r"\b(\d{4}[/-]\d{2}[/-]\d{2})\b",
    ]

    for padrao in padroes:
        m = re.search(padrao, texto)
        if not m:
            continue

        valor = m.group(1)

        for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(valor, fmt).strftime("%Y-%m-%d")
            except ValueError:
                pass

    return ""


def extrair_numero_nc(texto: str) -> str:
    texto = normalizar_texto(texto)

    padroes = [
        r"(?:Nota\s+de\s+Cr[eé]dito|Nota\s+Cr[eé]dito|NC|N\.?\s*C\.?)\s*(?:n[.ºo]*|n[uú]mero)?\s*[:\-]?\s*([A-Z0-9\/\-_\.]+)",
        r"(?:Documento|Doc\.?)\s*(?:n[.ºo]*|n[uú]mero)?\s*[:\-]?\s*([A-Z0-9\/\-_\.]+)",
        r"\bNC\s*([A-Z0-9\/\-_\.]+)\b",
    ]

    for padrao in padroes:
        m = re.search(padrao, texto, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip(" .;:")

    return ""


def extrair_fornecedor(texto: str, tipo: str) -> str:
    if tipo == "Apifarma":
        return "APIFARMA"

    if tipo == "Payback":
        return "PAYBACK"

    linhas = [l.strip() for l in (texto or "").splitlines() if l.strip()]

    rejeitar = [
        "nota de crédito",
        "nota credito",
        "nif",
        "contribuinte",
        "data",
        "documento",
        "cliente",
        "total",
        "iva",
    ]

    for linha in linhas[:15]:
        linha_limpa = normalizar_texto(linha)

        if len(linha_limpa) < 4:
            continue

        if any(x in linha_limpa.lower() for x in rejeitar):
            continue

        if re.search(r"\d{4,}", linha_limpa):
            continue

        return linha_limpa[:120]

    return ""


def processar_pdf(path: Path, tipo: str) -> dict:
    texto = ler_texto_pdf(path)

    return {
        "Fornecedor": extrair_fornecedor(texto, tipo),
        "Nº NC": extrair_numero_nc(texto),
        "Data NC": extrair_data_nc(texto),
        "Data de registo": "",
        "Valor de registo": "",
        "Nome ficheiro": path.name,
        "Caminho ficheiro": str(path),
        "Hash ficheiro": hash_ficheiro(path),
        "Data leitura": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Observações": "",
    }


def processar_pasta(pasta: str, tipo: str) -> pd.DataFrame:
    caminho = Path(pasta)

    if not caminho.exists():
        return pd.DataFrame(columns=COLUNAS)

    registos = []

    for pdf in sorted(caminho.glob("*.pdf")):
        registos.append(processar_pdf(pdf, tipo))

    return pd.DataFrame(registos, columns=COLUNAS)


def carregar_excel(path_excel: str) -> pd.DataFrame:
    path = Path(path_excel)

    if not path.exists():
        return pd.DataFrame(columns=COLUNAS)

    df = pd.read_excel(path, dtype=str).fillna("")

    for col in COLUNAS:
        if col not in df.columns:
            df[col] = ""

    return df[COLUNAS]


def atualizar_mapa(df_existente: pd.DataFrame, df_lidos: pd.DataFrame) -> tuple[pd.DataFrame, int]:
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


def gravar_excel(df: pd.DataFrame, path_excel: str):
    path = Path(path_excel)
    path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Notas de Crédito")

    wb = load_workbook(path)
    ws = wb["Notas de Crédito"]

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    larguras = {
        "A": 35,
        "B": 22,
        "C": 14,
        "D": 18,
        "E": 18,
        "F": 45,
        "G": 80,
        "H": 70,
        "I": 22,
        "J": 45,
    }

    for col, largura in larguras.items():
        ws.column_dimensions[col].width = largura

    wb.save(path)


st.set_page_config(
    page_title="Notas de Crédito PDF",
    page_icon="📄",
    layout="wide",
)

st.title("📄 Notas de Crédito PDF")
st.caption("Atualização automática dos mapas Excel da Apifarma e Payback.")

tipo = st.selectbox(
    "Escolha o diretório a atualizar",
    list(PASTAS_NC.keys()),
)

pasta_pdf = PASTAS_NC[tipo]["pasta"]
ficheiro_excel = PASTAS_NC[tipo]["excel"]

st.info(f"**Pasta dos PDFs:** `{pasta_pdf}`")
st.info(f"**Excel de destino:** `{ficheiro_excel}`")

col1, col2 = st.columns(2)

with col1:
    atualizar = st.button(f"Atualizar Excel - {tipo}", type="primary")

with col2:
    abrir_pasta = st.button("Verificar existência da pasta")

if abrir_pasta:
    if Path(pasta_pdf).exists():
        qtd_pdfs = len(list(Path(pasta_pdf).glob("*.pdf")))
        st.success(f"Pasta encontrada. Foram encontrados {qtd_pdfs} PDFs.")
    else:
        st.error("A pasta não foi encontrada. Confirma se a unidade G: está acessível.")

if atualizar:
    if not Path(pasta_pdf).exists():
        st.error("A pasta não foi encontrada. Confirma se a unidade G: está acessível.")
        st.stop()

    with st.spinner("A ler PDFs e a atualizar o Excel..."):
        df_existente = carregar_excel(ficheiro_excel)
        df_lidos = processar_pasta(pasta_pdf, tipo)
        df_final, novos = atualizar_mapa(df_existente, df_lidos)
        gravar_excel(df_final, ficheiro_excel)

    st.success("Excel atualizado com sucesso.")
    st.write(f"**PDFs lidos na pasta:** {len(df_lidos)}")
    st.write(f"**Novos PDFs adicionados:** {novos}")
    st.write(f"**Total de linhas no Excel:** {len(df_final)}")

    st.dataframe(df_final, use_container_width=True, hide_index=True)

    with open(ficheiro_excel, "rb") as f:
        st.download_button(
            label="⬇️ Descarregar Excel atualizado",
            data=f,
            file_name=Path(ficheiro_excel).name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

st.divider()

st.subheader("Campos do Excel")

st.markdown(
    """
O ficheiro Excel fica com estas colunas:

- **Fornecedor**
- **Nº NC**
- **Data NC**
- **Data de registo** — preenchimento manual por outro serviço
- **Valor de registo** — preenchimento manual por outro serviço
- **Nome ficheiro**
- **Caminho ficheiro**
- **Hash ficheiro**
- **Data leitura**
- **Observações**

O campo **Hash ficheiro** impede que o mesmo PDF seja acrescentado duas vezes.
"""
)
