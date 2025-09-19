# comparador_descontos_app.py
# -----------------------------------------------------------
# Comparador de Descontos (TXT vs PDF)
# -----------------------------------------------------------

import io
import re
from typing import List, Optional, Tuple

import pandas as pd
import streamlit as st

# Backends PDF
try:
    import pdfplumber
except Exception:
    pdfplumber = None

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
- Apenas **páginas 1 e 2** são processadas.
- Cada linha relevante tem formato:
  - `101 Nome_do_desconto Valor`
- Regras:
  - `CodigoDesconto` = **primeiros 3 dígitos**.
  - `NomeDesconto` = **resto do texto**.
  - `Valor_pdf` = número da última coluna.

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
# PDF parsing — pdfplumber
# ---------------------------
def parse_pdf_plumber_words(pdf_files: List[bytes], y_tol: float, log: List[str]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if pdfplumber is None:
        return pd.DataFrame(columns=["CodigoDesconto","NomeDesconto","Valor_pdf"]), pd.DataFrame()

    preview = []
    recs = []

    for i, fb in enumerate(pdf_files, start=1):
        with pdfplumber.open(io.BytesIO(fb)) as pdf:
            for pi, page in enumerate(pdf.pages, start=1):
                if pi > 2:  # só páginas 1 e 2
                    continue

                words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
                if not words:
                    continue

                # Agrupar por linha
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

                    # Valor = número PT mais à direita
                    nums = [w for w in ws if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})*,\d{2}", w["text"].strip())]
                    if not nums:
                        continue
                    val_w = max(nums, key=lambda k: k["x0"])
                    val = _to_float_pt(val_w["text"])

                    # Texto da linha à esquerda do valor
                    bloco = [w for w in ws if w["x0"] < val_w["x0"] - 3]
                    linha_texto = " ".join([w["text"] for w in bloco]).strip()

                    # Extrair código (3 dígitos) + nome
                    m = re.match(r"^(\d{3})\s+(.*)$", linha_texto)
                    if not m:
                        log.append(f"[Linha PDF {i}-{pi}] Ignorada — '{linha_texto}'")
                        continue

                    codigo = str(int(m.group(1)))
                    nome = m.group(2).strip()

                    recs.append({"CodigoDesconto": codigo, "NomeDesconto": nome, "Valor_pdf": val})
                    preview.append({
                        "PDF": i, "Pagina": pi, "y": y,
                        "codigo": codigo, "nome": nome, "valor": val,
                        "linha_texto": linha_texto
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
# Parâmetros PDF
# ---------------------------
st.header("2) PDF — Parâmetros")
y_tol = st.number_input("Tolerância Y (agrupamento de linhas)", min_value=0.5, value=2.0, step=0.5)

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
    log_msgs: List[str] = []
    pdf_agg, df_preview = parse_pdf_plumber_words(pdf_bytes, y_tol=y_tol, log=log_msgs)

    if pdf_agg.empty:
        st.error("Não foi possível extrair dados úteis dos PDFs.")
        if not df_preview.empty:
            st.subheader("Pré-visualização (linhas extraídas)")
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
        with st.expander("📋 Pré-visualização (linhas extraídas)"):
            st.dataframe(df_preview, use_container_width=True)

    if log_msgs:
        with st.expander("🧾 Logs"):
            st.code("\n".join(log_msgs))
