import io
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import cv2
import fitz  # PyMuPDF
import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image


# ============================================================
# 0. Configuração
# ============================================================

COLUNAS_EXCEL = [
    "Nome do ficheiro",
    "Empresa",
    "Nº da NC",
    "Data da NC",
    "Valor",
    "Valor utilizado",
    "Data de registo no SGICM",
]


# Mapeamento opcional por NIF do emitente.
# Podes acrescentar aqui fornecedores conforme forem aparecendo.
EMPRESAS_POR_NIF = {
    "500165595": "Lilly Portugal - Produtos Farmacêuticos, Lda.",
    "500191360": "Merck, S.A.",
    "502811194": "Octapharma Produtos Farmacêuticos, Lda.",
    "503108710": "Vifor Pharma Portugal, S.A.",
}



# ============================================================
# 1. Funções auxiliares
# ============================================================

def normalizar_monetario_para_float(valor: str) -> float:
    if valor is None:
        return 0.0

    v = str(valor).strip()
    if not v or v.lower() in ("nan", "none"):
        return 0.0

    v = re.sub(r"[^\d,.\-]", "", v)
    if not v:
        return 0.0

    negativo = "-" in v
    v = v.replace("-", "")

    if "." in v and "," in v:
        last = max(v.rfind("."), v.rfind(","))
        inteiro = re.sub(r"[.,]", "", v[:last])
        dec = re.sub(r"\D", "", v[last + 1:])
        dec = (dec + "00")[:2]
        num = float(f"{inteiro}.{dec}") if inteiro else 0.0
    elif "," in v:
        partes = v.split(",")
        inteiro = re.sub(r"\D", "", "".join(partes[:-1])) if len(partes) > 1 else re.sub(r"\D", "", partes[0])
        dec = re.sub(r"\D", "", partes[-1]) if len(partes) > 1 else "00"
        dec = (dec + "00")[:2]
        num = float(f"{inteiro or '0'}.{dec}")
    elif "." in v:
        partes = v.split(".")
        if len(partes[-1]) == 2:
            inteiro = re.sub(r"\D", "", "".join(partes[:-1])) or "0"
            dec = re.sub(r"\D", "", partes[-1])
            num = float(f"{inteiro}.{dec}")
        else:
            num = float(re.sub(r"\D", "", v) or 0)
    else:
        num = float(v or 0)

    return -num if negativo else num


def formatar_valor_pt(valor) -> str:
    try:
        return f"{float(valor):.2f}".replace(".", ",")
    except Exception:
        return ""


def formatar_data_ddmmaaaa(valor: str) -> str:
    if not valor:
        return ""

    valor = str(valor).strip()

    if re.fullmatch(r"\d{8}", valor):
        return f"{valor[6:8]}/{valor[4:6]}/{valor[0:4]}"

    formatos = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"]
    for fmt in formatos:
        try:
            return datetime.strptime(valor, fmt).strftime("%d/%m/%Y")
        except ValueError:
            pass

    m = re.search(r"(\d{2})[./-](\d{2})[./-](\d{4})", valor)
    if m:
        return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"

    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", valor)
    if m:
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"

    return valor


def limpar_empresa(nome: str) -> str:
    nome = str(nome or "").strip()
    nome = re.sub(r"\s+", " ", nome)
    nome = re.sub(r"\bNIF\b.*$", "", nome, flags=re.IGNORECASE).strip()
    return nome[:150]


# ============================================================
# 2. PDF -> imagem / QR robusto
# ============================================================

def abrir_pdf_bytes(file_bytes: bytes):
    return fitz.open(stream=file_bytes, filetype="pdf")


def pagina_para_cv2(doc, page_index: int = 0, zoom: float = 3.0) -> np.ndarray:
    page = doc.load_page(page_index)
    matriz = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matriz)
    mode = "RGBA" if pix.alpha else "RGB"
    img_pil = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
    if img_pil.mode == "RGBA":
        img_pil = img_pil.convert("RGB")
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)


def _order_points(pts: np.ndarray) -> np.ndarray:
    pts = pts.reshape(4, 2).astype(np.float32)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)

    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(diff)]
    bl = pts[np.argmax(diff)]

    return np.array([tl, tr, br, bl], dtype=np.float32)


def _warp_quad(image: np.ndarray, quad_pts: np.ndarray, pad: int = 10) -> np.ndarray:
    pts = _order_points(quad_pts)

    w1 = np.linalg.norm(pts[1] - pts[0])
    w2 = np.linalg.norm(pts[2] - pts[3])
    h1 = np.linalg.norm(pts[3] - pts[0])
    h2 = np.linalg.norm(pts[2] - pts[1])

    W = max(int(max(w1, w2)) + pad * 2, 250)
    H = max(int(max(h1, h2)) + pad * 2, 250)

    dst = np.array(
        [[pad, pad], [W - pad - 1, pad], [W - pad - 1, H - pad - 1], [pad, H - pad - 1]],
        dtype=np.float32,
    )

    M = cv2.getPerspectiveTransform(pts, dst)
    return cv2.warpPerspective(image, M, (W, H), flags=cv2.INTER_CUBIC)


def _preprocess_variants(bgr: np.ndarray) -> List[np.ndarray]:
    variants = [bgr]

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if len(bgr.shape) == 3 else bgr
    variants.append(gray)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    g_clahe = clahe.apply(gray)
    variants.append(g_clahe)

    g_blur = cv2.GaussianBlur(g_clahe, (3, 3), 0)

    thr_adapt = cv2.adaptiveThreshold(
        g_blur,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        2,
    )
    variants.append(thr_adapt)

    _, thr_otsu = cv2.threshold(g_clahe, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(thr_otsu)

    up = cv2.resize(g_clahe, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    up_blur = cv2.GaussianBlur(up, (3, 3), 0)
    up_thr = cv2.adaptiveThreshold(
        up_blur,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        2,
    )
    variants.append(up_thr)

    blur = cv2.GaussianBlur(g_clahe, (0, 0), sigmaX=1.0)
    sharp = cv2.addWeighted(g_clahe, 1.6, blur, -0.6, 0)
    variants.append(sharp)

    up2 = cv2.resize(sharp, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    variants.append(up2)

    return variants


def _decode_with_detector(detector: cv2.QRCodeDetector, img) -> Optional[str]:
    try:
        ok, decoded_info, _, _ = detector.detectAndDecodeMulti(img)
        if ok and decoded_info:
            for d in decoded_info:
                if d and d.strip():
                    return d.strip()
    except Exception:
        pass

    try:
        data, _, _ = detector.detectAndDecode(img)
        if data and data.strip():
            return data.strip()
    except Exception:
        pass

    return None


def ler_qr_robusto(doc, pages_to_try: int = 1) -> Optional[str]:
    detector = cv2.QRCodeDetector()
    max_pages = min(pages_to_try, doc.page_count)
    zooms = [3.0, 4.0, 2.5, 5.0]

    for p in range(max_pages):
        for zoom in zooms:
            try:
                img_bgr = pagina_para_cv2(doc, page_index=p, zoom=zoom)
            except Exception:
                continue

            for var in _preprocess_variants(img_bgr):
                data = _decode_with_detector(detector, var)
                if data:
                    return data

            try:
                gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
                ok, pts = detector.detect(gray)
                if ok and pts is not None and len(pts) >= 4:
                    warped = _warp_quad(img_bgr, pts, pad=20)
                    for var in _preprocess_variants(warped):
                        data = _decode_with_detector(detector, var)
                        if data:
                            return data
            except Exception:
                pass

    return None


# ============================================================
# 3. Extração de dados
# ============================================================

def extrair_texto_doc(doc) -> str:
    texto_total = []
    for page in doc:
        texto_total.append(page.get_text("text"))
    return "\n".join(texto_total)


def extrair_qr_string_do_texto(texto: str) -> Optional[str]:
    if not texto:
        return None

    t = re.sub(r"\s+", " ", texto).strip()

    m = re.search(r"\bA:.*?\bB:.*?\bF:", t)
    if m:
        return t[m.start():].strip()

    m = re.search(r"\bA:.*?\bB:", t)
    if m:
        return t[m.start():].strip()

    return None


def parse_qr_at(data: str) -> dict:
    if not data:
        return {}

    s = str(data).replace("|", "*")
    s = re.sub(r"\s+", "", s)
    parts = [p for p in s.split("*") if p]

    res = {}
    for p in parts:
        if ":" not in p:
            continue
        k, v = p.split(":", 1)
        if k and len(k) == 1 and k.isalpha():
            res[k.upper()] = v

    return res



def obter_nif_emissor_qr(campos_qr: dict) -> str:
    """
    No QR AT português normal, o campo A costuma ser o NIF do emitente.
    Nalguns layouts/exportações pode vir noutro campo, por isso procura um NIF válido.
    """
    if not campos_qr:
        return ""

    a = re.sub(r"\D", "", str(campos_qr.get("A", "")))
    if len(a) == 9:
        return a

    for _, valor in campos_qr.items():
        nif = re.sub(r"\D", "", str(valor or ""))
        if len(nif) == 9:
            return nif

    return ""


def obter_empresa_do_qr(campos_qr: dict) -> str:
    """
    Tenta retirar o nome da empresa directamente do QR.

    Nota: no QR AT standard, normalmente o campo A é o NIF do emitente,
    não o nome. Mas alguns PDFs/softwares colocam dados adicionais no texto
    descodificado. Esta função aproveita esses campos quando existirem.
    """
    if not campos_qr:
        return ""

    # 1) Campos prováveis se algum software acrescentar nome/designação.
    chaves_preferidas = [
        "EMPRESA",
        "NOME",
        "NAME",
        "EMITENTE",
        "FORNECEDOR",
        "SUPPLIER",
        "VENDOR",
        "RAZAO",
        "RAZÃO",
        "DESIGNACAO",
        "DESIGNAÇÃO",
    ]

    for chave in chaves_preferidas:
        for k, v in campos_qr.items():
            if str(k).upper() == chave:
                cand = limpar_empresa(v)
                if cand and re.search(r"[A-Za-zÀ-ÿ]", cand) and len(cand) >= 4:
                    return cand

    # 2) Se algum campo tiver texto longo com letras e não for campo técnico/monetário/data.
    campos_excluir = {
        "A",  # NIF emitente no QR AT normal
        "B",  # NIF adquirente no QR AT normal
        "C", "D", "E", "F", "G", "H",
        "I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8",
        "J1", "J2", "J3", "J4", "J5", "J6", "J7", "J8",
        "K1", "K2", "K3", "K4", "K5", "K6", "K7", "K8",
        "L", "M", "N", "O", "P", "Q", "R",
    }

    lixo = re.compile(
        r"(processado\s+por\s+programa|programa\s+certificado|certificado|"
        r"^\d+$|^\d+[,.]\d{2}$|^\d{4}-\d{2}-\d{2}$|"
        r"nota\s+de\s+cr[eé]dito|fatura|factura|total|iva|atcud)",
        flags=re.IGNORECASE,
    )

    candidatos = []
    for k, v in campos_qr.items():
        k_norm = str(k).upper().strip()
        val = str(v or "").strip()
        if not val:
            continue
        if k_norm in campos_excluir:
            continue
        if lixo.search(val):
            continue
        if re.search(r"[A-Za-zÀ-ÿ]", val) and len(val) >= 4:
            candidatos.append(limpar_empresa(val))

    if candidatos:
        # escolher o candidato com mais letras
        candidatos = sorted(
            set(candidatos),
            key=lambda x: len(re.findall(r"[A-Za-zÀ-ÿ]", x)),
            reverse=True,
        )
        return candidatos[0]

    # 3) Se o campo A não for apenas um NIF e tiver letras, pode ser empresa.
    a_raw = str(campos_qr.get("A", "") or "").strip()
    if a_raw and not re.fullmatch(r"PT?\d{9}", a_raw, flags=re.IGNORECASE):
        if re.search(r"[A-Za-zÀ-ÿ]", a_raw):
            return limpar_empresa(a_raw)

    return ""


def extrair_empresa_texto(texto: str, nif_emissor: str = "") -> str:
    """
    Extrai a empresa emitente do PDF.

    Estratégia:
    1) se o NIF do emissor estiver no dicionário EMPRESAS_POR_NIF, usa esse valor;
    2) procura linhas próximas do NIF do emissor;
    3) ignora linhas técnicas do AT / software certificado;
    4) usa primeiras linhas úteis como fallback.
    """
    nif_emissor = re.sub(r"\D", "", str(nif_emissor or ""))

    if nif_emissor in EMPRESAS_POR_NIF:
        return EMPRESAS_POR_NIF[nif_emissor]

    if not texto:
        return ""

    linhas = [re.sub(r"\s+", " ", l).strip() for l in texto.splitlines() if l.strip()]

    lixo_regex = re.compile(
        r"(processado\s+por\s+programa|programa\s+certificado|certificado\s+n[.ºo]*|"
        r"\bAT\b|autoridade\s+tribut[aá]ria|qr\s*code|c[oó]digo\s+qr|"
        r"hash|software|saft|iva\s+inclu[ií]do|iva|contribuinte|nif|"
        r"nota\s+de\s+cr[eé]dito|fatura|factura|original|duplicado|"
        r"p[aá]gina|page|data|documento|total|subtotal|valor|"
        r"exmo|cliente|morada|telefone|email|www\.|http|capital\s+social|"
        r"conservat[oó]ria|matr[ií]cula|registad[ao])",
        flags=re.IGNORECASE,
    )

    def linha_valida_empresa(linha: str) -> bool:
        if not linha:
            return False
        if lixo_regex.search(linha):
            return False
        if len(linha) < 4:
            return False
        if not re.search(r"[A-Za-zÀ-ÿ]", linha):
            return False
        # evita moradas puras
        if re.search(r"\b(rua|av\.|avenida|estrada|largo|praça|praceta|c[oó]digo postal|apartado)\b", linha, flags=re.IGNORECASE):
            return False
        # evita linhas quase só numéricas/símbolos
        letras = len(re.findall(r"[A-Za-zÀ-ÿ]", linha))
        if letras < 3:
            return False
        return True

    # 1) Procurar perto do NIF do emissor.
    if nif_emissor:
        for idx, linha in enumerate(linhas):
            linha_digits = re.sub(r"\D", "", linha)
            if nif_emissor and nif_emissor in linha_digits:
                candidatos = []

                # linha anterior, duas anteriores, e parte antes do NIF na própria linha
                if idx - 1 >= 0:
                    candidatos.append(linhas[idx - 1])
                if idx - 2 >= 0:
                    candidatos.append(linhas[idx - 2])

                antes_nif = re.split(nif_emissor, linha)[0].strip()
                if antes_nif:
                    candidatos.append(antes_nif)

                for cand in candidatos:
                    cand = limpar_empresa(cand)
                    if linha_valida_empresa(cand):
                        return cand

    # 2) Padrões em texto corrido: empresa antes de NIF/contribuinte.
    texto_flat = " ".join(linhas)
    padroes = [
        r"([A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9 .,ªº&'\-\/]{4,120})\s+(?:NIF|Contribuinte)[:\s]*(?:PT)?\d{9}",
        r"([A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9 .,ªº&'\-\/]{4,120})\s+(?:N\.?I\.?F\.?)[:\s]*(?:PT)?\d{9}",
    ]

    for p in padroes:
        m = re.search(p, texto_flat, flags=re.IGNORECASE)
        if m:
            emp = limpar_empresa(m.group(1))
            # fica só com a última parte se vier texto lixo antes
            partes = re.split(r"(?:original|duplicado|nota\s+de\s+cr[eé]dito|fatura|factura)", emp, flags=re.IGNORECASE)
            emp = limpar_empresa(partes[-1])
            if linha_valida_empresa(emp):
                return emp

    # 3) Fallback: primeiras linhas úteis, mas ignorando lixo técnico.
    for linha in linhas[:40]:
        cand = limpar_empresa(linha)
        if linha_valida_empresa(cand):
            return cand

    return ""


def extrair_numero_nc_texto(texto: str) -> str:
    if not texto:
        return ""

    texto_flat = re.sub(r"\s+", " ", texto)

    padroes = [
        r"\bNC\s*([A-Z0-9]{0,20})\s*[/-]\s*(\d{1,12})\b",
        r"\bNota\s+de\s+Cr[eé]dito\s*(?:n[.ºo]*|número|num\.?)?[:\s]*([A-Z0-9/ -]{3,40})",
        r"\bN[.ºo]*\s*(?:Documento|Doc\.?)[:\s]*((?:NC)?[A-Z0-9/ -]{3,40})",
    ]

    for p in padroes:
        m = re.search(p, texto_flat, flags=re.IGNORECASE)
        if m:
            if len(m.groups()) == 2:
                serie = (m.group(1) or "").strip()
                numero = (m.group(2) or "").strip()
                return f"NC {serie}/{numero}".replace("  ", " ").strip()
            return m.group(1).strip()

    return ""


def extrair_data_nc_texto(texto: str) -> str:
    if not texto:
        return ""

    texto_flat = re.sub(r"\s+", " ", texto)

    padroes = [
        r"Data\s+(?:da\s+)?(?:Nota\s+de\s+Cr[eé]dito|Documento|Emiss[aã]o)[:\s]*(\d{2}[./-]\d{2}[./-]\d{4})",
        r"(?:Nota\s+de\s+Cr[eé]dito|NC).*?(\d{2}[./-]\d{2}[./-]\d{4})",
        r"\b(\d{4}-\d{2}-\d{2})\b",
    ]

    for p in padroes:
        m = re.search(p, texto_flat, flags=re.IGNORECASE)
        if m:
            return formatar_data_ddmmaaaa(m.group(1))

    datas = re.findall(r"\b(\d{2}[./-]\d{2}[./-]\d{4})\b", texto_flat)
    return formatar_data_ddmmaaaa(datas[0]) if datas else ""


def extrair_valor_nc_texto(texto: str) -> str:
    if not texto:
        return ""

    texto_flat = re.sub(r"\s+", " ", texto)

    padroes = [
        r"Total\s+(?:da\s+)?(?:Nota\s+de\s+Cr[eé]dito|Documento).*?(-?\d{1,3}(?:\.\d{3})*,\d{2})",
        r"Total\s+a\s+Cr[eé]dito.*?(-?\d{1,3}(?:\.\d{3})*,\d{2})",
        r"Total\s+Geral.*?(-?\d{1,3}(?:\.\d{3})*,\d{2})",
        r"Total\s+\(EUR\).*?(-?\d{1,3}(?:\.\d{3})*,\d{2})",
        r"Total.*?(-?\d{1,3}(?:\.\d{3})*,\d{2})\s*€",
        r"Total.*?(-?\d+,\d{2})\s*€",
        r"Valor\s+Total.*?(-?\d{1,3}(?:\.\d{3})*,\d{2})",
    ]

    for p in padroes:
        m = re.search(p, texto_flat, flags=re.IGNORECASE)
        if m:
            return formatar_valor_pt(abs(normalizar_monetario_para_float(m.group(1))))

    # fallback: maior valor monetário encontrado no documento
    valores = re.findall(r"-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2}", texto_flat)
    if valores:
        nums = [abs(normalizar_monetario_para_float(v)) for v in valores]
        return formatar_valor_pt(max(nums))

    return ""


def processar_pdf_nc(nome_ficheiro: str, ficheiro_bytes: bytes, pages_to_try: int = 1) -> dict:
    doc = abrir_pdf_bytes(ficheiro_bytes)

    try:
        texto = extrair_texto_doc(doc)
        campos_qr = {}
        origem = "Texto"

        qr_str = extrair_qr_string_do_texto(texto)
        if qr_str:
            campos_qr = parse_qr_at(qr_str)
            if campos_qr:
                origem = "QR texto oculto"

        if not campos_qr:
            qr_img = ler_qr_robusto(doc, pages_to_try=pages_to_try)
            if qr_img and "A:" in qr_img:
                campos_qr = parse_qr_at(qr_img)
                if campos_qr:
                    origem = "QR imagem"

        nif_emissor_qr = obter_nif_emissor_qr(campos_qr)
        empresa = obter_empresa_do_qr(campos_qr)

        if not empresa and nif_emissor_qr in EMPRESAS_POR_NIF:
            empresa = EMPRESAS_POR_NIF[nif_emissor_qr]

        if not empresa:
            empresa = extrair_empresa_texto(texto, nif_emissor_qr)

        numero_nc = ""
        data_nc = ""
        valor = ""

        if campos_qr:
            # QR AT:
            # D = tipo doc; G = número documento; F = data; O/M = total.
            tipo_doc = (campos_qr.get("D", "") or "").upper().strip()

            if tipo_doc and tipo_doc != "NC":
                origem += f" / Aviso: tipo QR {tipo_doc}"

            numero_nc = (campos_qr.get("G", "") or "").strip()
            data_nc = formatar_data_ddmmaaaa(campos_qr.get("F", ""))
            valor = formatar_valor_pt(abs(normalizar_monetario_para_float(campos_qr.get("O", "") or campos_qr.get("M", ""))))

        if not numero_nc:
            numero_nc = extrair_numero_nc_texto(texto)

        if not data_nc:
            data_nc = extrair_data_nc_texto(texto)

        if not valor or valor == "0,00":
            valor = extrair_valor_nc_texto(texto)

        estado = "OK"
        erro = ""

        if not empresa:
            estado = "VERIFICAR"
            erro += "Empresa não encontrada. "

        if not numero_nc:
            estado = "VERIFICAR"
            erro += "Nº da NC não encontrado. "

        if not data_nc:
            estado = "VERIFICAR"
            erro += "Data da NC não encontrada. "

        if not valor:
            estado = "VERIFICAR"
            erro += "Valor não encontrado. "

        return {
            "Nome do ficheiro": nome_ficheiro,
            "Empresa": nif_emissor_qr,
            "Nº da NC": numero_nc,
            "Data da NC": data_nc,
            "Valor": valor,
            "Valor utilizado": "",
            "Data de registo no SGICM": "",
            "Estado": estado,
            "Erro": erro.strip(),
            "Origem": origem,
            "NIF Emissor QR": nif_emissor_qr,
            "QR bruto": qr_str if qr_str else (qr_img if 'qr_img' in locals() and qr_img else ""),
        }

    finally:
        doc.close()


# ============================================================
# 4. Excel
# ============================================================

def escrever_excel(df_final: pd.DataFrame, df_controlo: pd.DataFrame) -> io.BytesIO:
    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_final.to_excel(writer, index=False, sheet_name="NC_APIFARMA_PAYBACK")
        df_controlo.to_excel(writer, index=False, sheet_name="Controlo")

        wb = writer.book

        for ws in wb.worksheets:
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions

            for col_cells in ws.columns:
                max_len = 0
                col_letter = col_cells[0].column_letter

                for cell in col_cells:
                    val = "" if cell.value is None else str(cell.value)
                    max_len = max(max_len, len(val))

                    # Datas e valores ficam editáveis pelo utilizador.
                    if ws.title == "NC_APIFARMA_PAYBACK":
                        if cell.row == 1:
                            continue
                        header = ws.cell(row=1, column=cell.column).value
                        if header in ["Nome do ficheiro", "Empresa", "Nº da NC", "Data da NC", "Data de registo no SGICM"]:
                            cell.number_format = "@"
                        elif header in ["Valor", "Valor utilizado"]:
                            cell.number_format = "#,##0.00"

                            if isinstance(cell.value, str):
                                try:
                                    cell.value = normalizar_monetario_para_float(cell.value)
                                except Exception:
                                    pass

                ws.column_dimensions[col_letter].width = min(max(max_len + 2, 12), 55)

            for cell in ws[1]:
                cell.font = cell.font.copy(bold=True)
                cell.alignment = cell.alignment.copy(horizontal="center")

    buffer.seek(0)
    return buffer


# ============================================================
# 5. Interface Streamlit
# ============================================================

st.set_page_config(page_title="NC APIFARMA / PAYBACK PDF → Excel", layout="wide")

st.title("📄 NC APIFARMA / PAYBACK — PDF para Excel")
st.markdown(
    """
Carrega as **notas de crédito em PDF** e gera um Excel simples com:

**Nome do ficheiro, Empresa, Nº da NC, Data da NC, Valor, Valor utilizado e Data de registo no SGICM.**

As duas últimas colunas ficam em branco para preencher depois.
"""
)

col1, col2 = st.columns([3, 1])

with col1:
    uploaded_files = st.file_uploader(
        "Carrega os PDFs em lote",
        type=["pdf"],
        accept_multiple_files=True,
    )

with col2:
    pages_to_try = st.number_input(
        "Páginas a tentar para QR",
        min_value=1,
        max_value=10,
        value=1,
    )

if uploaded_files:
    st.info(f"{len(uploaded_files)} PDF(s) carregado(s).")

    if st.button("🚀 Criar Excel", type="primary"):
        progress = st.progress(0)
        registos = []

        for i, f in enumerate(uploaded_files):
            try:
                registos.append(processar_pdf_nc(f.name, f.read(), pages_to_try=int(pages_to_try)))
            except Exception as e:
                registos.append({
                    "Nome do ficheiro": f.name,
                    "Empresa": "",
                    "Nº da NC": "",
                    "Data da NC": "",
                    "Valor": "",
                    "Valor utilizado": "",
                    "Data de registo no SGICM": "",
                    "Estado": "ERRO",
                    "Erro": str(e),
                    "Origem": "Erro",
                    "NIF Emissor QR": "",
                    "QR bruto": "",
                })

            progress.progress((i + 1) / len(uploaded_files))

        progress.empty()

        df_controlo = pd.DataFrame(registos)

        df_final = df_controlo[COLUNAS_EXCEL].copy()

        st.subheader("Pré-visualização do Excel")
        st.dataframe(df_final, use_container_width=True)

        problemas = df_controlo[df_controlo["Estado"] != "OK"].copy()
        if not problemas.empty:
            st.warning(f"{len(problemas)} linha(s) para verificar.")
            st.dataframe(problemas, use_container_width=True)
        else:
            st.success("Todas as linhas foram extraídas sem avisos.")

        buffer = escrever_excel(df_final, df_controlo)

        nome_saida = f"NC_APIFARMA_PAYBACK_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"

        st.download_button(
            "📥 Descarregar Excel",
            data=buffer.getvalue(),
            file_name=nome_saida,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
else:
    st.info("Carrega os PDFs para começar.")
