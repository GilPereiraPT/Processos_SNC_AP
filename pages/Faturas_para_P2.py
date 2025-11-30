import io
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List
import numpy as np
import pandas as pd
import streamlit as st
import fitz  # PyMuPDF
import cv2
from PIL import Image

# ============================================================
# Configuração do teu NIF
# ============================================================
MEU_NIF = "510445152"

# ============================================================
# Funções auxiliares
# ============================================================
def formatar_data_ddmmaaaa(valor: str) -> str:
    if not valor or not valor.strip():
        return ""
    valor = valor.strip()
    formatos = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y%m%d"]
    for fmt in formatos:
        try:
            return datetime.strptime(valor, fmt).strftime("%d/%m/%Y")
        except:
            continue
    m = re.search(r"(\d{2}[./-]\d{2}[./-]\d{4})", valor)
    if m:
        return m.group(1).replace(".", "/").replace("-", "/")
    return valor

def normalizar_monetario(valor: str) -> str:
    if not valor:
        return ""
    v = re.sub(r"[^\d.,]", "", valor)
    if "." in v and "," in v:
        if v.index(".") < v.index(","):
            v = v.replace(".", "")  # 1.234,56 → 1234,56
        else:
            v = v.replace(".", ",").replace(",", ".", 1)[::-1].replace(".", ",", 1)[::-1]
    v = v.replace(".", "").replace(",", ".")
    try:
        return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return valor

# ============================================================
# QR-Code AT (correção oficial)
# ============================================================
def ler_qr_imagem(doc) -> Optional[str]:
    try:
        page = doc.load_page(0)
        pix = page.get_pixmap(dpi=200)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img_np = np.array(img)
        img_cv2 = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        detector = cv2.QRCodeDetector()
        data, _, _ = detector.detectAndDecode(img_cv2)
        return data.strip() if data else None
    except:
        return None

def parse_qr_portugues(qr_str: str) -> dict:
    if not qr_str or "&" not in qr_str:
        return {}
    try:
        partes = dict(item.split("=", 1) for item in qr_str.split("&") if "=" in item)
        nif_emitente = partes.get("B", "").split(":")[-1] if "B" in partes else ""
        nif_cliente = partes.get("C", "").split(":")[-1] if "C" in partes else ""
        data = partes.get("G", "")
        total = partes.get("N", "")
        serie = partes.get("E", "")
        numero = partes.get("F", "")
        num_fatura = re.sub(r"\D", "", serie + numero)
        tipo = partes.get("I", "FT")[:2]
        tipos = {"FT": "Fatura", "FR": "Fatura-Recibo", "NC": "Nota de Crédito", "ND": "Nota de Débito"}
        tipo_doc = tipos.get(tipo, "Fatura")
        return {
            "nif_emitente": nif_emitente,
            "nif_cliente": nif_cliente,
            "data": formatar_data_ddmmaaaa(data),
            "total": normalizar_monetario(total),
            "num_fatura": num_fatura,
            "tipo_doc": tipo_doc,
            "valido": nif_cliente == MEU_NIF
        }
    except:
        return {}

# ============================================================
# Extração por texto (fallback)
# ============================================================
def extrair_nif_emitente(texto: str) -> str:
    m = re.search(r"NIF[^\d]*(\d{9})", texto, re.I)
    return m.group(1) if m else ""

def extrair_nota_encomenda_7xx25(texto: str) -> str:
    texto_limpo = re.sub(r"\s+", "", texto)
    m = re.search(r"\b(\d{7}25)\b", texto_limpo)
    return m.group(1) if m else ""

# ============================================================
# Processamento principal
# ============================================================
def processar_pdf(nome: str, bytes_pdf: bytes) -> dict:
    doc = fitz.open(stream=bytes_pdf, filetype="pdf")
    texto = "\n".join(page.get_text() for page in doc)

    # 1. Tentar QR (prioridade máxima)
    qr_data = ler_qr_imagem(doc)
    if qr_data:
        dados = parse_qr_portugues(qr_data)
        if dados.get("nif_emitente"):
            status_nif = "Correto" if dados["valido"] else f"ERRADO → {dados['nif_cliente']}"
            return {
                "Ficheiro": nome,
                "Tipo": dados["tipo_doc"],
                "NIF Fornecedor": dados["nif_emitente"],
                "NIF Cliente (deve ser 510445152)": status_nif,
                "Data": dados["data"],
                "Valor Total €": dados["total"],
                "Nº Fatura (dígitos)": dados["num_fatura"],
                "Nota Encomenda (7xx25)": extrair_nota_encomenda_7xx25(texto),
                "Origem": "QR-Code (perfeito)"
            }

    # 2. Fallback: texto
    return {
        "Ficheiro": nome,
        "Tipo": "Fatura",
        "NIF Fornecedor": extrair_nif_emitente(texto),
        "NIF Cliente (deve ser 510445152)": "Não confirmado (sem QR)",
        "Data": formatar_data_ddmmaaaa(re.search(r"\d{2}[./-]\d{2}[./-]\d{4}", texto).group(0) if re.search(r"\d{2}[./-]\d{2}[./-]\d{4}", texto) else ""),
        "Valor Total €": normalizar_monetario(re.search(r"TOTAL\s*A\s*PAGAR[^\d]*([\d.,]+)", texto, re.I).group(1) if re.search(r"TOTAL\s*A\s*PAGAR[^\d]*([\d.,]+)", texto, re.I) else ""),
        "Nº Fatura (dígitos)": "",
        "Nota Encomenda (7xx25)": extrair_nota_encomenda_7xx25(texto),
        "Origem": "Texto (fallback)"
    }

# ============================================================
# Streamlit App
# ============================================================
st.set_page_config(page_title="Faturas P2 – Extração Automática", layout="wide")
st.title("Extração Automática de Faturas (com QR da AT)")
st.markdown(f"**NIF da empresa:** `{MEU_NIF}` ← verifica se aparece correto no QR")

uploaded = st.file_uploader("Carregar faturas PDF", type="pdf", accept_multiple_files=True)

if uploaded and st.button("Processar Faturas", type="primary"):
    with st.spinner("A processar..."):
        resultados = [processar_pdf(f.name, f.read()) for f in uploaded]
        df = pd.DataFrame(resultados)

        # Ordenar colunas
        colunas = ["Ficheiro", "Origem", "Tipo", "NIF Fornecedor", "NIF Cliente (deve ser 510445152)",
                   "Data", "Valor Total €", "Nº Fatura (dígitos)", "Nota Encomenda (7xx25)"]
        df = df[colunas]

        st.success(f"Processadas {len(df)} faturas!")
        st.dataframe(df, use_container_width=True)

        # Excel
        output = io.BytesIO()
        df.to_excel(output, index=False, engine="openpyxl")
        st.download_button("Descarregar Excel", output.getvalue(), "Faturas_Processadas.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
