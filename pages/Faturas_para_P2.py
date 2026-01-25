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
# 1. Funções Auxiliares de Formatação e Validação
# ============================================================

def formatar_data_ddmmaaaa(valor: str) -> str:
    """
    Converte datas para DD/MM/AAAA.
    Suporta formatos do texto (2023-01-01) e do QR (20230101).
    """
    if not valor:
        return ""
    valor = valor.strip()

    if re.fullmatch(r"\d{8}", valor):
        return f"{valor[6:8]}/{valor[4:6]}/{valor[0:4]}"

    formatos = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"]
    for fmt in formatos:
        try:
            dt = datetime.strptime(valor, fmt)
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            continue

    m = re.search(r"(\d{2})[./-](\d{2})[./-](\d{4})", valor)
    if m:
        return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"

    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", valor)
    if m:
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"

    return valor


def normalizar_monetario(valor: str) -> str:
    """
    Devolve sempre formato PT: 1234,56 (com 2 casas decimais quando possível).
    Aceita valores com separadores ., , e espaços.
    """
    if not valor:
        return ""
    v = re.sub(r"[^\d.,]", "", str(valor))
    if not v:
        return ""

    # Se tem '.' e ',', assume último separador como decimal
    if "." in v and "," in v:
        last = max(v.rfind("."), v.rfind(","))
        inteiro = re.sub(r"[.,]", "", v[:last])
        dec = re.sub(r"[^\d]", "", v[last + 1 :])
        dec = (dec + "00")[:2]
        return f"{inteiro},{dec}"

    # Só vírgula
    if "," in v:
        partes = v.split(",")
        inteiro = re.sub(r"[^\d]", "", partes[0])
        dec = re.sub(r"[^\d]", "", partes[1]) if len(partes) > 1 else ""
        dec = (dec + "00")[:2]
        return f"{inteiro},{dec}"

    # Só ponto (assume decimal no último ponto)
    if "." in v:
        partes = v.split(".")
        if len(partes) == 1:
            return partes[0]
        inteiro = re.sub(r"[^\d]", "", "".join(partes[:-1]))
        dec = re.sub(r"[^\d]", "", partes[-1])
        dec = (dec + "00")[:2]
        return f"{inteiro},{dec}"

    return v


def nif_valido(nif: str) -> bool:
    """
    Valida NIF português (9 dígitos) pelo dígito de controlo.
    dv = 11 - (soma % 11); se dv >= 10 => 0.
    """
    if not nif:
        return False
    nif = re.sub(r"\D", "", str(nif))

    if len(nif) != 9:
        return False

    # Mantém o conjunto típico usado no teu código. Se precisares, pode ser alargado.
    if nif[0] not in "1235689":
        return False

    total = 0
    for i in range(8):
        total += int(nif[i]) * (9 - i)

    resto = total % 11
    dv = 11 - resto
    if dv >= 10:
        dv = 0

    return int(nif[8]) == dv


# ============================================================
# 2. Processamento de Imagem e Leitura de QR
# ============================================================

def abrir_pdf_bytes(file_bytes: bytes):
    return fitz.open(stream=file_bytes, filetype="pdf")


def primeira_pagina_para_cv2(doc) -> np.ndarray:
    """
    Renderiza a primeira página com ZOOM (2.0x) para melhorar a leitura do QR.
    """
    page = doc.load_page(0)
    matriz = fitz.Matrix(2.0, 2.0)
    pix = page.get_pixmap(matrix=matriz)

    mode = "RGBA" if pix.alpha else "RGB"
    img_pil = Image.frombytes(mode, [pix.width, pix.height], pix.samples)

    if img_pil.mode == "RGBA":
        img_pil = img_pil.convert("RGB")

    img_cv2 = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
    return img_cv2


def ler_qr_imagem(doc) -> Optional[str]:
    """
    Tenta ler QR a partir da 1ª página como imagem com estratégias de fallback.
    """
    try:
        img_cv2 = primeira_pagina_para_cv2(doc)
    except Exception:
        return None

    detector = cv2.QRCodeDetector()

    data, _, _ = detector.detectAndDecode(img_cv2)
    if data:
        return data.strip()

    gray = cv2.cvtColor(img_cv2, cv2.COLOR_BGR2GRAY)
    data, _, _ = detector.detectAndDecode(gray)
    if data:
        return data.strip()

    # Threshold adaptativo (melhor do que threshold fixo em muitos PDFs)
    gray_blur = cv2.GaussianBlur(gray, (3, 3), 0)
    thr = cv2.adaptiveThreshold(
        gray_blur, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31, 2
    )
    data, _, _ = detector.detectAndDecode(thr)
    if data:
        return data.strip()

    return None


def extrair_qr_string_do_texto(texto: str) -> Optional[str]:
    """
    Procura string AT (A:...*B:...*...) diretamente no texto do PDF.
    Torna a pesquisa mais robusta em PDFs com texto partido.
    """
    if not texto:
        return None

    t = re.sub(r"\s+", " ", texto).strip()

    # Heurística: começa em A: e tenta apanhar um bloco com vários campos.
    # Não é perfeito, mas aumenta muito a taxa de acerto em “texto oculto”.
    m = re.search(r"\bA:.*?\bB:.*?\bF:", t)
    if m:
        return m.group(0).strip()

    # fallback mais permissivo
    m = re.search(r"\bA:.*?\bB:", t)
    return m.group(0).strip() if m else None


def parse_qr_at(data: str) -> dict:
    """
    Parser robusto para o QR da AT.
    Abordagem por split em '*' e divisão 'chave:valor' (mais resiliente do que regex).
    """
    if not data:
        return {}

    s = str(data).replace("|", "*")
    s = re.sub(r"\s+", "", s)
    partes = [p for p in s.split("*") if p]

    res = {}
    for p in partes:
        if ":" not in p:
            continue
        k, v = p.split(":", 1)
        if k and len(k) == 1 and k.isalpha():
            res[k.upper()] = v
    return res


# ============================================================
# 3. Extração via Texto (Fallback)
# ============================================================

def extrair_texto_doc(doc) -> str:
    texto_total: List[str] = []
    for page in doc:
        texto_total.append(page.get_text("text"))
    return "\n".join(texto_total)


def extrair_nif_texto(texto: str, filename: str) -> str:
    """
    Extrai NIF a partir do filename e/ou do texto, devolvendo o primeiro NIF válido encontrado.
    Se não encontrar nenhum válido, devolve vazio.
    """
    candidatos = []

    # 1) Do nome do ficheiro
    base = Path(filename).stem
    candidatos.extend(re.findall(r"\b(\d{9})\b", base))

    # 2) Do texto
    texto_norm = texto.replace("\n", " ")

    padroes = [
        r"\bContribuinte:?\s*(\d{9})\b",
        r"\bNIF:?\s*PT?\s*(\d{9})\b",
        r"\bN\.?IF:?\s*(\d{9})\b",
        r"\bNIF\s+(\d{9})\b",
    ]
    for p in padroes:
        candidatos.extend(re.findall(p, texto_norm, flags=re.IGNORECASE))

    # 3) Fallback: qualquer 9 dígitos no texto
    candidatos.extend(re.findall(r"\b(\d{9})\b", texto_norm))

    vistos = set()
    for c in candidatos:
        c = re.sub(r"\D", "", c)
        if c in vistos:
            continue
        vistos.add(c)
        if nif_valido(c):
            return c

    return ""


def extrair_data_texto(texto: str) -> str:
    texto_norm = texto.replace("\n", " ")
    m = re.search(
        r"Data\s+(?:de\s+)?Emiss[aã]o[:\s]*(\d{2}[./-]\d{2}[./-]\d{4})",
        texto_norm,
        flags=re.IGNORECASE,
    )
    if m:
        return formatar_data_ddmmaaaa(m.group(1))

    m = re.search(r"(\d{4}-\d{2}-\d{2})", texto_norm)
    if m:
        return formatar_data_ddmmaaaa(m.group(1))

    datas = re.findall(r"\b(\d{2}[./-]\d{2}[./-]\d{4})\b", texto_norm)
    return formatar_data_ddmmaaaa(datas[0]) if datas else ""


def extrair_total_texto(texto: str) -> str:
    texto_norm = texto.replace("\n", " ")
    padroes = [
        r"Total\s+a\s+Pagar.*?(\d{1,3}(?:\.\d{3})*,\d{2})",
        r"Total\s+Geral.*?(\d{1,3}(?:\.\d{3})*,\d{2})",
        r"Total\s+\(EUR\).*?(\d{1,3}(?:\.\d{3})*,\d{2})",
        r"Total.*?(\d{1,3}(?:\.\d{3})*,\d{2})\s*€",
        r"Total.*?(\d+,\d{2})\s*€",
        r"Total.*?(\d+\.\d{2})\s*€",
    ]
    for p in padroes:
        m = re.search(p, texto_norm, flags=re.IGNORECASE)
        if m:
            return normalizar_monetario(m.group(1))
    return ""


def extrair_numero_fatura_texto(texto: str) -> str:
    """
    Extrai o número do documento preservando tipo + série (quando existe).
    Ex.: "FT A/1234" -> "FT A/1234"
    """
    texto_norm = texto.replace("\n", " ")

    # Padrões comuns PT
    m = re.search(
        r"\b(FT|FR|FS|NC|ND|VD)\s*([A-Z0-9]{0,15})\s*[/-]\s*(\d{1,10})\b",
        texto_norm,
        flags=re.IGNORECASE,
    )
    if m:
        tipo, serie, num = m.group(1).upper(), m.group(2).upper().strip(), m.group(3)
        if serie:
            return f"{tipo} {serie}/{num}"
        return f"{tipo} {num}"

    # fallback menos estrito (linhas com “fatura” etc.)
    linhas = texto.splitlines()
    for linha in linhas:
        if re.search(r"fatura|factura|invoice", linha, flags=re.IGNORECASE):
            m2 = re.search(r"\b(FT|FR|FS|NC|ND|VD)\b.*?(\d{1,10})\b", linha, flags=re.IGNORECASE)
            if m2:
                return f"{m2.group(1).upper()} {m2.group(2)}"

    return ""


def extrair_nota_encomenda(texto: str) -> str:
    """
    Extrai a Nota de Encomenda, priorizando o padrão específico de 7 algarismos:
    começa por [1,2,3,4,7,8] e termina em 25.
    """
    texto_norm = texto.replace("\n", " ")

    novo_padrao = r"([123478]\d{4}25)"
    m_especifico = re.search(novo_padrao, texto_norm)
    if m_especifico:
        return m_especifico.group(1)

    padroes_antigos = [
        r"(?:Vossa\s+)?Encomenda[:\s\.]*(\d{3,15})",
        r"(?:Vossa\s+)?Requisi[cç][aã]o[:\s\.]*(\d{3,15})",
        r"O\/Ref[:\s\.]*(\d{3,15})",
    ]
    for p in padroes_antigos:
        m = re.search(p, texto_norm, flags=re.IGNORECASE)
        if m:
            return m.group(1)

    return ""


def detetar_tipo_texto(texto: str, filename: str) -> str:
    txt = texto.lower()
    if "nota de crédito" in txt or "nota de credito" in txt:
        return "Nota de Crédito"
    if "fatura-recibo" in txt:
        return "Fatura-Recibo"
    if "venda a dinheiro" in txt:
        return "Venda a Dinheiro"
    if "fatura simplificada" in txt:
        return "Fatura Simplificada"
    if "fatura" in txt:
        return "Fatura"

    if "credito" in filename.lower():
        return "Nota de Crédito"
    return "Fatura"


# ============================================================
# 4. Processamento Principal (Lógica de Decisão)
# ============================================================

def processar_pdf(nome_ficheiro: str, ficheiro_bytes: bytes) -> dict:
    doc = abrir_pdf_bytes(ficheiro_bytes)
    try:
        texto = extrair_texto_doc(doc)

        origem = "Texto (Regex)"
        campos_qr = {}
        qr_raw = ""

        # 1) QR embutido em texto (quando existe)
        qr_str = extrair_qr_string_do_texto(texto)
        if qr_str:
            campos_qr = parse_qr_at(qr_str)
            if campos_qr:
                origem = "QR (Texto Oculto)"
                qr_raw = qr_str

        # 2) QR via imagem
        if not campos_qr:
            qr_img = ler_qr_imagem(doc)
            if qr_img and "A:" in qr_img and ("B:" in qr_img or "H:" in qr_img):
                campos_qr = parse_qr_at(qr_img)
                if campos_qr:
                    origem = "QR (Imagem)"
                    qr_raw = qr_img

        nif = ""
        data = ""
        total = ""
        num_fatura = ""
        tipo_doc = ""
        nota_enc = ""

        # 3) Mapeamento de dados
        if campos_qr:
            # --- DADOS QR ---
            nif_qr = campos_qr.get("A", "").upper().replace("PT", "").replace(" ", "")
            nif_qr = re.sub(r"\D", "", nif_qr)

            # Validação do NIF (se falhar, tenta texto)
            nif = nif_qr if nif_valido(nif_qr) else extrair_nif_texto(texto, nome_ficheiro)

            data = formatar_data_ddmmaaaa(campos_qr.get("F", ""))

            total_raw = campos_qr.get("O", "") or campos_qr.get("M", "")
            total = normalizar_monetario(total_raw)

            # Preserva série quando existir
            num_fatura = (campos_qr.get("G", "") or "").strip()

            tipo_code = (campos_qr.get("D", "") or "").strip().upper()
            mapa_tipos = {
                "FT": "Fatura",
                "FR": "Fatura-Recibo",
                "NC": "Nota de Crédito",
                "ND": "Nota de Débito",
                "FS": "Fatura Simplificada",
                "VD": "Venda a Dinheiro",
            }
            tipo_doc = mapa_tipos.get(tipo_code, tipo_code)

            nota_enc = extrair_nota_encomenda(texto)

        else:
            # --- FALLBACK TEXTO ---
            nif = extrair_nif_texto(texto, nome_ficheiro)
            data = extrair_data_texto(texto)
            total = extrair_total_texto(texto)
            num_fatura = extrair_numero_fatura_texto(texto)
            tipo_doc = detetar_tipo_texto(texto, nome_ficheiro)
            nota_enc = extrair_nota_encomenda(texto)

        return {
            "Ficheiro": nome_ficheiro,
            "Origem": origem,
            "Tipo": tipo_doc,
            "NIF Emissor": nif,
            "Data": data,
            "Total": total,
            "Num. Fatura": num_fatura,
            "Encomenda": nota_enc,
            "Debug QR": qr_raw,
        }
    finally:
        doc.close()


# ============================================================
# 5. Interface Streamlit
# ============================================================

st.set_page_config(page_title="Processar Faturas P2", layout="wide")

st.title("📄 Processador de Faturas (AT Portugal)")
st.markdown(
    """
Esta ferramenta extrai dados de faturas PDF para contabilidade.  
O campo **Encomenda** prioriza o padrão de 7 algarismos que começa por **1, 2, 3, 4, 7 ou 8** e termina em **25**.  
O **NIF** é validado pelo **dígito de controlo** (quando não valida, tenta fallback por texto).
"""
)

col1, col2 = st.columns([2, 1])

with col1:
    uploaded_files = st.file_uploader(
        "Arraste as faturas para aqui (PDF)",
        type=["pdf"],
        accept_multiple_files=True,
    )

if uploaded_files:
    if st.button("🚀 Iniciar Processamento", type="primary"):
        progress_bar = st.progress(0)
        registos = []

        for i, f in enumerate(uploaded_files):
            try:
                reg = processar_pdf(f.name, f.read())
                registos.append(reg)
            except Exception as e:
                st.error(f"Erro ao processar {f.name}: {e}")
            progress_bar.progress((i + 1) / len(uploaded_files))

        progress_bar.empty()

        if registos:
            df = pd.DataFrame(registos)

            cols = [
                "Ficheiro",
                "NIF Emissor",
                "Data",
                "Total",
                "Num. Fatura",
                "Tipo",
                "Encomenda",
                "Origem",
                "Debug QR",
            ]
            cols = [c for c in cols if c in df.columns]
            df = df[cols]

            st.success(f"{len(registos)} documentos processados com sucesso.")

            c1, c2 = st.columns(2)
            com_qr = df[df["Origem"].str.contains("QR", na=False)].shape[0]
            c1.metric("Lidos via QR (Alta precisão)", com_qr)
            c2.metric("Lidos via Texto (Estimativa)", len(registos) - com_qr)

            st.dataframe(df, use_container_width=True)

            with st.expander("🛠️ Ver detalhes do último QR lido (Debug)"):
                ultimo = registos[-1]
                if "QR" in ultimo.get("Origem", ""):
                    st.write("Dados brutos extraídos do QR:")
                    st.json(parse_qr_at(ultimo.get("Debug QR", "")))
                    st.write("**Legenda:** A=NIF Emissor | F=Data | G=Num Doc | O/M=Total | D=Tipo")
                else:
                    st.write("O último documento não foi lido via QR.")

            col_d1, col_d2 = st.columns(2)

            buffer_xlsx = io.BytesIO()
            with pd.ExcelWriter(buffer_xlsx, engine="openpyxl") as writer:
                df.to_excel(writer, index=False)
            buffer_xlsx.seek(0)

            col_d1.download_button(
                label="📥 Download Excel",
                data=buffer_xlsx,
                file_name=f"faturas_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

            csv_data = df.to_csv(index=False, sep=";").encode("utf-8-sig")
            col_d2.download_button(
                label="📥 Download CSV",
                data=csv_data,
                file_name=f"faturas_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                use_container_width=True,
            )
else:
    st.info("Aguardando ficheiros...")
