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
# 0. Configuração (Regra de Controlo)
# ============================================================

# Todos os documentos têm de ser emitidos ao NIF do adquirente abaixo.
NIF_ADQUIRENTE_ESPERADO = "510445152"

# Se TRUE: documentos sem QR (ou sem campo B) são ERRO, para evitar falsos positivos.
FALHAR_SEM_QR = True

# ============================================================
# 1. Funções Auxiliares de Formatação e Validação
# ============================================================

def normalizar_nif(nif: str) -> str:
    """Remove PT, espaços e caracteres não numéricos."""
    return re.sub(r"\D", "", (nif or "").upper().replace("PT", ""))


def formatar_data_ddmmaaaa(valor: str) -> str:
    """Converte datas para DD/MM/AAAA. Suporta (2023-01-01) e (20230101)."""
    if not valor:
        return ""
    valor = str(valor).strip()

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
    """Devolve sempre formato PT: 1234,56 (tenta forçar 2 casas decimais)."""
    if not valor:
        return ""
    v = re.sub(r"[^\d.,]", "", str(valor))
    if not v:
        return ""

    if "." in v and "," in v:
        last = max(v.rfind("."), v.rfind(","))
        inteiro = re.sub(r"[.,]", "", v[:last])
        dec = re.sub(r"[^\d]", "", v[last + 1 :])
        dec = (dec + "00")[:2]
        return f"{inteiro},{dec}"

    if "," in v:
        a, *b = v.split(",")
        inteiro = re.sub(r"[^\d]", "", a)
        dec = re.sub(r"[^\d]", "", b[0]) if b else ""
        dec = (dec + "00")[:2]
        return f"{inteiro},{dec}"

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

    # Conjunto típico. Ajusta se necessário.
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
# 2. PDF -> Imagem / QR robusto (detetar, recortar, corrigir perspetiva)
# ============================================================

def abrir_pdf_bytes(file_bytes: bytes):
    return fitz.open(stream=file_bytes, filetype="pdf")


def pagina_para_cv2(doc, page_index: int = 0, zoom: float = 3.0) -> np.ndarray:
    """Renderiza uma página com zoom para melhorar leitura de QR."""
    page = doc.load_page(page_index)
    matriz = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matriz)
    mode = "RGBA" if pix.alpha else "RGB"
    img_pil = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
    if img_pil.mode == "RGBA":
        img_pil = img_pil.convert("RGB")
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)


def _order_points(pts: np.ndarray) -> np.ndarray:
    """Ordena 4 pontos (tl, tr, br, bl) para warpPerspective."""
    pts = pts.reshape(4, 2).astype(np.float32)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)

    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(diff)]
    bl = pts[np.argmax(diff)]

    return np.array([tl, tr, br, bl], dtype=np.float32)


def _warp_quad(image: np.ndarray, quad_pts: np.ndarray, pad: int = 10) -> np.ndarray:
    """Warp de um quadrilátero para um retângulo (com padding)."""
    pts = _order_points(quad_pts)

    w1 = np.linalg.norm(pts[1] - pts[0])
    w2 = np.linalg.norm(pts[2] - pts[3])
    h1 = np.linalg.norm(pts[3] - pts[0])
    h2 = np.linalg.norm(pts[2] - pts[1])
    W = int(max(w1, w2)) + pad * 2
    H = int(max(h1, h2)) + pad * 2
    W = max(W, 250)
    H = max(H, 250)

    dst = np.array(
        [[pad, pad], [W - pad - 1, pad], [W - pad - 1, H - pad - 1], [pad, H - pad - 1]],
        dtype=np.float32,
    )

    M = cv2.getPerspectiveTransform(pts, dst)
    warped = cv2.warpPerspective(image, M, (W, H), flags=cv2.INTER_CUBIC)
    return warped


def _preprocess_variants(bgr: np.ndarray) -> List[np.ndarray]:
    """Gera variantes de pré-processamento para maximizar taxa de descodificação."""
    variants = []
    variants.append(bgr)

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    variants.append(gray)

    # CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    g_clahe = clahe.apply(gray)
    variants.append(g_clahe)

    # Blur + adaptativo
    g_blur = cv2.GaussianBlur(g_clahe, (3, 3), 0)
    thr_adapt = cv2.adaptiveThreshold(
        g_blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 2
    )
    variants.append(thr_adapt)

    # Otsu
    _, thr_otsu = cv2.threshold(g_clahe, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(thr_otsu)

    # Upscale + adaptativo (muito eficaz em QR fino)
    up = cv2.resize(g_clahe, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    up_blur = cv2.GaussianBlur(up, (3, 3), 0)
    up_thr = cv2.adaptiveThreshold(
        up_blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 2
    )
    variants.append(up_thr)

    # Sharpen (unsharp mask)
    blur = cv2.GaussianBlur(g_clahe, (0, 0), sigmaX=1.0)
    sharp = cv2.addWeighted(g_clahe, 1.6, blur, -0.6, 0)
    variants.append(sharp)

    # Upscale + sharpen
    up2 = cv2.resize(sharp, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    variants.append(up2)

    return variants


def _decode_with_detector(detector: cv2.QRCodeDetector, img) -> Optional[str]:
    """Tenta detectAndDecodeMulti (se disponível) e detectAndDecode."""
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
    """
    Leitura QR robusta:
    - zooms múltiplos
    - variantes de pré-processamento
    - detetar pontos -> warp -> tentar novamente
    """
    detector = cv2.QRCodeDetector()

    max_pages = min(pages_to_try, doc.page_count)
    zooms = [3.0, 4.0, 2.5]

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

            # Detetar e warpar
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
# 3. Extração via Texto (Fallback)
# ============================================================

def extrair_texto_doc(doc) -> str:
    texto_total: List[str] = []
    for page in doc:
        texto_total.append(page.get_text("text"))
    return "\n".join(texto_total)


def extrair_qr_string_do_texto(texto: str) -> Optional[str]:
    """Procura conteúdo do QR em texto oculto (quando existe)."""
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
    """
    Parser do QR AT:
    - normaliza | para *
    - remove espaços
    - split por *
    - split por ':' (1 vez)
    """
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


def extrair_nif_texto(texto: str, filename: str) -> str:
    """Extrai NIF devolvendo o primeiro NIF válido (dígito de controlo)."""
    candidatos: List[str] = []

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
    """Extrai o número do documento preservando tipo + série (quando existe)."""
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

    m = re.search(r"\bN[ºo]\.?\s*Documento[:\s]*([A-Z0-9/ -]{3,40})\b", texto_norm, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()

    return ""


def extrair_nota_encomenda(texto: str) -> str:
    """Extrai Nota de Encomenda; prioriza 7 dígitos (1/2/3/4/7/8....25)."""
    texto_norm = texto.replace("\n", " ")

    novo_padrao = r"([123478]\d{4}25)"
    m = re.search(novo_padrao, texto_norm)
    if m:
        return m.group(1)

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
# 4. Processamento Principal (com validação forte do adquirente)
# ============================================================

def validar_adquirente(campos_qr: dict) -> (str, str, str):
    """
    Devolve (estado, erro, nif_adquirente_normalizado).
    Regras:
      - B tem de existir, ser NIF válido, e ser igual ao NIF_ADQUIRENTE_ESPERADO.
    """
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

        # 2) QR por imagem (robusto)
        if not campos_qr:
            qr_img = ler_qr_robusto(doc, pages_to_try=pages_to_try)
            if qr_img and "A:" in qr_img and ("B:" in qr_img or "H:" in qr_img):
                campos_qr = parse_qr_at(qr_img)
                if campos_qr:
                    origem = "QR (Imagem - Robusto)"
                    qr_raw = qr_img

        # Campos de saída
        estado = "OK"
        erro = ""
        nif_emissor = ""
        nif_adquirente = ""
        data = ""
        total = ""
        num_fatura = ""
        tipo_doc = ""
        nota_enc = ""

        if campos_qr:
            # Validar adquirente (B) com regra forte
            estado, erro, nif_adquirente = validar_adquirente(campos_qr)

            # Emissor (A) — assumido como emissor porque B está fixo e validado
            nif_a = normalizar_nif(campos_qr.get("A", ""))
            if not nif_a:
                estado = "ERRO"
                erro = (erro + " " if erro else "") + "QR sem campo A (NIF do emissor)."
            elif not nif_valido(nif_a):
                estado = "ERRO"
                erro = (erro + " " if erro else "") + f"NIF do emissor (A) inválido: {nif_a}"
            nif_emissor = nif_a

            data = formatar_data_ddmmaaaa(campos_qr.get("F", ""))
            total = normalizar_monetario(campos_qr.get("O", "") or campos_qr.get("M", ""))
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
            # Sem QR: por defeito, falha para evitar erros (configurável)
            if FALHAR_SEM_QR:
                estado = "ERRO"
                erro = "Não foi possível ler QR (e a validação do adquirente exige QR)."
                # Mesmo assim tenta preencher algum contexto para ajudar na análise
                nif_emissor = extrair_nif_texto(texto, nome_ficheiro)
                data = extrair_data_texto(texto)
                total = extrair_total_texto(texto)
                num_fatura = extrair_numero_fatura_texto(texto)
                tipo_doc = detetar_tipo_texto(texto, nome_ficheiro)
                nota_enc = extrair_nota_encomenda(texto)
            else:
                # Modo permissivo: mantém fallback texto (não recomendado no teu caso)
                nif_emissor = extrair_nif_texto(texto, nome_ficheiro)
                nif_adquirente = ""
                data = extrair_data_texto(texto)
                total = extrair_total_texto(texto)
                num_fatura = extrair_numero_fatura_texto(texto)
                tipo_doc = detetar_tipo_texto(texto, nome_ficheiro)
                nota_enc = extrair_nota_encomenda(texto)

        return {
            "Ficheiro": nome_ficheiro,
            "Origem": origem,
            "Estado": estado,
            "Erro": erro.strip(),
            "Tipo": tipo_doc,
            "NIF Emissor": nif_emissor,
            "NIF Adquirente": nif_adquirente,
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
    f"""
Esta ferramenta extrai dados de faturas PDF para contabilidade.

Regras de controlo:
- O **NIF do adquirente (QR campo B)** tem de ser **{NIF_ADQUIRENTE_ESPERADO}**.
- Se não for, o documento é marcado como **ERRO**.
- NIFs são validados pelo **dígito de controlo**.
- Leitura QR por imagem é feita com pré-processamento **robusto** (CLAHE, threshold adaptativo, upscale, sharpen e correção de perspetiva).
"""
)

col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    uploaded_files = st.file_uploader(
        "Arraste as faturas para aqui (PDF)",
        type=["pdf"],
        accept_multiple_files=True,
    )

with col2:
    pages_to_try = st.number_input(
        "Páginas a tentar (QR por imagem)",
        min_value=1,
        max_value=10,
        value=1,
        help="Aumenta se o QR não estiver na 1.ª página.",
    )

with col3:
    exportar_apenas_ok = st.checkbox("Exportar só OK", value=True)

if uploaded_files:
    if st.button("🚀 Iniciar Processamento", type="primary"):
        progress_bar = st.progress(0)
        registos = []

        for i, f in enumerate(uploaded_files):
            try:
                reg = processar_pdf(f.name, f.read(), pages_to_try=int(pages_to_try))
                registos.append(reg)
            except Exception as e:
                registos.append({
                    "Ficheiro": f.name,
                    "Origem": "Erro",
                    "Estado": "ERRO",
                    "Erro": f"Exceção ao processar: {e}",
                    "Tipo": "",
                    "NIF Emissor": "",
                    "NIF Adquirente": "",
                    "Data": "",
                    "Total": "",
                    "Num. Fatura": "",
                    "Encomenda": "",
                    "Debug QR": "",
                })
            progress_bar.progress((i + 1) / len(uploaded_files))

        progress_bar.empty()

        df = pd.DataFrame(registos)

        cols = [
            "Ficheiro",
            "Estado",
            "Erro",
            "NIF Adquirente",
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

        oks = df[df["Estado"] == "OK"].copy()
        erros = df[df["Estado"] != "OK"].copy()

        st.success(f"{len(oks)} documentos OK.")
        if len(erros) > 0:
            st.error(f"{len(erros)} documentos com ERRO.")
            st.dataframe(erros, use_container_width=True)

        st.subheader("Todos os documentos")
        st.dataframe(df, use_container_width=True)

        # Dataset a exportar
        df_export = oks if exportar_apenas_ok else df

        col_d1, col_d2 = st.columns(2)

        buffer_xlsx = io.BytesIO()
        with pd.ExcelWriter(buffer_xlsx, engine="openpyxl") as writer:
            df_export.to_excel(writer, index=False, sheet_name="Export")
            # Folha adicional com erros (sempre útil)
            if len(erros) > 0:
                erros.to_excel(writer, index=False, sheet_name="Erros")
        buffer_xlsx.seek(0)

        col_d1.download_button(
            label="📥 Download Excel",
            data=buffer_xlsx,
            file_name=f"faturas_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

        csv_data = df_export.to_csv(index=False, sep=";").encode("utf-8-sig")
        col_d2.download_button(
            label="📥 Download CSV",
            data=csv_data,
            file_name=f"faturas_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

        with st.expander("🛠️ Debug do último documento (QR)"):
            ultimo = registos[-1] if registos else {}
            if "QR" in (ultimo.get("Origem") or "") and ultimo.get("Debug QR"):
                st.write("Dados brutos extraídos do QR:")
                st.json(parse_qr_at(ultimo.get("Debug QR", "")))
                st.write("**Legenda:** A=NIF Emitente | B=NIF Adquirente | F=Data | G=Num Doc | O/M=Total | D=Tipo")
            else:
                st.write("O último documento não foi lido via QR (ou não há QR para mostrar).")
else:
    st.info("Aguardando ficheiros...")
