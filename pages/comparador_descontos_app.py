# comparador_descontos_app.py
# -----------------------------------------------------------
# Comparador de Descontos (TXT vs PDF)
# - TXT (largura fixa): COD=101, Entidade 999000xxxx (ignora 9963*),
#   soma apenas Valor das linhas com Sinal="+", usando ponto como separador decimal.
#   Código de desconto = últimos 4 dígitos da Entidade, convertido para número (sem zeros à esquerda).
# - PDF: Secção "Descontos" (3 subcolunas). 1.ª ou 2.ª subcoluna = Código (configurável),
#   3.ª = Nome. Coluna "Desconto" (singular) = Valor.
#   Extração por:
#     • Camelot (opcional, se instalado) – bom para tabelas com linhas.
#     • pdfplumber (palavras x,y) – com modos Automático / Manual (cortes) / Manual (faixas X).
# - Compara somatórios por Código (numérico) e exporta Excel.
# -----------------------------------------------------------

import io
import re
from typing import List, Optional, Dict, Tuple

import pandas as pd
import streamlit as st

# Backends PDF (opcionais)
try:
    import pdfplumber
except Exception:
    pdfplumber = None

try:
    import camelot  # requer Ghostscript para 'lattice'
except Exception:
    camelot = None

st.set_page_config(page_title="Comparador de Descontos (TXT vs PDF)", layout="wide")
st.title("Comparador de Descontos — TXT vs PDF")
st.caption("Extrai totais por **Código de Desconto** do TXT e das listagens em PDF e compara. Em PT-PT.")
st.markdown("---")

with st.expander("➕ Instruções (clique)"):
    st.markdown("""
**TXT (largura fixa)**
- Considera apenas `COD = "101"`.
- Entidade: **começa por `999000`** (ignorar `9963*`).
- **Código de desconto** = **últimos 4 dígitos** da Entidade → convertido para **número** (sem zeros à esquerda).
- **Valor** a somar = **antes do `+`** (no TXT vem com **ponto** como separador decimal).
- Somar **apenas** linhas com `Sinal = "+"`.

**PDF**
- Secção **Descontos** tem 3 subcolunas:
  - 1.ª (por vezes vazia) ou **2.ª** = **Código** (configurável),
  - **3.ª** = **Nome**,
  - Coluna **Desconto** (singular) = **Valor**.
- Modos de extração:
  - **Camelot** (se instalado): bom para tabelas com grelha/linhas.
  - **pdfplumber (Palavras x,y)**: **Automático (gaps)**, **Manual (cortes x)** ou **Manual (faixas X)**.

**Resultado**
- Junta por **Código (numérico)** e calcula **Diferença = Total_txt − Valor_pdf**.
""")

# ---------------------------
# Helpers
# ---------------------------
def _decode_bytes(b: bytes) -> str:
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("latin-1", errors="replace")

def _to_float_pt(s: str) -> Optional[float]:
    """Converte '1.234,56' → 1234.56."""
    if s is None:
        return None
    s = s.strip().replace(" ", "")
    if not s:
        return None
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None

def _to_float_txt(s: str) -> Optional[float]:
    """No TXT o valor vem com PONTO como separador decimal (vírgula pode ser milhar)."""
    if s is None:
        return None
    s = s.strip().replace(" ", "")
    if not s:
        return None
    s = s.replace(",", "")  # remover vírgulas (milhar)
    try:
        return float(s)
    except Exception:
        return None

# ---------------------------
# TXT parsing
# ---------------------------
def parse_txt_fixed_width(b: bytes) -> pd.DataFrame:
    txt = _decode_bytes(b)
    lines = [ln.rstrip("\r\n") for ln in txt.splitlines() if ln.strip()]
    rows = []
    for ln in lines:
        s = ln + " " * max(0, 192 - len(ln))  # padding até 192 chars
        cod       = s[0:3].strip()
        entidade  = s[11:21].strip()
        ne        = s[21:55].strip()
        data_str  = s[55:63].strip()
        deb       = s[63:113].strip()
        cred      = s[113:155].strip()
        valor_str = s[155:181].strip()
        sinal     = s[181:182].strip()
        cc        = s[182:192].strip()
        rows.append({
            "COD": cod, "Entidade": entidade, "NE": ne, "Data": data_str,
            "Deb": deb, "Cred": cred, "Valor": valor_str, "Sinal": sinal, "CC": cc
        })
    return pd.DataFrame(rows)

def aggregate_txt(df: pd.DataFrame) -> pd.DataFrame:
    m = (
        (df["COD"] == "101")
        & (~df["Entidade"].fillna("").str.startswith("9963"))
        & (df["Entidade"].fillna("").str.startswith("999000"))
        & (df["Sinal"] == "+")
    )
    use = df.loc[m].copy()

    # Código = últimos 4 dígitos → número (remove zeros à esquerda) → string para merge
    use["CodigoDesconto"] = (
        use["Entidade"].str[-4:].str.replace(r"\D", "", regex=True).apply(lambda x: str(int(x)) if x else None)
    )
    use = use.dropna(subset=["CodigoDesconto"])

    # Valor antes do '+': TXT tem '.' como decimal
    use["ValorNum"] = use["Valor"].apply(_to_float_txt)
    use = use.dropna(subset=["ValorNum"])

    agg = (
        use.groupby("CodigoDesconto", as_index=False)["ValorNum"]
           .sum()
           .rename(columns={"ValorNum": "Total_txt"})
    )
    return agg

# ---------------------------
# PDF parsing — Camelot
# ---------------------------
def parse_pdf_camelot(pdf_files: List[bytes], flavor: str, pages: str, strip_text: str,
                      code_col_hint: Optional[int], name_col_hint: Optional[int],
                      value_col_hint: Optional[int], log: List[str]) -> pd.DataFrame:
    if camelot is None:
        return pd.DataFrame(columns=["CodigoDesconto","NomeDesconto","Valor_pdf"])
    # ... (mantém versão original, sem alterações)
    # Para poupar espaço não reescrevo aqui todo o bloco — mas mantêm-se igual ao teu original.

# ---------------------------
# PDF parsing — pdfplumber (melhorado)
# ---------------------------
def parse_pdf_plumber_words(pdf_files: List[bytes],
                            mode: str,
                            x_cut1: Optional[float], x_cut2: Optional[float],
                            ranges: Optional[Tuple[float,float,float,float,float]],
                            y_tol: float, code_pos_is_second: bool,
                            codigo_digits: int, log: List[str]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    mode: "auto" | "cuts" | "ranges"
    ranges: (x_code_min, x_code_max, x_name_min, x_name_max, x_val_min)
    """
    if pdfplumber is None:
        return pd.DataFrame(columns=["CodigoDesconto","NomeDesconto","Valor_pdf"]), pd.DataFrame()

    preview = []
    recs = []
    patt_exact = re.compile(r"\d{2,5}")  # mais permissivo

    for i, fb in enumerate(pdf_files, start=1):
        with pdfplumber.open(io.BytesIO(fb)) as pdf:
            for pi, page in enumerate(pdf.pages, start=1):
                words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
                if not words:
                    continue

                # 1) localizar coluna de valores
                nums_all = [w for w in words if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})*,\d{2}", w["text"].strip())]
                if not nums_all:
                    continue
                x_val_guess = max(nums_all, key=lambda k: k["x0"])["x0"]

                # 2) agrupar linhas por Y
                lines = {}
                for w in words:
                    cy = (w["top"] + w["bottom"]) / 2
                    found = None
                    for k in lines.keys():
                        if abs(k - cy) <= y_tol:
                            found = k
                            break
                    if found is not None:
                        lines[found].append(w)
                    else:
                        lines[cy] = [w]

                for y, ws in sorted(lines.items()):
                    ws = sorted(ws, key=lambda w: w["x0"])

                    # valor mais à direita
                    nums = [w for w in ws if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})*,\d{2}", w["text"].strip())]
                    if mode == "ranges" and ranges:
                        cand_nums = [w for w in nums if w["x0"] >= ranges[4]-1]
                        if not cand_nums:
                            continue
                        val_w = max(cand_nums, key=lambda k: k["x0"])
                    else:
                        if not nums:
                            continue
                        val_w = max(nums, key=lambda k: k["x0"])
                        if val_w["x0"] < x_val_guess - 3:
                            continue

                    val = _to_float_pt(val_w["text"])
                    bloco = [w for w in ws if w["x0"] < (ranges[4]-3 if (mode == "ranges" and ranges) else (x_val_guess - 3))]
                    if not bloco:
                        continue

                    # separar código/nome
                    if mode == "ranges" and ranges:
                        x_code_min, x_code_max, x_name_min, x_name_max, _ = ranges
                        col_codigo = [w for w in bloco if x_code_min <= w["x0"] < x_code_max]
                        col_nome   = [w for w in bloco if x_name_min <= w["x0"] < x_name_max]
                    else:
                        xs = sorted(set([w["x0"] for w in bloco]))
                        if mode == "auto":
                            if len(xs) < 3:
                                continue
                            gaps = [(xs[i+1]-xs[i], xs[i], xs[i+1]) for i in range(len(xs)-1)]
                            gaps = sorted(gaps, key=lambda g: g[0], reverse=True)
                            if len(gaps) < 2:
                                continue
                            cut1, cut2 = gaps[0][2], gaps[1][2]
                            c1, c2 = sorted([cut1, cut2])
                        else:  # cuts
                            if x_cut1 is None or x_cut2 is None:
                                continue
                            c1, c2 = sorted([x_cut1, x_cut2])

                        col1 = [w for w in bloco if w["x0"] < c1]
                        col2 = [w for w in bloco if c1 <= w["x0"] < c2]
                        col3 = [w for w in bloco if w["x0"] >= c2]
                        col_codigo = col2 if code_pos_is_second else col1
                        col_nome   = col3 if code_pos_is_second else (col2 if col2 else col3)

                    # extrair código
                    codigo_raw = "".join([w["text"] for w in col_codigo]).strip()
                    m = patt_exact.search(codigo_raw)
                    if m:
                        codigo = m.group(0)
                    else:
                        codigo = re.sub(r"\D", "", codigo_raw)

                    if not codigo:
                        log.append(f"[Linha PDF {i}-{pi}] Falhou código — '{codigo_raw}'")
                        preview.append({"PDF": i, "Pagina": pi, "y": y, "linha_texto": " ".join([w['text'] for w in bloco])})
                        continue

                    try:
                        codigo = str(int(codigo))
                    except Exception:
                        continue

                    nome = " ".join([w["text"] for w in col_nome]).strip()

                    recs.append({"CodigoDesconto": codigo, "NomeDesconto": nome, "Valor_pdf": val})
                    preview.append({
                        "PDF": i, "Pagina": pi, "y": y,
                        "codigo_raw": codigo_raw, "codigo": codigo,
                        "nome": nome, "valor": val,
                        "linha_texto": " ".join([w["text"] for w in bloco]),
                        "coords": [(w["text"], round(w["x0"],1)) for w in bloco]
                    })

    df_prev = pd.DataFrame(preview)
    if not recs:
        return pd.DataFrame(columns=["CodigoDesconto","NomeDesconto","Valor_pdf"]), df_prev

    df = pd.DataFrame(recs)
    agg = (
        df.groupby("CodigoDesconto", as_index=False)
          .agg(Valor_pdf=("Valor_pdf", "sum"),
               NomeDesconto=("NomeDesconto", lambda s: s.value_counts().index[0] if len(s) else ""))
    )
    return agg, df_prev

# ---------------------------
# UI — Uploads
# ---------------------------
st.header("1) Carregar ficheiros")
st.caption("O seletor do TXT aceita ficheiros sem extensão.")
c1, c2 = st.columns(2)
with c1:
    txt_file = st.file_uploader("TXT (largura fixa)", type=None, accept_multiple_files=False)
with c2:
    pdf_files = st.file_uploader("PDF(s) das listagens", type=["pdf"], accept_multiple_files=True)

# ---------------------------
# UI — PDF Backend e parâmetros
# ---------------------------
st.header("2) PDF — Backend e parâmetros")

available_backends = []
if camelot is not None:
    available_backends.append("Camelot (recomendado se tiver Ghostscript)")
if pdfplumber is not None:
    available_backends.append("pdfplumber (Palavras x,y)")

if not available_backends:
    st.error("Nenhum backend PDF disponível. Instale pelo menos `pdfplumber`.")
    st.stop()

if camelot is None:
    st.info("⚠️ Camelot não disponível neste ambiente (requer Ghostscript). A usar pdfplumber.")

backend = st.radio("Backend PDF", options=available_backends, index=0)
log_msgs: List[str] = []

# ... (mantém a tua lógica original de UI e processamento)
# Diferença é que a função parse_pdf_plumber_words já está melhorada
