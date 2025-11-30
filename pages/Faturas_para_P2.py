"""
app.py  –  Extrator de dados de faturas (QR + texto) em Streamlit

Requisitos (requirements.txt):
streamlit
pandas
pymupdf
opencv-python-headless
Pillow
numpy
"""

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
# Funções auxiliares de formatação
# ============================================================

def formatar_data_ddmmaaaa(valor: str) -> str:
    """Converte para DD/MM/AAAA sempre que possível."""
    if not valor:
        return ""
    valor = valor.strip()
    formatos = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"]
    for fmt in formatos:
        try:
            dt = datetime.strptime(valor, fmt)
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            continue
    m = re.search(r"(\d{2}[./-]\d{2}[./-]\d{4})", valor)
    if m:
        try:
            dt = datetime.strptime(m.group(1).replace("-", "/"), "%d/%m/%Y")
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            pass
    m = re.search(r"(\d{4}-\d{2}-\d{2})", valor)
    if m:
        try:
            dt = datetime.strptime(m.group(1), "%Y-%m-%d")
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            pass
    return valor


def normalizar_monetario(valor: str) -> str:
    """Devolve sempre formato PT: 1234,56."""
    if not valor:
        return ""
    v = valor.strip().replace(" ", "")
    if "," in v and "." not in v:
        return v
    sep = None
    for ch in reversed(v):
        if ch in ",.":
            sep = ch
            break
    if not sep:
        return v
    inteiro, dec = v.rsplit(sep, 1)
    inteiro = inteiro.replace(".", "").replace(",", "")
    return f"{inteiro},{dec}"


# ============================================================
# Leitura de PDF / QR
# ============================================================

def abrir_pdf_bytes(file_bytes: bytes):
    return fitz.open(stream=file_bytes, filetype="pdf")


def primeira_pagina_para_cv2(doc) -> np.ndarray:
    page = doc.load_page(0)
    pix = page.get_pixmap()
    mode = "RGBA" if pix.alpha else "RGB"
    img_pil = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
    if img_pil.mode == "RGBA":
        img_pil = img_pil.convert("RGB")
    img_cv2 = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
    return img_cv2


def ler_qr_imagem(doc) -> Optional[str]:
    """Tenta ler QR a partir da 1ª página como imagem."""
    try:
        img_cv2 = primeira_pagina_para_cv2(doc)
    except Exception:
        return None
    detector = cv2.QRCodeDetector()
    data, points, _ = detector.detectAndDecode(img_cv2)
    if data:
        return data.strip()
    return None


def extrair_qr_string_do_texto(texto: str) -> Optional[str]:
    """Procura string AT (A:PT*B:...) diretamente no texto."""
    m = re.search(r"A:PT\*B:[^\r\n]+", texto)
    if m:
        return m.group(0).strip()
    m = re.search(r"A:PT\|B:[^\r\n]+", texto)
    if m:
        return m.group(0).strip()
    return None


def parse_qr_at(data: str) -> dict:
    if not data:
        return {}
    sep = "*" if "*" in data else "|"
    partes = data.split(sep)
    res: dict[str, str] = {}
    for parte in partes:
        parte = parte.strip()
        if ":" not in parte:
            continue
        k, v = parte.split(":", 1)
        k = k.strip()
        v = v.strip()
        if k:
            res[k] = v
    return res


def numero_fatura_de_c(campo_c: str) -> str:
    """
    A partir do campo C do QR:
    'FT A 2500/003421' -> '2500003421'
    'FT FA.2025/297'  -> '2025297'
    """
    if not campo_c:
        return ""
    m = re.search(r"(\d+)[/\-](\d+)", campo_c)
    if m:
        return m.group(1) + m.group(2)
    digitos = re.findall(r"(\d+)", campo_c)
    return "".join(digitos) if digitos else ""


def detetar_tipo_documento(campo_c: str, texto: str, filename: str) -> str:
    tipo_map = {
        "FT": "Fatura",
        "FR": "Fatura-Recibo",
        "NC": "Nota de Crédito",
        "ND": "Nota de Débito",
        "VD": "Venda a Dinheiro",
        "RC": "Recibo",
    }
    if campo_c:
        m = re.match(r"\s*([A-Z]{2})\b", campo_c)
        if m:
            cod = m.group(1)
            if cod in tipo_map:
                return tipo_map[cod]

    txt = texto.lower()
    if "nota de crédito" in txt or "nota de credito" in txt:
        return "Nota de Crédito"
    if "fatura-recibo" in txt or "fatura recibo" in txt:
        return "Fatura-Recibo"
    if "venda a dinheiro" in txt:
        return "Venda a Dinheiro"
    if "nota de débito" in txt or "nota de debito" in txt:
        return "Nota de Débito"
    if "recibo" in txt and "fatura" not in txt:
        return "Recibo"
    if "fatura " in txt or "factura " in txt:
        return "Fatura"

    nome = filename.lower()
    if "credito" in nome:
        return "Nota de Crédito"
    if "fatura" in nome or "factura" in nome:
        return "Fatura"
    if "recibo" in nome:
        return "Recibo"
    return ""


# ============================================================
# Extração por TEXTO
# ============================================================

def extrair_texto_doc(doc) -> str:
    texto_total: List[str] = []
    for page in doc:
        texto_total.append(page.get_text("text"))
    return "\n".join(texto_total)


def extrair_nif_texto(texto: str, filename: str) -> str:
    base = Path(filename).stem
    m = re.search(r"NIF\s*([0-9]{9})", base, flags=re.IGNORECASE)
    if m:
        return m.group(1)

    texto_norm = texto.replace("\n", " ")
    padroes = [
        r"N[úu]mero\s+de\s+Identifica[cç][aã]o\s+Fiscal[^0-9]*([0-9]{9})",
        r"NIF[^0-9]*([0-9]{9})",
    ]
    for p in padroes:
        m = re.search(p, texto_norm, flags=re.IGNORECASE)
        if m:
            return m.group(1)

    todos = re.findall(r"\b([0-9]{9})\b", texto_norm)
    return todos[0] if todos else ""


def extrair_data_texto(texto: str) -> str:
    texto_norm = texto.replace("\n", " ")

    m = re.search(
        r"Data[^0-9]{0,15}Emiss[aã]o[^0-9]*([0-9]{2}[./-][0-9]{2}[./-][0-9]{4})",
        texto_norm, flags=re.IGNORECASE,
    )
    if m:
        return formatar_data_ddmmaaaa(m.group(1))

    m = re.search(r"emitida\s+em\s+(\d{2}[./-]\d{2}[./-]\d{4})",
                  texto_norm, flags=re.IGNORECASE)
    if m:
        return formatar_data_ddmmaaaa(m.group(1))

    m = re.search(r"\b(\d{2}[./-]\d{2}[./-]\d{4})\b", texto_norm)
    if m:
        return formatar_data_ddmmaaaa(m.group(1))

    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", texto_norm)
    if m:
        return formatar_data_ddmmaaaa(m.group(1))

    return ""


def extrair_total_texto(texto: str) -> str:
    """
    Estratégia conservadora:
    - Total Documento / Total ( EUR ) / Total Fatura / Total a Pagar / TOTAL GERAL
    """
    texto_norm = texto.replace("\n", " ")

    padroes = [
        r"Total\s+Documento[^0-9]*([0-9]{1,3}(?:[.,][0-9]{3})*[.,][0-9]{2})",
        r"Total\s*\(\s*EUR\s*\)\s*([0-9]{1,3}(?:[.,][0-9]{3})*[.,][0-9]{2})",
        r"TOTAL\s+GERAL[^0-9]*([0-9]{1,3}(?:[.,][0-9]{3})*[.,][0-9]{2})",
        r"TOTAL\s+FATURA[^0-9]*([0-9]{1,3}(?:[.,][0-9]{3})*[.,][0-9]{2})",
        r"TOTAL\s+A\s+PAGAR[^0-9]*([0-9]{1,3}(?:[.,][0-9]{3})*[.,][0-9]{2})",
    ]
    for p in padroes:
        m = re.search(p, texto_norm, flags=re.IGNORECASE)
        if m:
            return normalizar_monetario(m.group(1))

    return ""


def extrair_numero_fatura_texto(texto: str, nif: str) -> str:
    """Procura nº da fatura só em linhas com 'Fatura' ou 'Invoice'."""
    def escolher(cands):
        filtrados = []
        for num in cands:
            if not (3 <= len(num) <= 15):
                continue
            if nif and num == nif:
                continue
            if re.fullmatch(r"\d{7}", num) and num.endswith("25"):
                continue
            if num in {"2023", "2024", "2025", "2026"}:
                continue
            filtrados.append(num)
        if not filtrados:
            return ""
        return max(filtrados, key=len)

    linhas = texto.splitlines()
    candidatos = []

    for linha in linhas:
        if re.search(r"fatura|factura|invoice", linha, flags=re.IGNORECASE):
            # formato serie/numero
            m = re.search(r"(\d{4})\s*[/\-]\s*(\d{1,7})", linha)
            if m:
                candidatos.append(m.group(1) + m.group(2))
            for m2 in re.finditer(r"(\d{3,15})", linha):
                candidatos.append(m2.group(1))

    return escolher(candidatos)


def extrair_nota_encomenda(texto: str) -> str:
    texto_norm = texto.replace("\n", " ")

    contexto = re.findall(
        r"(requisi[cç][aã]o.{0,40}?(\d{7,12})|encomenda.{0,40}?(\d{7,12}))",
        texto_norm,
        flags=re.IGNORECASE,
    )
    for grupo in contexto:
        for num in grupo[1:]:
            if num:
                return num

    # ex.: "Ref. Fatura(s) 1125027652"
    m = re.search(r"Fatura\(s\)\s*([0-9]{7,12})", texto_norm, flags=re.IGNORECASE)
    if m:
        return m.group(1)

    return ""


# ============================================================
# Processar um PDF
# ============================================================

def processar_pdf(nome_ficheiro: str, ficheiro_bytes: bytes) -> dict:
    doc = abrir_pdf_bytes(ficheiro_bytes)

    # texto completo (serve para muita coisa)
    texto = extrair_texto_doc(doc)

    origem = "texto"
    nif = ""
    data = ""
    total = ""
    num_fatura = ""
    tipo_doc = ""
    campo_c_qr = ""

    # 1) tentar obter string AT no texto
    qr_str = extrair_qr_string_do_texto(texto)
    campos_qr = {}
    if qr_str:
        campos_qr = parse_qr_at(qr_str)
        origem = "qr"
    else:
        # 2) fallback: QR por imagem
        qr_img = ler_qr_imagem(doc)
        if qr_img and "A:" in qr_img and "B:" in qr_img and "C:" in qr_img:
            campos_qr = parse_qr_at(qr_img)
            origem = "qr"

    if campos_qr:
        nif = campos_qr.get("B", "") or ""
        data = formatar_data_ddmmaaaa(campos_qr.get("D", "") or "")
        total = normalizar_monetario(campos_qr.get("E", "") or "")
        campo_c_qr = campos_qr.get("C", "") or ""
        num_fatura = numero_fatura_de_c(campo_c_qr)

    # 3) complementar com texto se faltar alguma coisa
    if not nif:
        nif = extrair_nif_texto(texto, nome_ficheiro)
    if not data:
        data = extrair_data_texto(texto)
    if not total:
        total = extrair_total_texto(texto)
    if not num_fatura:
        num_fatura = extrair_numero_fatura_texto(texto, nif)

    tipo_doc = detetar_tipo_documento(campo_c_qr, texto, nome_ficheiro)
    nota_encomenda = extrair_nota_encomenda(texto)

    return {
        "ficheiro": nome_ficheiro,
        "origem_dados": origem,
        "tipo_documento": tipo_doc,
        "nif": nif,
        "data_fatura": data,
        "valor_total": total,
        "numero_fatura_digitos": num_fatura,
        "nota_encomenda": nota_encomenda,
    }


# ============================================================
# Streamlit UI
# ============================================================

st.set_page_config(page_title="Extrator de Faturas (QR + Texto)", layout="wide")

st.title("📄 Extrator de Informação de Faturas (QR + Texto)")
st.write(
    "Carrega faturas em PDF (com ou sem QR da AT) e obtenha um ficheiro "
    "para importação na contabilidade (NIF, data, total, nº fatura, nota de encomenda, tipo de documento)."
)

uploaded_files = st.file_uploader(
    "Selecione uma ou mais faturas em PDF",
    type=["pdf", "PDF"],
    accept_multiple_files=True,
)

if uploaded_files:
    if st.button("🔍 Processar faturas"):
        registos = []
        for f in uploaded_files:
            try:
                reg = processar_pdf(f.name, f.read())
            except Exception as e:
                reg = {
                    "ficheiro": f.name,
                    "origem_dados": f"erro: {e}",
                    "tipo_documento": "",
                    "nif": "",
                    "data_fatura": "",
                    "valor_total": "",
                    "numero_fatura_digitos": "",
                    "nota_encomenda": "",
                }
            registos.append(reg)

        df = pd.DataFrame(registos)
        st.success("Processamento concluído.")
        st.dataframe(df, use_container_width=True)

        # Download Excel
        buffer_xlsx = io.BytesIO()
        with pd.ExcelWriter(buffer_xlsx, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)
        buffer_xlsx.seek(0)

        st.download_button(
            label="⬇️ Descarregar Excel",
            data=buffer_xlsx,
            file_name="resumo_faturas.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        # Download CSV
        csv_data = df.to_csv(index=False, sep=";").encode("utf-8-sig")
        st.download_button(
            label="⬇️ Descarregar CSV (; separado)",
            data=csv_data,
            file_name="resumo_faturas.csv",
            mime="text/csv",
        )
else:
    st.info("Carrega primeiro pelo menos um PDF para começar.")
