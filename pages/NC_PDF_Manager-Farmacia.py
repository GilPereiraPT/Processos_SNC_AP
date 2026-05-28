import hashlib
import re
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from openpyxl import load_workbook
from pypdf import PdfReader


PASTAS_NC = {
    "Apifarma": {
        "rede": r"G:\Comum\Notas de Crédito\Apifarma",
        "local": r"C:\Temp\Notas de Crédito\Apifarma",
        "excel": r"C:\Temp\Notas de Crédito\Apifarma\Mapa_Notas_Credito_Apifarma.xlsx",
    },
    "Payback": {
        "rede": r"G:\Comum\Notas de Crédito\Payback",
        "local": r"C:\Temp\Notas de Crédito\Payback",
        "excel": r"C:\Temp\Notas de Crédito\Payback\Mapa_Notas_Credito_Payback.xlsx",
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


def listar_pdfs(pasta: str) -> list[Path]:
    caminho = Path(pasta)

    if not caminho.exists():
        return []

    pdfs = []

    try:
        for ficheiro in caminho.rglob("*"):
            try:
                if ficheiro.is_file() and ficheiro.suffix.lower() == ".pdf":
                    pdfs.append(ficheiro)
            except Exception:
                pass
    except Exception:
        pass

    return sorted(pdfs)


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

    padroes = [
        r"(?:Nota\s+de\s+Cr[eé]dito|Nota\s+Cr[eé]dito|NC|N\.?\s*C\.?)\s*(?:n[.ºo]*|n[uú]mero)?\s*[:\-]?\s*([A-Z0-9\/\-_\.]+)",
        r"(?:Documento|Doc\.?)\s*(?:n[.ºo]*|n[uú]mero)?\s*[:\-]?\s*([A-Z0-9\/\-_\.]+)",
        r"\bNC\s*([A-Z0-9\/\-_\.]+)\b",
    ]

    for padrao in padroes:
        m = re.search(padrao, texto_norm, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip(" .;:")

    return ""


def extrair_fornecedor(texto: str, tipo: str) -> str:
    if tipo == "Apifarma":
        return "APIFARMA"

    if tipo == "Payback":
        return "PAYBACK"

    return ""


def sincronizar_pdfs(rede: str, local: str) -> tuple[int, int, list[str]]:
    destino = Path(local)
    destino.mkdir(parents=True, exist_ok=True)

    pdfs = listar_pdfs(rede)

    copiados = 0
    ignorados = 0
    erros = []

    for pdf_origem in pdfs:
        pdf_destino = destino / pdf_origem.name

        try:
            if not pdf_destino.exists():
                shutil.copy2(pdf_origem, pdf_destino)
                copiados += 1
            else:
                try:
                    if pdf_origem.stat().st_mtime > pdf_destino.stat().st_mtime:
                        shutil.copy2(pdf_origem, pdf_destino)
                        copiados += 1
                    else:
                        ignorados += 1
                except Exception:
                    ignorados += 1

        except Exception as e:
            erros.append(f"{pdf_origem.name}: {e}")

    return copiados, ignorados, erros


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
    registos = []

    for pdf in listar_pdfs(pasta):
        try:
            registos.append(processar_pdf(pdf, tipo))
        except Exception as e:
            print(f"Erro a processar {pdf.name}: {e}")

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
st.caption("Sincroniza PDFs da rede para o PC e atualiza os mapas Excel da Apifarma e Payback.")

tipo = st.selectbox(
    "Escolha o diretório a tratar",
    list(PASTAS_NC.keys()),
)

pasta_rede = PASTAS_NC[tipo]["rede"]
pasta_local = PASTAS_NC[tipo]["local"]
ficheiro_excel = PASTAS_NC[tipo]["excel"]

st.info(f"**Pasta de rede:** `{pasta_rede}`")
st.info(f"**Pasta local:** `{pasta_local}`")
st.info(f"**Excel de destino:** `{ficheiro_excel}`")

col1, col2, col3 = st.columns(3)

with col1:
    testar_local = st.button("Testar pasta local")

with col2:
    sincronizar = st.button(f"Sincronizar PDFs - {tipo}", type="primary")

with col3:
    atualizar = st.button(f"Atualizar Excel - {tipo}")


if testar_local:
    pdfs_local = listar_pdfs(pasta_local)

    st.write("Pasta local:")
    st.code(pasta_local)

    st.success(f"PDFs encontrados localmente: {len(pdfs_local)}")

    if pdfs_local:
        st.write("Primeiros PDFs encontrados:")
        for pdf in pdfs_local[:20]:
            st.write(pdf.name)


if sincronizar:
    try:
        copiados, ignorados, erros = sincronizar_pdfs(pasta_rede, pasta_local)

        st.success("Sincronização concluída.")
        st.write(f"**PDFs copiados/atualizados:** {copiados}")
        st.write(f"**PDFs ignorados porque já existiam:** {ignorados}")

        pdfs_local = listar_pdfs(pasta_local)
        st.write(f"**PDFs existentes agora na pasta local:** {len(pdfs_local)}")

        if erros:
            st.warning(f"Ocorreram erros em {len(erros)} ficheiros.")
            with st.expander("Ver erros"):
                for erro in erros:
                    st.write(erro)

    except Exception as e:
        st.error(f"Erro na sincronização: {e}")


if atualizar:
    Path(pasta_local).mkdir(parents=True, exist_ok=True)

    with st.spinner("A ler PDFs locais e a atualizar o Excel..."):
        df_existente = carregar_excel(ficheiro_excel)
        df_lidos = processar_pasta(pasta_local, tipo)
        df_final, novos = atualizar_mapa(df_existente, df_lidos)
        gravar_excel(df_final, ficheiro_excel)

    st.success("Excel atualizado com sucesso.")
    st.write(f"**PDFs lidos na pasta local:** {len(df_lidos)}")
    st.write(f"**Novos PDFs adicionados ao Excel:** {novos}")
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

st.subheader("Como usar")

st.markdown(
    """
1. Copiar ou sincronizar os PDFs para a pasta local.
2. Clicar em **Testar pasta local**.
3. Confirmar que os PDFs são encontrados.
4. Clicar em **Atualizar Excel**.

Pastas locais usadas:

- `C:\\Temp\\Notas de Crédito\\Apifarma`
- `C:\\Temp\\Notas de Crédito\\Payback`

Excels gerados:

- `C:\\Temp\\Notas de Crédito\\Apifarma\\Mapa_Notas_Credito_Apifarma.xlsx`
- `C:\\Temp\\Notas de Crédito\\Payback\\Mapa_Notas_Credito_Payback.xlsx`

Os campos **Data de registo**, **Valor de registo** e **Observações** são preservados quando o Excel já existe.
"""
)
