# comparador_descontos_app.py
# -----------------------------------------------------------
# Comparador de Descontos (TXT vs PDF)
# -----------------------------------------------------------

import io
import re
from typing import List, Optional, Tuple

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
    if s is None:
        return None
    s = s.strip().replace(" ", "")
    if not s:
        return None
    s = s.replace(",", "")
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
        s = ln + " " * max(0, 192 - len(ln))
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

    use["CodigoDesconto"] = (
        use["Entidade"].str[-4:].str.replace(r"\D", "", regex=True).apply(lambda x: str(int(x)) if x else None)
    )
    use = use.dropna(subset=["CodigoDesconto"])

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
    # (Mantém versão original sem alterações)

# ---------------------------
# PDF parsing — pdfplumber (melhorado)
# ---------------------------
def parse_pdf_plumber_words(pdf_files: List[bytes],
                            mode: str,
                            x_cut1: Optional[float], x_cut2: Optional[float],
                            ranges: Optional[Tuple[float,float,float,float,float]],
                            y_tol: float, code_pos_is_second: bool,
                            codigo_digits: int, log: List[str]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if pdfplumber is None:
        return pd.DataFrame(columns=["CodigoDesconto","NomeDesconto","Valor_pdf"]), pd.DataFrame()

    preview = []
    recs = []
    patt_exact = re.compile(r"\d{2,5}")

    for i, fb in enumerate(pdf_files, start=1):
        with pdfplumber.open(io.BytesIO(fb)) as pdf:
            for pi, page in enumerate(pdf.pages, start=1):
                words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
                if not words:
                    continue

                nums_all = [w for w in words if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})*,\d{2}", w["text"].strip())]
                if not nums_all:
                    continue
                x_val_guess = max(nums_all, key=lambda k: k["x0"])["x0"]

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
                        else:
                            if x_cut1 is None or x_cut2 is None:
                                continue
                            c1, c2 = sorted([x_cut1, x_cut2])

                        col1 = [w for w in bloco if w["x0"] < c1]
                        col2 = [w for w in bloco if c1 <= w["x0"] < c2]
                        col3 = [w for w in bloco if w["x0"] >= c2]
                        col_codigo = col2 if code_pos_is_second else col1
                        col_nome   = col3 if code_pos_is_second else (col2 if col2 else col3)

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
    st.error("Nenhum backend PDF disponível.")
    st.stop()

if camelot is None:
    st.info("⚠️ Camelot não disponível neste ambiente (requer Ghostscript). A usar pdfplumber.")

backend = st.radio("Backend PDF", options=available_backends, index=0)
log_msgs: List[str] = []

if backend.startswith("Camelot"):
    cA, cB, cC = st.columns(3)
    with cA:
        flavor = st.selectbox("flavor", options=["lattice", "stream"], index=0)
    with cB:
        pages = st.text_input("pages", value="all")
    with cC:
        strip_text = st.text_input("strip_text", value=" \n")
    cD, cE, cF = st.columns(3)
    with cD:
        code_col_hint = st.number_input("col CÓDIGO (hint)", min_value=-1, value=-1, step=1)
    with cE:
        name_col_hint = st.number_input("col NOME (hint)", min_value=-1, value=-1, step=1)
    with cF:
        value_col_hint = st.number_input("col VALOR (hint)", min_value=-1, value=-1, step=1)
else:
    st.write("**pdfplumber (Palavras x,y)** — escolha um dos modos abaixo:")
    mode = st.radio("Modo", options=["Automático (gaps)", "Manual (cortes x)", "Manual (faixas X)"], index=0)
    mode_key = "auto" if mode.startswith("Auto") else ("cuts" if "cortes" in mode else "ranges")
    cA, cB, cC = st.columns(3)
    with cA:
        y_tol = st.number_input("Tolerância Y", min_value=0.5, value=2.0, step=0.5)
    with cB:
        code_pos = st.radio("Subcoluna com CÓDIGO", options=["1ª", "2ª"], index=0)
    with cC:
        codigo_digits = st.selectbox("Dígitos do código", options=[3, 4], index=0)

    cD, cE = st.columns(2)
    with cD:
        x_cut1 = st.number_input("x-cut1", min_value=0.0, value=100.0, step=5.0)
    with cE:
        x_cut2 = st.number_input("x-cut2", min_value=0.0, value=200.0, step=5.0)

    cF, cG, cH = st.columns(3)
    with cF:
        x_code_min = st.number_input("X mín. CÓDIGO", min_value=0.0, value=40.0, step=5.0)
    with cG:
        x_code_max = st.number_input("X máx. CÓDIGO", min_value=0.0, value=110.0, step=5.0)
    with cH:
        x_name_min = st.number_input("X mín. NOME", min_value=0.0, value=115.0, step=5.0)
    cI, cJ = st.columns(2)
    with cI:
        x_name_max = st.number_input("X máx. NOME", min_value=0.0, value=360.0, step=5.0)
    with cJ:
        x_val_min = st.number_input("X mín. VALOR", min_value=0.0, value=380.0, step=5.0)

# ---------------------------
# Processar
# ---------------------------
st.header("3) Executar comparação")

if st.button("Processar e Comparar", type="primary"):
    if not txt_file or not pdf_files:
        st.error("Carregue o TXT e pelo menos um PDF.")
        st.stop()

    try:
        df_txt = parse_txt_fixed_width(txt_file.getvalue())
        txt_agg = aggregate_txt(df_txt)
    except Exception as e:
        st.exception(e)
        st.stop()

    pdf_bytes = [f.getvalue() for f in pdf_files]

    if backend.startswith("Camelot"):
        pdf_agg = parse_pdf_camelot(
            pdf_bytes,
            flavor=flavor,
            pages=pages,
            strip_text=strip_text,
            code_col_hint=(None if code_col_hint < 0 else int(code_col_hint)),
            name_col_hint=(None if name_col_hint < 0 else int(name_col_hint)),
            value_col_hint=(None if value_col_hint < 0 else int(value_col_hint)),
            log=log_msgs
        )
        df_preview = pd.DataFrame()
    else:
        ranges = (x_code_min, x_code_max, x_name_min, x_name_max, x_val_min)
        pdf_agg, df_preview = parse_pdf_plumber_words(
            pdf_bytes,
            mode=mode_key,
            x_cut1=(x_cut1 if mode_key == "cuts" else None),
            x_cut2=(x_cut2 if mode_key == "cuts" else None),
            ranges=(ranges if mode_key == "ranges" else None),
            y_tol=y_tol,
            code_pos_is_second=(code_pos.startswith("2ª")),
            codigo_digits=codigo_digits,
            log=log_msgs
        )

    if pdf_agg.empty:
        st.error("Não foi possível extrair dados úteis dos PDFs.")
        if not df_preview.empty:
            st.subheader("Pré-visualização (palavras por linha)")
            st.dataframe(df_preview.head(200), use_container_width=True)
        if log_msgs:
            st.subheader("Logs")
            st.code("\n".join(log_msgs))
        st.stop()

    pdf_agg["CodigoDesconto"] = pdf_agg["CodigoDesconto"].astype(str)
    comp = pd.merge(txt_agg, pdf_agg, on="CodigoDesconto", how="outer")
    comp["Total_txt"] = comp["Total_txt"].fillna(0.0)
    comp["Valor_pdf"] = comp["Valor_pdf"].fillna(0.0)
    comp["NomeDesconto"] = comp.get("NomeDesconto", "").fillna("")
    comp["Diferenca"] = comp["Total_txt"] - comp["Valor_pdf"]

    st.success("Processamento concluído.")
    st.subheader("Resumo por Código de Desconto")
    st.dataframe(comp.sort_values("CodigoDesconto").reset_index(drop=True), use_container_width=True)

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
        txt_agg.sort_values("CodigoDesconto").to_excel(writer, sheet_name="TXT_aggregado", index=False)
        pdf_agg.sort_values("CodigoDesconto").to_excel(writer, sheet_name="PDF_aggregado", index=False)
        comp.sort_values("CodigoDesconto").to_excel(writer, sheet_name="Comparacao", index=False)
    out.seek(0)
    st.download_button("📥 Descarregar relatório (Excel)", data=out,
                       file_name="comparacao_descontos.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    if not df_preview.empty:
        with st.expander("📋 Pré-visualização (palavras por linha)"):
            st.dataframe(df_preview, use_container_width=True)

    if log_msgs:
        with st.expander("🧾 Logs"):
            st.code("\n".join(log_msgs))
