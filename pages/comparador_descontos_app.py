# comparador_descontos_app.py
import io
import re
from typing import List, Optional, Dict, Tuple

import pandas as pd
import streamlit as st

try:
    import pdfplumber
except Exception:
    pdfplumber = None

st.set_page_config(page_title="Comparador de Descontos (TXT vs PDF)", layout="wide")

st.title("Comparador de Descontos – TXT vs PDF")
st.caption("Lê o TXT (largura fixa), extrai totais por código de desconto, extrai do(s) PDF(s) a coluna Desconto na secção Descontos e compara.")
st.markdown("---")

with st.expander("➕ Instruções"):
    st.markdown("""
**TXT**
- Considera apenas `COD = "101"`.
- Ignora Entidade que **comece por `9963`**.
- Usa Entidade que **comece por `999000`** e retira **os últimos 4 dígitos** como código de desconto.
- **Valor**: o número **antes do `+`** (no TXT vem com **ponto** como separador decimal).
- Somar apenas linhas com `Sinal = "+"`.

**PDF**
- Na secção **Descontos** (3 subcolunas), despreza-se a 1.ª, a **2.ª ou 1.ª** (configurável) contém o **código**, e a 3.ª contém o **nome**. 
- A coluna **Desconto** (singular) tem o **valor**.
- Somar por código e manter um nome representativo.

**Comparação**
- Junta por **Código de Desconto** e calcula **Diferença = Total_txt − Valor_pdf**.
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
    """
    Converte formato PT (1.234,56) para float.
    """
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
    """
    No TXT o valor vem com PONTO como separador decimal (e vírgula pode ser milhar).
    Ex.: 2130163.44  ->  2130163.44
    """
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
        s = ln + " " * max(0, 192 - len(ln))  # padding
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
    # Código de desconto = últimos 4 dígitos, convertido para número (remove zeros à esquerda)
    use["CodigoDesconto"] = use["Entidade"].str[-4:].str.replace(r"\D", "", regex=True)
    use["CodigoDesconto"] = use["CodigoDesconto"].apply(lambda x: str(int(x)) if x else None)
    use = use.dropna(subset=["CodigoDesconto"])

    # Valor antes do '+': no TXT vem com PONTO como separador decimal
    use["ValorNum"] = use["Valor"].apply(_to_float_txt)
    use = use.dropna(subset=["ValorNum"])

    agg = (
        use.groupby("CodigoDesconto", as_index=False)["ValorNum"]
           .sum()
           .rename(columns={"ValorNum": "Total_txt"})
    )
    return agg

# ---------------------------
# PDF parsing
# ---------------------------
def parse_pdf_via_tables(pdf_bytes_list: List[bytes], settings: Dict, log: List[str]) -> pd.DataFrame:
    """
    Tenta extrair a grelha como tabela. Funciona quando o PDF tem linhas/colunas bem definidas.
    """
    if pdfplumber is None:
        return pd.DataFrame(columns=["CodigoDesconto", "NomeDesconto", "Valor_pdf"])

    recs = []
    for idx, fb in enumerate(pdf_bytes_list, start=1):
        try:
            with pdfplumber.open(io.BytesIO(fb)) as pdf:
                for pi, page in enumerate(pdf.pages, start=1):
                    try:
                        tables = page.extract_tables(table_settings=settings)
                    except Exception as e:
                        log.append(f"[Tables] PDF#{idx} pág.{pi}: {e}")
                        continue

                    for tbl in tables:
                        df_tbl = pd.DataFrame(tbl)
                        if df_tbl.empty:
                            continue
                        header = df_tbl.iloc[0].astype(str).str.lower()
                        if not (header.str.contains("descont").any() and header.str.contains("desconto").any()):
                            continue

                        # Heurística: tentar localizar col Código (4 dígitos), Nome (texto), Valor (número PT)
                        for c_idx in range(df_tbl.shape[1]):
                            col = df_tbl.iloc[1:, c_idx].astype(str)
                            hits_cod = col.str.fullmatch(r"\d{3,4}").sum()
                            if hits_cod >= max(3, int(0.2 * len(col))):
                                codigo_col = c_idx
                                # nome provável: próxima coluna
                                nome_col = c_idx + 1 if c_idx + 1 < df_tbl.shape[1] else None
                                # valor provável: coluna com padrão 1.234,56
                                valor_col = None
                                for k in range(df_tbl.shape[1]):
                                    if k in (codigo_col, nome_col):
                                        continue
                                    patt = df_tbl.iloc[1:, k].astype(str).str.fullmatch(r"-?\d{1,3}(?:\.\d{3})*,\d{2}")
                                    if patt.sum() >= max(3, int(0.2 * len(df_tbl) - 1)):
                                        valor_col = k
                                        break
                                if nome_col is None or valor_col is None:
                                    continue

                                for _, row in df_tbl.iloc[1:].iterrows():
                                    codigo = str(row[codigo_col]).strip()
                                    nome = str(row[nome_col]).strip()
                                    valor = _to_float_pt(str(row[valor_col]))
                                    codigo = re.sub(r"\D", "", codigo)
                                    if re.fullmatch(r"\d{3,4}", codigo) and valor is not None:
                                        # normalizar código numérico (sem zeros à esquerda)
                                        codigo = str(int(codigo))
                                        recs.append({"CodigoDesconto": codigo, "NomeDesconto": nome, "Valor_pdf": valor})
                                break
        except Exception as e:
            log.append(f"[Tables] PDF#{idx}: {e}")

    if not recs:
        return pd.DataFrame(columns=["CodigoDesconto", "NomeDesconto", "Valor_pdf"])
    df = pd.DataFrame(recs)
    agg = (
        df.groupby("CodigoDesconto", as_index=False)
          .agg(Valor_pdf=("Valor_pdf", "sum"),
               NomeDesconto=("NomeDesconto", lambda s: s.value_counts().index[0] if len(s) else ""))
    )
    return agg

def parse_pdf_via_words(pdf_bytes_list: List[bytes],
                        auto: bool,
                        x_cut1: Optional[float],
                        x_cut2: Optional[float],
                        y_tol: float,
                        codigo_regex: str,
                        code_pos_is_second: bool,
                        numeric_code: bool,
                        log: List[str]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Extrai por palavras (coordenadas x,y). 
    code_pos_is_second=True => código na 2.ª subcoluna de 'Descontos'; False => 1.ª subcoluna.
    numeric_code=True => código final sem zeros à esquerda (p/ casar com TXT).
    """
    if pdfplumber is None:
        return pd.DataFrame(columns=["CodigoDesconto", "NomeDesconto", "Valor_pdf"]), pd.DataFrame()

    preview_rows = []
    recs = []

    for idx, fb in enumerate(pdf_bytes_list, start=1):
        try:
            with pdfplumber.open(io.BytesIO(fb)) as pdf:
                for pi, page in enumerate(pdf.pages, start=1):
                    words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
                    if not words:
                        continue

                    # Coluna de valor (Desconto)
                    x_valor = None
                    for w in words:
                        if w["text"].strip().lower() == "desconto":
                            x_valor = w["x0"]
                            break
                    if x_valor is None:
                        nums = [w for w in words if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})*,\d{2}", w["text"].strip())]
                        if nums:
                            x_valor = max(nums, key=lambda k: k["x0"])["x0"]
                        else:
                            log.append(f"[Words] PDF#{idx} pág.{pi}: sem 'Desconto' nem números detectáveis.")
                            continue

                    # Agrupar linhas por Y
                    linhas = {}
                    for w in words:
                        cy = (w["top"] + w["bottom"]) / 2
                        key_y = round(cy / y_tol) * y_tol
                        linhas.setdefault(key_y, []).append(w)

                    for y, ws in sorted(linhas.items()):
                        ws_sorted = sorted(ws, key=lambda x: x["x0"])

                        # valor (mais à direita, depois de x_valor)
                        nums = [w for w in ws_sorted if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})*,\d{2}", w["text"].strip())]
                        valor = None
                        if nums:
                            cand = max(nums, key=lambda k: k["x0"])
                            if cand["x0"] >= x_valor - 3:
                                valor = _to_float_pt(cand["text"].strip())

                        # bloco Descontos (à esquerda da coluna de valor)
                        bloco = [w for w in ws_sorted if w["x0"] < x_valor - 3]
                        if not bloco or valor is None:
                            preview_rows.append({"PDF": idx, "Pagina": pi, "y": y, "valor": valor, "linha_texto": " ".join([w["text"] for w in ws_sorted])})
                            continue

                        # detetar 3 subcolunas: automático (gaps) ou manual (x_cut1/x_cut2)
                        if auto:
                            xs = sorted(set([w["x0"] for w in bloco]))
                            if len(xs) < 3:
                                preview_rows.append({"PDF": idx, "Pagina": pi, "y": y, "valor": valor, "linha_texto": " ".join([w["text"] for w in bloco])})
                                continue
                            gaps = [(xs[i+1]-xs[i], xs[i], xs[i+1]) for i in range(len(xs)-1)]
                            gaps_sorted = sorted(gaps, key=lambda g: g[0], reverse=True)
                            if len(gaps_sorted) < 2:
                                preview_rows.append({"PDF": idx, "Pagina": pi, "y": y, "valor": valor, "linha_texto": " ".join([w["text"] for w in bloco])})
                                continue
                            cut1 = gaps_sorted[0][2]
                            cut2 = gaps_sorted[1][2]
                            c1, c2 = sorted([cut1, cut2])
                        else:
                            if x_cut1 is None or x_cut2 is None:
                                log.append(f"[Words] pág.{pi}: cortes manuais não definidos.")
                                continue
                            c1, c2 = sorted([x_cut1, x_cut2])

                        col1 = [w for w in bloco if w["x0"] < c1]
                        col2 = [w for w in bloco if c1 <= w["x0"] < c2]
                        col3 = [w for w in bloco if w["x0"] >= c2]

                        col_codigo = col2 if code_pos_is_second else col1
                        col_nome = col3 if code_pos_is_second else (col2 if col2 else col3)

                        codigo_raw = "".join([w["text"] for w in col_codigo]).strip()
                        m = re.search(codigo_regex, codigo_raw)
                        codigo = m.group(0) if m else re.sub(r"[^\d]", "", codigo_raw)
                        if not codigo:
                            preview_rows.append({"PDF": idx, "Pagina": pi, "y": y, "valor": valor, "linha_texto": " ".join([w["text"] for w in bloco])})
                            continue

                        if numeric_code:
                            codigo = str(int(codigo))  # remove zeros à esquerda
                        else:
                            codigo = codigo.zfill(4)    # 4 dígitos

                        nome = " ".join([w["text"] for w in col_nome]).strip()

                        recs.append({
                            "Ficheiro": f"PDF#{idx}",
                            "Pagina": pi,
                            "CodigoDesconto": codigo,
                            "NomeDesconto": nome,
                            "Valor_pdf": valor
                        })
                        preview_rows.append({"PDF": idx, "Pagina": pi, "y": y, "valor": valor, "codigo": codigo, "nome": nome,
                                             "linha_texto": " ".join([w["text"] for w in bloco])})
        except Exception as e:
            log.append(f"[Words] PDF#{idx}: {e}")

    df_preview = pd.DataFrame(preview_rows)
    if not recs:
        return pd.DataFrame(columns=["CodigoDesconto", "NomeDesconto", "Valor_pdf"]), df_preview

    df = pd.DataFrame(recs)
    agg = (
        df.groupby("CodigoDesconto", as_index=False)
          .agg(Valor_pdf=("Valor_pdf", "sum"),
               NomeDesconto=("NomeDesconto", lambda s: s.value_counts().index[0] if len(s) else ""))
    )
    return agg, df_preview

# ---------------------------
# UI
# ---------------------------
st.header("1) Carregar ficheiros")
st.caption("O seletor do TXT aceita ficheiros sem extensão.")
c1, c2 = st.columns(2)
with c1:
    txt_file = st.file_uploader("Carregar TXT (largura fixa)", type=None, accept_multiple_files=False, key="txt")
with c2:
    pdf_files = st.file_uploader("Carregar PDF(s) das listagens", type=["pdf"], accept_multiple_files=True, key="pdfs")

st.header("2) Ajustes de parsing do PDF (opcional)")
tab1, tab2 = st.tabs(["Deteção por Tabelas", "Deteção por Palavras"])

with tab1:
    st.write("**pdfplumber.extract_tables** — usar quando o PDF tem grelha/linhas.")
    cA, cB, cC = st.columns(3)
    with cA:
        snap_x_tolerance = st.number_input("snap_tolerance", min_value=0.0, value=3.0, step=0.5)
    with cB:
        join_tolerance = st.number_input("join_tolerance", min_value=0.0, value=3.0, step=0.5)
    with cC:
        edge_min_length = st.number_input("edge_min_length", min_value=1.0, value=3.0, step=0.5)
    text_tolerance = st.number_input("text_tolerance", min_value=0.0, value=3.0, step=0.5)
    table_settings = dict(
        vertical_strategy="lines",
        horizontal_strategy="lines",
        snap_tolerance=snap_x_tolerance,
        join_tolerance=join_tolerance,
        edge_min_length=edge_min_length,
        text_tolerance=text_tolerance
    )

with tab2:
    st.write("**Palavras (x,y)** — automático por “gaps” ou manual com cortes x.")
    auto = st.radio("Colunas 'Descontos'", options=["Automático (por gaps)", "Manual (cortes x)"], index=0)
    auto_mode = auto.startswith("Automático")
    y_tol = st.number_input("Tolerância Y (agrupamento)", min_value=0.5, value=2.0, step=0.5)
    cD, cE = st.columns(2)
    with cD:
        x_cut1 = st.number_input("x-cut1 (se manual)", min_value=0.0, value=100.0, step=5.0)
    with cE:
        x_cut2 = st.number_input("x-cut2 (se manual)", min_value=0.0, value=200.0, step=5.0)
    code_pos = st.radio("Qual subcoluna de **Descontos** tem o CÓDIGO?", options=["2ª (padrão)", "1ª"], index=0)
    code_format = st.radio("Formato do código a comparar", options=["Número (sem zeros à esquerda)", "4 dígitos (zero à esquerda)"], index=0)
    codigo_regex = st.text_input("Regex para extrair o código", value=r"\d{3,4}")

# ---------------------------
# Processar
# ---------------------------
log_msgs: List[str] = []

if st.button("Processar e Comparar", type="primary"):
    if not txt_file or not pdf_files:
        st.error("Carregue o TXT e pelo menos um PDF.")
        st.stop()

    try:
        df_txt = parse_txt_fixed_width(txt_file.getvalue())
        txt_agg = aggregate_txt(df_txt)  # CodigoDesconto (numérico) | Total_txt
    except Exception as e:
        st.exception(e)
        st.stop()

    pdf_bytes = [f.getvalue() for f in pdf_files]

    # 1) Tabelas
    pdf_agg_tables = parse_pdf_via_tables(pdf_bytes, table_settings, log_msgs)

    # 2) Palavras
    numeric_code = code_format.startswith("Número")
    pdf_agg_words, df_preview = parse_pdf_via_words(
        pdf_bytes,
        auto=auto_mode,
        x_cut1=(x_cut1 if not auto_mode else None),
        x_cut2=(x_cut2 if not auto_mode else None),
        y_tol=y_tol,
        codigo_regex=codigo_regex,
        code_pos_is_second=(code_pos.startswith("2ª")),
        numeric_code=numeric_code,
        log=log_msgs
    )

    pdf_agg = pdf_agg_tables if not pdf_agg_tables.empty else pdf_agg_words

    if pdf_agg.empty:
        st.error("Não foi possível extrair dados dos PDFs. Ajuste os parâmetros e tente de novo.")
        if not df_preview.empty:
            st.subheader("Pré-visualização (palavras por linha)")
            st.dataframe(df_preview.head(200), use_container_width=True)
        if log_msgs:
            st.subheader("Logs")
            st.code("\n".join(log_msgs))
        st.stop()

    # Se TXT está em numérico, garantir que PDF também (ou vice-versa)
    # Aqui seguimos o TXT: códigos numéricos (sem zeros à esquerda)
    pdf_agg["CodigoDesconto"] = pdf_agg["CodigoDesconto"].astype(str)
    if numeric_code:
        pdf_agg["CodigoDesconto"] = pdf_agg["CodigoDesconto"].apply(lambda x: str(int(re.sub(r"\D", "", x))) if re.search(r"\d", x) else x)
    else:
        pdf_agg["CodigoDesconto"] = pdf_agg["CodigoDesconto"].str.zfill(4)

    comp = pd.merge(txt_agg, pdf_agg, on="CodigoDesconto", how="outer")
    comp["Total_txt"] = comp["Total_txt"].fillna(0.0)
    comp["Valor_pdf"] = comp["Valor_pdf"].fillna(0.0)
    if "NomeDesconto" not in comp.columns:
        comp["NomeDesconto"] = ""
    comp["NomeDesconto"] = comp["NomeDesconto"].fillna("")
    comp["Diferenca"] = comp["Total_txt"] - comp["Valor_pdf"]

    st.success("Processamento concluído.")
    st.subheader("Resumo por Código de Desconto")
    st.dataframe(comp.sort_values("CodigoDesconto").reset_index(drop=True), use_container_width=True)

    st.subheader("Top divergências (|Diferença|)")
    topn = comp.reindex(comp["Diferenca"].abs().sort_values(ascending=False).index).head(30)
    st.dataframe(topn.reset_index(drop=True), use_container_width=True)

    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
        txt_agg.sort_values("CodigoDesconto").to_excel(writer, sheet_name="TXT_aggregado", index=False)
        pdf_agg.sort_values("CodigoDesconto").to_excel(writer, sheet_name="PDF_aggregado", index=False)
        comp.sort_values("CodigoDesconto").to_excel(writer, sheet_name="Comparacao", index=False)
    out.seek(0)
    st.download_button("📥 Descarregar relatório (Excel)", data=out,
                       file_name="comparacao_descontos.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    if 'df_preview' in locals() and not df_preview.empty:
        with st.expander("📋 Pré-visualização (palavras por linha)"):
            st.dataframe(df_preview, use_container_width=True)

    if log_msgs:
        with st.expander("🧾 Logs"):
            st.code("\n".join(log_msgs))
