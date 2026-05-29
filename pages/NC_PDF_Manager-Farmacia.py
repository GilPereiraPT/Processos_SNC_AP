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
    "Empresa",  # neste caso fica com o NIF do emissor
    "Nº da NC",
    "Data da NC",
    "Valor",
    "Valor utilizado",
    "Data de registo no SGICM",
]

COLUNAS_CONTROLO = COLUNAS_EXCEL + [
    "Estado",
    "Erro",
    "Origem",
    "NIF Emissor QR",
    "QR bruto",
]

CHAVE_COLS = ["Empresa", "Nº da NC"]


# ============================================================
# 1. Funções auxiliares
# ============================================================

def normalizar_monetario_para_float(valor) -> float:
    if valor is None:
        return 0.0

    if isinstance(valor, (int, float)) and not pd.isna(valor):
        return float(valor)

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
        inteiro = re.sub(r"[.,]", "", v[:last]) or "0"
        dec = re.sub(r"\D", "", v[last + 1:])
        dec = (dec + "00")[:2]
        num = float(f"{inteiro}.{dec}")
    elif "," in v:
        partes = v.split(",")
        inteiro = re.sub(r"\D", "", "".join(partes[:-1])) if len(partes) > 1 else re.sub(r"\D", "", partes[0])
        inteiro = inteiro or "0"
        dec = re.sub(r"\D", "", partes[-1]) if len(partes) > 1 else "00"
        dec = (dec + "00")[:2]
        num = float(f"{inteiro}.{dec}")
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


def normalizar_chave(valor) -> str:
    if valor is None:
        return ""
    s = str(valor).strip()
    if s.lower() in ("nan", "none"):
        return ""
    s = re.sub(r"\s+", "", s)
    return s.upper()


def criar_chave_linha(row) -> str:
    nif = normalizar_chave(row.get("Empresa", ""))
    nc = normalizar_chave(row.get("Nº da NC", ""))
    return f"{nif}|{nc}"


def garantir_colunas(df: pd.DataFrame, colunas: List[str]) -> pd.DataFrame:
    df = df.copy()
    for c in colunas:
        if c not in df.columns:
            df[c] = ""
    return df[colunas]


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


def normalizar_nif(nif: str) -> str:
    return re.sub(r"\D", "", str(nif or "").upper().replace("PT", ""))


def obter_nif_emissor_qr(campos_qr: dict) -> str:
    if not campos_qr:
        return ""

    # No QR AT, A é o NIF do emitente.
    nif_a = normalizar_nif(campos_qr.get("A", ""))
    if len(nif_a) == 9:
        return nif_a

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
        qr_raw = ""

        qr_str = extrair_qr_string_do_texto(texto)
        if qr_str:
            campos_qr = parse_qr_at(qr_str)
            if campos_qr:
                origem = "QR texto oculto"
                qr_raw = qr_str

        if not campos_qr:
            qr_img = ler_qr_robusto(doc, pages_to_try=pages_to_try)
            if qr_img and "A:" in qr_img:
                campos_qr = parse_qr_at(qr_img)
                if campos_qr:
                    origem = "QR imagem"
                    qr_raw = qr_img

        nif_emissor = obter_nif_emissor_qr(campos_qr)

        # Empresa fica com o NIF do emissor, conforme definido.
        empresa = nif_emissor

        numero_nc = ""
        data_nc = ""
        valor = ""

        if campos_qr:
            tipo_doc = (campos_qr.get("D", "") or "").upper().strip()

            if tipo_doc and tipo_doc != "NC":
                origem += f" / Aviso: tipo QR {tipo_doc}"

            numero_nc = (campos_qr.get("G", "") or "").strip()
            data_nc = formatar_data_ddmmaaaa(campos_qr.get("F", ""))
            valor = formatar_valor_pt(
                abs(normalizar_monetario_para_float(campos_qr.get("O", "") or campos_qr.get("M", "")))
            )

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
            erro += "NIF emissor não encontrado. "

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
            "Empresa": empresa,
            "Nº da NC": numero_nc,
            "Data da NC": data_nc,
            "Valor": valor,
            "Valor utilizado": "",
            "Data de registo no SGICM": "",
            "Estado": estado,
            "Erro": erro.strip(),
            "Origem": origem,
            "NIF Emissor QR": nif_emissor,
            "QR bruto": qr_raw,
        }

    finally:
        doc.close()


# ============================================================
# 4. Excel existente + acrescentar só novos PDFs
# ============================================================

def ler_excel_existente(uploaded_excel) -> pd.DataFrame:
    if uploaded_excel is None:
        return pd.DataFrame(columns=COLUNAS_EXCEL)

    uploaded_excel.seek(0)
    df = pd.read_excel(uploaded_excel, dtype=str)
    df = df.fillna("")

    # Normaliza nomes de colunas, mas mantém conteúdo intacto.
    df.columns = [str(c).strip() for c in df.columns]

    df = garantir_colunas(df, COLUNAS_EXCEL)
    return df


def separar_novos(df_existente: pd.DataFrame, df_extraido: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df_existente = garantir_colunas(df_existente, COLUNAS_EXCEL).copy()
    df_extraido = garantir_colunas(df_extraido, COLUNAS_EXCEL).copy()

    chaves_existentes = set()
    for _, row in df_existente.iterrows():
        chave = criar_chave_linha(row)
        if chave != "|":
            chaves_existentes.add(chave)

    novas = []
    duplicadas = []

    chaves_novas_na_sessao = set()

    for _, row in df_extraido.iterrows():
        chave = criar_chave_linha(row)

        if chave == "|":
            novas.append(row.to_dict())
            continue

        if chave in chaves_existentes or chave in chaves_novas_na_sessao:
            duplicadas.append(row.to_dict())
        else:
            novas.append(row.to_dict())
            chaves_novas_na_sessao.add(chave)

    return pd.DataFrame(novas, columns=COLUNAS_EXCEL), pd.DataFrame(duplicadas, columns=COLUNAS_EXCEL)


def atualizar_excel(df_existente: pd.DataFrame, df_novas: pd.DataFrame) -> pd.DataFrame:
    df_existente = garantir_colunas(df_existente, COLUNAS_EXCEL).copy()
    df_novas = garantir_colunas(df_novas, COLUNAS_EXCEL).copy()

    if df_novas.empty:
        return df_existente

    return pd.concat([df_existente, df_novas], ignore_index=True)


def escrever_excel(df_final: pd.DataFrame, df_controlo: pd.DataFrame, df_novas: pd.DataFrame, df_duplicadas: pd.DataFrame) -> io.BytesIO:
    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_final.to_excel(writer, index=False, sheet_name="NC_APIFARMA_PAYBACK")
        df_novas.to_excel(writer, index=False, sheet_name="Novas_adicionadas")
        df_duplicadas.to_excel(writer, index=False, sheet_name="Ja_existiam")
        df_controlo.to_excel(writer, index=False, sheet_name="Controlo_extracao")

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

                    if cell.row == 1:
                        continue

                    header = ws.cell(row=1, column=cell.column).value

                    if header in ["Nome do ficheiro", "Empresa", "Nº da NC", "Data da NC", "Data de registo no SGICM"]:
                        cell.number_format = "@"

                    elif header in ["Valor", "Valor utilizado"]:
                        cell.number_format = "#,##0.00"
                        if isinstance(cell.value, str) and cell.value.strip():
                            try:
                                cell.value = normalizar_monetario_para_float(cell.value)
                            except Exception:
                                pass

                ws.column_dimensions[col_letter].width = min(max(max_len + 2, 12), 60)

            for cell in ws[1]:
                cell.font = cell.font.copy(bold=True)
                cell.alignment = cell.alignment.copy(horizontal="center")

    buffer.seek(0)
    return buffer


# ============================================================
# 5. Interface Streamlit
# ============================================================

st.set_page_config(page_title="NC APIFARMA / PAYBACK PDF → Excel", layout="wide")

st.title("📄 NC APIFARMA / PAYBACK — atualização por PDFs")
st.markdown(
    """
Carrega os **PDFs das notas de crédito** e, opcionalmente, o **Excel já existente**.

O sistema:
- lê os dados dos PDFs;
- usa o **NIF do emissor** na coluna **Empresa**;
- compara por **Empresa + Nº da NC**;
- **não altera linhas já existentes**;
- acrescenta apenas as NC que ainda não existem.
"""
)

col_excel, col_pdfs, col_opts = st.columns([1.2, 2.2, 0.8])

with col_excel:
    excel_existente = st.file_uploader(
        "Excel existente, se já houver",
        type=["xlsx"],
        accept_multiple_files=False,
    )

with col_pdfs:
    uploaded_files = st.file_uploader(
        "PDFs das NC",
        type=["pdf"],
        accept_multiple_files=True,
    )

with col_opts:
    pages_to_try = st.number_input(
        "Páginas QR",
        min_value=1,
        max_value=10,
        value=1,
    )

if uploaded_files:
    st.info(f"{len(uploaded_files)} PDF(s) carregado(s).")

    if st.button("🚀 Atualizar / Criar Excel", type="primary"):
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
        df_controlo = garantir_colunas(df_controlo, COLUNAS_CONTROLO)

        df_extraido = df_controlo[COLUNAS_EXCEL].copy()
        df_existente = ler_excel_existente(excel_existente)

        df_novas, df_duplicadas = separar_novos(df_existente, df_extraido)
        df_final = atualizar_excel(df_existente, df_novas)

        st.subheader("Resultado")
        st.success(f"{len(df_novas)} nova(s) NC adicionada(s).")
        st.info(f"{len(df_duplicadas)} NC já existia(m) e não foram mexidas.")

        problemas = df_controlo[df_controlo["Estado"] != "OK"].copy()
        if not problemas.empty:
            st.warning(f"{len(problemas)} linha(s) para verificar na extração.")
            st.dataframe(problemas, use_container_width=True)

        with st.expander("Pré-visualização — Excel final"):
            st.dataframe(df_final, use_container_width=True)

        with st.expander("Novas linhas adicionadas"):
            st.dataframe(df_novas, use_container_width=True)

        with st.expander("PDFs ignorados porque já existiam"):
            st.dataframe(df_duplicadas, use_container_width=True)

        with st.expander("Controlo da extração"):
            st.dataframe(df_controlo, use_container_width=True)

        buffer = escrever_excel(df_final, df_controlo, df_novas, df_duplicadas)

        nome_saida = f"NC_APIFARMA_PAYBACK_ATUALIZADO_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"

        st.download_button(
            "📥 Descarregar Excel atualizado",
            data=buffer.getvalue(),
            file_name=nome_saida,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
else:
    st.info("Carrega os PDFs para começar.")
