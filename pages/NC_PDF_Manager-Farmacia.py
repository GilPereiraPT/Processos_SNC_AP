import io
import os
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List, Dict, Tuple

import cv2
import fitz  # PyMuPDF
import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image


# ============================================================
# 0. CONFIGURAÇÃO
# ============================================================

NIF_ADQUIRENTE_ESPERADO = "510445152"
FALHAR_SEM_QR = True
ENTIDADE_PADRAO = "999"
MAPPING_CSV_PATH = "mapeamento_entidades_nc.csv"

# Cabeçalhos exactos do ficheiro de importação
HEADER_IMPORTACAO = [
    "NC",
    "Entidade",
    "Data documento",
    "Data Contabilistica",
    "Nº NC",
    "Série",
    "Subtipo",
    "classificador economico",
    "Classificador funcional",
    "Fonte de financiamento",
    "Programa",
    "Medida",
    "Projeto",
    "Regionalização",
    "Atividade",
    "Natureza",
    "Departamento/Atividade",
    "Conta Debito",
    "Conta a Credito",
    "Valor Lançamento",
    "Centro de custo",
    "Observações Documento",
    "Observaçoes lançamento",
    "Classificação Orgânica",
    "Litigio",
    "Data Litigio",
    "Data Fim Litigio",
    "Plano Pagamento",
    "Data Plano Pagamento",
    "Data Fim Plano Pag",
    "Pag Factoring",
    "Nº Compromisso Assumido",
    "Projeto Documento",
    "Ano Compromisso Assumido",
    "Série Compromisso Assumido",
]


# ============================================================
# 1. FUNÇÕES DE BASE
# ============================================================

def normalizar_texto(s: str) -> str:
    s = str(s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s.upper()


def normalizar_nif(nif: str) -> str:
    return re.sub(r"\D", "", str(nif or "").upper().replace("PT", ""))


def apenas_algarismos(texto: str) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def nif_valido(nif: str) -> bool:
    nif = normalizar_nif(nif)
    if len(nif) != 9:
        return False
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


def formatar_data_yyyymmdd(valor: str) -> str:
    d = formatar_data_ddmmaaaa(valor)
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", d)
    if m:
        return f"{m.group(3)}{m.group(2)}{m.group(1)}"
    if re.fullmatch(r"\d{8}", str(valor or "")):
        return str(valor)
    return d


def today_yyyymmdd() -> str:
    hoje = date.today()
    return f"{hoje.year:04d}{hoje.month:02d}{hoje.day:02d}"


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
        # O último separador é assumido como decimal.
        last = max(v.rfind("."), v.rfind(","))
        inteiro = re.sub(r"[.,]", "", v[:last])
        dec = re.sub(r"\D", "", v[last + 1:])
        dec = (dec + "00")[:2]
        num = float(f"{inteiro}.{dec}")
    elif "," in v:
        partes = v.split(",")
        inteiro = re.sub(r"\D", "", "".join(partes[:-1])) if len(partes) > 1 else re.sub(r"\D", "", partes[0])
        dec = re.sub(r"\D", "", partes[-1]) if len(partes) > 1 else "00"
        dec = (dec + "00")[:2]
        num = float(f"{inteiro}.{dec}")
    elif "." in v:
        partes = v.split(".")
        if len(partes[-1]) == 2:
            inteiro = re.sub(r"\D", "", "".join(partes[:-1]))
            dec = re.sub(r"\D", "", partes[-1])
            num = float(f"{inteiro}.{dec}")
        else:
            num = float(re.sub(r"\D", "", v) or 0)
    else:
        num = float(v or 0)

    return -num if negativo else num


def formatar_valor_pt(valor: float) -> str:
    return f"{float(valor):.2f}".replace(".", ",")


def normalizar_monetario(valor: str) -> str:
    return formatar_valor_pt(normalizar_monetario_para_float(valor))


# ============================================================
# 2. MAPEAMENTO ENTIDADE
# ============================================================

def get_mapping_path(default_path: str) -> str:
    if os.path.isfile(default_path):
        return default_path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(script_dir, default_path)
    if os.path.isfile(candidate):
        return candidate
    return default_path


def load_empresa_mapping(path: str) -> pd.DataFrame:
    if not os.path.isfile(path):
        return pd.DataFrame(columns=["Empresa", "Entidade", "NIF"])

    df = pd.read_csv(path, sep=";", encoding="latin-1", dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    if "Entidade" not in df.columns:
        raise ValueError("O ficheiro de mapeamento tem de ter a coluna 'Entidade'.")

    if "Empresa" not in df.columns and "NIF" not in df.columns and "NIF Emissor" not in df.columns:
        raise ValueError("O mapeamento deve ter pelo menos uma coluna 'Empresa', 'NIF' ou 'NIF Emissor'.")

    return df.fillna("")


def criar_mapas_entidade(mapping_df: pd.DataFrame) -> Tuple[Dict[str, str], Dict[str, str]]:
    mapa_empresa = {}
    mapa_nif = {}

    for _, row in mapping_df.iterrows():
        entidade = str(row.get("Entidade", "")).strip()
        if entidade.endswith(".0"):
            entidade = entidade[:-2]
        if not entidade:
            continue

        empresa = normalizar_texto(row.get("Empresa", ""))
        if empresa:
            mapa_empresa[empresa] = entidade

        nif = normalizar_nif(row.get("NIF", "") or row.get("NIF Emissor", ""))
        if nif:
            mapa_nif[nif] = entidade

    return mapa_empresa, mapa_nif


def obter_entidade(reg: dict, mapa_empresa: Dict[str, str], mapa_nif: Dict[str, str]) -> str:
    nif = normalizar_nif(reg.get("NIF Emissor", ""))
    if nif and nif in mapa_nif:
        return mapa_nif[nif]

    empresa = normalizar_texto(reg.get("Empresa", ""))
    if empresa and empresa in mapa_empresa:
        return mapa_empresa[empresa]

    return ENTIDADE_PADRAO


# ============================================================
# 3. PDF -> IMAGEM / QR ROBUSTO
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
        g_blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 2
    )
    variants.append(thr_adapt)

    _, thr_otsu = cv2.threshold(g_clahe, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(thr_otsu)

    up = cv2.resize(g_clahe, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    up_blur = cv2.GaussianBlur(up, (3, 3), 0)
    up_thr = cv2.adaptiveThreshold(
        up_blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 2
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
# 4. EXTRACÇÃO POR TEXTO / QR
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


def extrair_empresa_texto(texto: str) -> str:
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    lixo = ("fatura", "factura", "nota de crédito", "nota de credito", "nif", "contribuinte", "original")
    for linha in linhas[:20]:
        lnorm = linha.lower()
        if any(x in lnorm for x in lixo):
            continue
        if len(linha) >= 4 and re.search(r"[A-Za-zÀ-ÿ]", linha):
            return linha[:120]
    return ""


def extrair_nif_texto(texto: str, filename: str) -> str:
    candidatos = []
    base = Path(filename).stem
    candidatos.extend(re.findall(r"\b(\d{9})\b", base))

    texto_norm = texto.replace("\n", " ")
    padroes = [
        r"\bContribuinte:?\s*(\d{9})\b",
        r"\bNIF:?\s*PT?\s*(\d{9})\b",
        r"\bN\.?IF:?\s*(\d{9})\b",
        r"\bNIF\s+(\d{9})\b",
    ]

    for p in padroes:
        candidatos.extend(re.findall(p, texto_norm, flags=re.IGNORECASE))

    candidatos.extend(re.findall(r"\b(\d{9})\b", texto_norm))

    vistos = set()
    for c in candidatos:
        c = normalizar_nif(c)
        if c in vistos:
            continue
        vistos.add(c)
        if nif_valido(c) and c != NIF_ADQUIRENTE_ESPERADO:
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
        r"Total\s+a\s+Pagar.*?(-?\d{1,3}(?:\.\d{3})*,\d{2})",
        r"Total\s+Geral.*?(-?\d{1,3}(?:\.\d{3})*,\d{2})",
        r"Total\s+\(EUR\).*?(-?\d{1,3}(?:\.\d{3})*,\d{2})",
        r"Total.*?(-?\d{1,3}(?:\.\d{3})*,\d{2})\s*€",
        r"Total.*?(-?\d+,\d{2})\s*€",
        r"Total.*?(-?\d+\.\d{2})\s*€",
    ]
    for p in padroes:
        m = re.search(p, texto_norm, flags=re.IGNORECASE)
        if m:
            return normalizar_monetario(m.group(1))
    return ""


def extrair_numero_documento_texto(texto: str) -> str:
    texto_norm = texto.replace("\n", " ")

    m = re.search(
        r"\b(FT|FR|FS|NC|ND|VD)\s*([A-Z0-9]{0,20})\s*[/-]\s*(\d{1,12})\b",
        texto_norm,
        flags=re.IGNORECASE,
    )
    if m:
        tipo = m.group(1).upper()
        serie = (m.group(2) or "").upper().strip()
        num = m.group(3)
        return f"{tipo} {serie}/{num}".replace("  ", " ").strip()

    padroes = [
        r"\bN[ºo]\.?\s*Documento[:\s]*([A-Z0-9/ -]{3,40})\b",
        r"\bDocumento[:\s]*([A-Z0-9/ -]{3,40})\b",
        r"\bN[ºo]\.?\s*Fatura[:\s]*([A-Z0-9/ -]{3,40})\b",
    ]

    for p in padroes:
        m = re.search(p, texto_norm, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()

    return ""


def extrair_nota_encomenda(texto: str) -> str:
    texto_norm = texto.replace("\n", " ")

    # Regra específica que já tinhas indicado: 7 dígitos com último par 25.
    m = re.search(r"([123478]\d{4}25)", texto_norm)
    if m:
        return m.group(1)

    padroes = [
        r"(?:Vossa\s+)?Encomenda[:\s\.]*(\d{3,15})",
        r"(?:Vossa\s+)?Requisi[cç][aã]o[:\s\.]*(\d{3,15})",
        r"O\/Ref[:\s\.]*(\d{3,15})",
        r"Nota\s+de\s+Encomenda[:\s\.]*(\d{3,15})",
    ]
    for p in padroes:
        m = re.search(p, texto_norm, flags=re.IGNORECASE)
        if m:
            return m.group(1)

    return ""


def detetar_tipo_texto(texto: str, filename: str) -> str:
    txt = texto.lower()
    fn = filename.lower()

    if "nota de crédito" in txt or "nota de credito" in txt or "credito" in fn:
        return "Nota de Crédito"
    if "fatura-recibo" in txt or "factura-recibo" in txt:
        return "Fatura-Recibo"
    if "venda a dinheiro" in txt:
        return "Venda a Dinheiro"
    if "fatura simplificada" in txt or "factura simplificada" in txt:
        return "Fatura Simplificada"
    if "fatura" in txt or "factura" in txt:
        return "Fatura"

    return ""


def validar_adquirente(campos_qr: dict) -> Tuple[str, str, str]:
    nif_b = normalizar_nif(campos_qr.get("B", ""))
    if not nif_b:
        return "ERRO", "QR sem campo B (NIF do adquirente).", ""
    if not nif_valido(nif_b):
        return "ERRO", f"NIF do adquirente (B) inválido: {nif_b}", nif_b
    if nif_b != NIF_ADQUIRENTE_ESPERADO:
        return "ERRO", f"Documento não emitido ao NIF {NIF_ADQUIRENTE_ESPERADO} (B={nif_b}).", nif_b
    return "OK", "", nif_b


def processar_pdf(nome_ficheiro: str, ficheiro_bytes: bytes, pages_to_try: int = 1) -> dict:
    doc = abrir_pdf_bytes(ficheiro_bytes)

    try:
        texto = extrair_texto_doc(doc)

        origem = "Texto (Regex)"
        campos_qr = {}
        qr_raw = ""

        # 1) QR em texto oculto
        qr_str = extrair_qr_string_do_texto(texto)
        if qr_str:
            campos_qr = parse_qr_at(qr_str)
            if campos_qr:
                origem = "QR (Texto Oculto)"
                qr_raw = qr_str

        # 2) QR por imagem robusto
        if not campos_qr:
            qr_img = ler_qr_robusto(doc, pages_to_try=pages_to_try)
            if qr_img and "A:" in qr_img and ("B:" in qr_img or "H:" in qr_img):
                campos_qr = parse_qr_at(qr_img)
                if campos_qr:
                    origem = "QR (Imagem - Robusto)"
                    qr_raw = qr_img

        estado = "OK"
        erro = ""
        nif_emissor = ""
        nif_adquirente = ""
        data_doc = ""
        total = ""
        num_doc = ""
        tipo_doc = ""
        encomenda = ""

        if campos_qr:
            estado, erro, nif_adquirente = validar_adquirente(campos_qr)

            nif_a = normalizar_nif(campos_qr.get("A", ""))
            if not nif_a:
                estado = "ERRO"
                erro = (erro + " " if erro else "") + "QR sem campo A (NIF do emissor)."
            elif not nif_valido(nif_a):
                estado = "ERRO"
                erro = (erro + " " if erro else "") + f"NIF do emissor (A) inválido: {nif_a}"

            nif_emissor = nif_a
            data_doc = formatar_data_ddmmaaaa(campos_qr.get("F", ""))

            # Nos QR AT, O costuma ser total com IVA; M aparece nalguns documentos.
            total = normalizar_monetario(campos_qr.get("O", "") or campos_qr.get("M", ""))

            num_doc = (campos_qr.get("G", "") or "").strip()

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

            encomenda = extrair_nota_encomenda(texto)

        else:
            if FALHAR_SEM_QR:
                estado = "ERRO"
                erro = "Não foi possível ler QR; validação do adquirente exige QR."

            nif_emissor = extrair_nif_texto(texto, nome_ficheiro)
            nif_adquirente = ""
            data_doc = extrair_data_texto(texto)
            total = extrair_total_texto(texto)
            num_doc = extrair_numero_documento_texto(texto)
            tipo_doc = detetar_tipo_texto(texto, nome_ficheiro)
            encomenda = extrair_nota_encomenda(texto)

        empresa = extrair_empresa_texto(texto)

        return {
            "Ficheiro": nome_ficheiro,
            "Estado": estado,
            "Erro": erro.strip(),
            "Origem": origem,
            "Tipo": tipo_doc,
            "NIF Emissor": nif_emissor,
            "NIF Adquirente": nif_adquirente,
            "Empresa": empresa,
            "Data": data_doc,
            "Total": total,
            "Num. Documento": num_doc,
            "Encomenda": encomenda,
            "Debug QR": qr_raw,
        }

    finally:
        doc.close()


# ============================================================
# 5. GERAÇÃO DO EXCEL DE IMPORTAÇÃO
# ============================================================

def gerar_linha_importacao(reg: dict, entidade: str, tipo_prefixo: str) -> dict:
    tipo_doc = normalizar_texto(reg.get("Tipo", ""))
    data_doc = formatar_data_yyyymmdd(reg.get("Data", ""))
    valor = normalizar_monetario_para_float(reg.get("Total", ""))

    # Notas de crédito devem ficar positivas para importação NC.
    # Se o PDF trouxer negativo, converte para positivo.
    valor_import = abs(valor)

    num_original = str(reg.get("Num. Documento", "") or "").strip()
    numero_nc = apenas_algarismos(num_original)

    if not numero_nc:
        numero_nc = apenas_algarismos(Path(str(reg.get("Ficheiro", ""))).stem)

    obs_parts = []
    if tipo_prefixo:
        obs_parts.append(tipo_prefixo)
    if reg.get("Encomenda"):
        obs_parts.append(f"Enc. {reg.get('Encomenda')}")
    if num_original:
        obs_parts.append(num_original)
    if reg.get("Empresa"):
        obs_parts.append(str(reg.get("Empresa"))[:80])

    observacoes_doc = " | ".join(obs_parts).strip()

    linha = {col: "" for col in HEADER_IMPORTACAO}
    linha["NC"] = "NC"
    linha["Entidade"] = str(entidade or ENTIDADE_PADRAO).replace(".0", "")
    linha["Data documento"] = data_doc
    linha["Data Contabilistica"] = today_yyyymmdd()
    linha["Nº NC"] = numero_nc
    linha["Série"] = ""
    linha["Subtipo"] = ""
    linha["classificador economico"] = "02.01.09.C0.00"
    linha["Classificador funcional"] = "0730"
    linha["Fonte de financiamento"] = "511"
    linha["Programa"] = "015"
    linha["Medida"] = "022"
    linha["Projeto"] = ""
    linha["Regionalização"] = ""
    linha["Atividade"] = "533"
    linha["Natureza"] = ""
    linha["Departamento/Atividade"] = "1"
    linha["Conta Debito"] = "221111"
    linha["Conta a Credito"] = "31826111"
    linha["Valor Lançamento"] = formatar_valor_pt(valor_import)
    linha["Centro de custo"] = ""
    linha["Observações Documento"] = observacoes_doc
    linha["Observaçoes lançamento"] = ""
    linha["Classificação Orgânica"] = "121904000"
    linha["Litigio"] = ""
    linha["Data Litigio"] = ""
    linha["Data Fim Litigio"] = ""
    linha["Plano Pagamento"] = ""
    linha["Data Plano Pagamento"] = ""
    linha["Data Fim Plano Pag"] = ""
    linha["Pag Factoring"] = ""
    linha["Nº Compromisso Assumido"] = ""
    linha["Projeto Documento"] = ""
    linha["Ano Compromisso Assumido"] = ""
    linha["Série Compromisso Assumido"] = ""

    return linha


def gerar_dataframe_importacao(df_ok: pd.DataFrame, mapa_empresa: Dict[str, str], mapa_nif: Dict[str, str], tipo_prefixo: str) -> pd.DataFrame:
    linhas = []

    for _, row in df_ok.iterrows():
        reg = row.to_dict()
        entidade = obter_entidade(reg, mapa_empresa, mapa_nif)
        linhas.append(gerar_linha_importacao(reg, entidade, tipo_prefixo))

    return pd.DataFrame(linhas, columns=HEADER_IMPORTACAO)


def escrever_excel(df_import: pd.DataFrame, df_controlo: pd.DataFrame, df_erros: pd.DataFrame) -> io.BytesIO:
    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_import.to_excel(writer, index=False, sheet_name="Importacao")
        df_controlo.to_excel(writer, index=False, sheet_name="Controlo")
        if not df_erros.empty:
            df_erros.to_excel(writer, index=False, sheet_name="Erros")

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

                    # Forçar texto nos campos de códigos para não perder zeros nem alterar formato.
                    if ws.title == "Importacao":
                        cell.number_format = "@"

                ws.column_dimensions[col_letter].width = min(max(max_len + 2, 10), 45)

            for cell in ws[1]:
                cell.font = cell.font.copy(bold=True)
                cell.alignment = cell.alignment.copy(horizontal="center")

        # Folha de importação: garantir texto em todos os campos.
        if "Importacao" in wb.sheetnames:
            ws = wb["Importacao"]
            for row in ws.iter_rows():
                for cell in row:
                    cell.number_format = "@"

    buffer.seek(0)
    return buffer


# ============================================================
# 6. INTERFACE STREAMLIT
# ============================================================

st.set_page_config(page_title="NC PDF → Excel Importação", layout="wide")

st.title("📄 Notas de Crédito PDF → Excel robusto")
st.markdown(
    """
Ferramenta para ler PDFs através do **QR AT** e gerar um Excel de importação contabilística.

A leitura dos PDFs usa:
- QR em texto oculto;
- QR por imagem com pré-processamento;
- fallback por texto apenas para diagnóstico;
- validação do NIF do adquirente;
- folha de controlo e folha de erros.
"""
)

with st.sidebar:
    st.header("Configuração")
    tipo_prefixo = st.selectbox("Tipo / origem", ["APIFARMA", "PAYBACK", "NC", "OUTRO"], index=0)
    pages_to_try = st.number_input("Páginas a tentar para QR", min_value=1, max_value=10, value=1)
    exportar_so_ok = st.checkbox("Gerar importação apenas com documentos OK", value=True)

    st.caption(f"NIF adquirente esperado: {NIF_ADQUIRENTE_ESPERADO}")

mapping_path = get_mapping_path(MAPPING_CSV_PATH)

try:
    mapping_df = load_empresa_mapping(mapping_path)
    mapa_empresa, mapa_nif = criar_mapas_entidade(mapping_df)
    if not mapping_df.empty:
        st.success(f"✅ Mapeamento carregado: {len(mapping_df)} linhas")
        with st.expander("Ver mapeamento"):
            st.dataframe(mapping_df, use_container_width=True)
    else:
        mapa_empresa, mapa_nif = {}, {}
        st.warning("⚠️ Não encontrei ficheiro de mapeamento. Os documentos ficarão com entidade 999.")
except Exception as e:
    st.error(f"Erro no mapeamento: {e}")
    st.stop()

uploaded_files = st.file_uploader(
    "Carrega os PDFs em lote",
    type=["pdf"],
    accept_multiple_files=True,
)

if uploaded_files:
    st.info(f"{len(uploaded_files)} PDF(s) carregado(s).")

    if st.button("🚀 Processar PDFs e gerar Excel", type="primary"):
        registos = []
        progress = st.progress(0)

        for i, f in enumerate(uploaded_files):
            try:
                reg = processar_pdf(f.name, f.read(), pages_to_try=int(pages_to_try))
                registos.append(reg)
            except Exception as e:
                registos.append({
                    "Ficheiro": f.name,
                    "Estado": "ERRO",
                    "Erro": f"Exceção ao processar: {e}",
                    "Origem": "Erro",
                    "Tipo": "",
                    "NIF Emissor": "",
                    "NIF Adquirente": "",
                    "Empresa": "",
                    "Data": "",
                    "Total": "",
                    "Num. Documento": "",
                    "Encomenda": "",
                    "Debug QR": "",
                })

            progress.progress((i + 1) / len(uploaded_files))

        progress.empty()

        df = pd.DataFrame(registos)

        # Acrescentar entidade calculada ao controlo
        df["Entidade Calculada"] = df.apply(lambda r: obter_entidade(r.to_dict(), mapa_empresa, mapa_nif), axis=1)

        cols = [
            "Ficheiro",
            "Estado",
            "Erro",
            "Entidade Calculada",
            "NIF Adquirente",
            "NIF Emissor",
            "Empresa",
            "Data",
            "Total",
            "Num. Documento",
            "Tipo",
            "Encomenda",
            "Origem",
            "Debug QR",
        ]
        df = df[[c for c in cols if c in df.columns]]

        oks = df[df["Estado"] == "OK"].copy()
        erros = df[df["Estado"] != "OK"].copy()

        st.success(f"✅ {len(oks)} documento(s) OK.")
        if len(erros) > 0:
            st.error(f"❌ {len(erros)} documento(s) com erro.")
            st.dataframe(erros, use_container_width=True)

        st.subheader("Controlo")
        st.dataframe(df, use_container_width=True)

        df_para_import = oks if exportar_so_ok else df.copy()
        df_import = gerar_dataframe_importacao(df_para_import, mapa_empresa, mapa_nif, tipo_prefixo)

        st.subheader("Pré-visualização da importação")
        st.dataframe(df_import, use_container_width=True)

        buffer_xlsx = escrever_excel(df_import, df, erros)

        nome_saida = f"NC_{tipo_prefixo}_importacao_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"

        st.download_button(
            label="📥 Descarregar Excel final",
            data=buffer_xlsx.getvalue(),
            file_name=nome_saida,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

        if len(erros) > 0:
            st.warning("Há documentos com erro. Confirma a folha 'Erros' antes de importar.")
else:
    st.info("Carrega os PDFs para começar.")
