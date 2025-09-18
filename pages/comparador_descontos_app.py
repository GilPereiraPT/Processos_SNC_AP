
import io
import re
import math
import pandas as pd
import streamlit as st
from typing import List, Optional, Dict, Tuple

try:
    import pdfplumber
except Exception:
    pdfplumber = None

st.set_page_config(page_title="Comparador de Descontos (TXT vs PDF)", layout="wide")

st.title("Comparador de Descontos – TXT vs PDF")
st.caption("Extrai e compara totais por **Código de Desconto** do ficheiro TXT (importação) com a coluna **Desconto** na secção **Descontos** dos PDFs.")
st.markdown("---")

with st.expander("➕ Instruções (clique para expandir)"):
    st.markdown("""
    **Passo 1 — TXT**  
    - Ler linhas de largura fixa.  
    - Considerar apenas `COD = "101"`.  
    - Ignorar entidades que **comecem por `9963`**.  
    - Selecionar entidades que **comecem por `999000`**.  
    - `CodigoDesconto = últimos 4 dígitos` da Entidade.  
    - Somar o **Valor** **apenas** das linhas com `Sinal = "+"`.

    **Passo 2 — PDF**  
    - Em cada página, localizar a coluna **Descontos** (3 sub-colunas) e a coluna **Desconto** (valor).  
    - Desprezar a 1.ª subcoluna de **Descontos**.  
    - Usar a 2.ª subcoluna como **Código** e a 3.ª como **Nome do desconto**.  
    - Somar a coluna **Desconto** (valor) por **Código**.  
    - Manter um nome representativo por código (mais frequente).

    **Comparação**  
    - Junta por `CodigoDesconto` e calcula `Diferença = Total_txt - Total_pdf`.
    """)

# --------------------------------
# Helpers
# --------------------------------
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

# Valor no TXT: ponto como separador decimal
# (remove vírgulas que possam surgir como separadores de milhar)

def _to_float_txt(s: str) -> Optional[float]:
    if s is None:
        return None
    s = s.strip().replace(' ', '')
    if not s:
        return None
    # remover vírgulas (se existirem como separadores de milhar)
    s = s.replace(',', '')
    try:
        return float(s)
    except Exception:
        return None

# --------------------------------
# TXT parsing
# --------------------------------
def parse_txt_fixed_width(b: bytes) -> pd.DataFrame:
    txt = _decode_bytes(b)
    lines = [ln.rstrip("\\r\\n") for ln in txt.splitlines() if ln.strip()]
    rows = []
    for ln in lines:
        s = ln + " " * max(0, 192 - len(ln))  # padding até 192
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
            "COD": cod,
            "Entidade": entidade,
            "NE": ne,
            "Data": data_str,
            "Deb": deb,
            "Cred": cred,
            "Valor": valor_str,
            "Sinal": sinal,
            "CC": cc
        })
    df = pd.DataFrame(rows)
    return df

def aggregate_txt(df: pd.DataFrame) -> pd.DataFrame:
    m = (df["COD"] == "101") \
        & (~df["Entidade"].fillna("").str.startswith("9963")) \
        & (df["Entidade"].fillna("").str.startswith("999000")) \
        & (df["Sinal"] == "+")
    use = df.loc[m].copy()

    # Código de desconto = últimos 4 dígitos, convertido para número para remover zeros à esquerda
    use["CodigoDesconto"] = use["Entidade"].str[-4:].apply(lambda x: str(int(re.sub(r"\D","", x) or "0")))
    # Valor antes do + tem ponto como separador decimal
    use["ValorNum"] = use["Valor"].apply(_to_float_txt)
    use = use.dropna(subset=["ValorNum"])

    agg = (use.groupby("CodigoDesconto", as_index=False)["ValorNum"]
               .sum()
               .rename(columns={"ValorNum": "Total_txt"}))
    return agg

# --------------------------------
# PDF parsing (duas abordagens): Tabelas ou Palavras (manual/automática)
# --------------------------------
def parse_pdf_via_tables(pdf_bytes_list: List[bytes], settings: Dict, log: List[str]) -> pd.DataFrame:
    """Tenta extrair 'Descontos' como tabela com pdfplumber.extract_tables, com ajustes ao table_settings."""
    if pdfplumber is None:
        return pd.DataFrame(columns=["CodigoDesconto","NomeDesconto","Valor_pdf"])

    recs = []
    for idx, fb in enumerate(pdf_bytes_list, start=1):
        try:
            with pdfplumber.open(io.BytesIO(fb)) as pdf:
                for pi, page in enumerate(pdf.pages, start=1):
                    try:
                        tables = page.extract_tables(table_settings=settings)
                    except Exception as e:
                        log.append(f"[Tables] PDF#{idx} pág.{pi}: erro extract_tables: {e}")
                        continue

                    for ti, tbl in enumerate(tables, start=1):
                        # tbl é uma lista de linhas, cada linha é lista de células (strings)
                        df_tbl = pd.DataFrame(tbl)
                        # Tentar localizar o grupo "Descontos" e a coluna "Desconto"
                        # Heurística: procurar cabeçalhos que contenham 'Descont' e 'Desconto'
                        header = df_tbl.iloc[0].astype(str).str.lower()
                        if not (header.str.contains("descont").any() and header.str.contains("desconto").any()):
                            continue

                        # Assumir layout: três subcolunas sob "Descontos" + "Desconto" (valor)
                        # Vamos varrer colunas e tentar identificar: Código (numérico, 4 dígitos) e Nome (texto), e Valor (número)
                        for col_idx in range(df_tbl.shape[1]-1):
                            col_series = df_tbl.iloc[1:, col_idx].astype(str)
                            # procurar uma coluna com muitos 4 dígitos
                            hits = col_series.str.fullmatch(r"\d{4}").sum()
                            if hits >= max(3, int(0.2 * len(col_series))):
                                codigo_col = col_idx
                                # presumir nome na col seguinte e valor noutra coluna com vírgula
                                nome_col = col_idx + 1 if col_idx + 1 < df_tbl.shape[1] else None
                                # valor: procurar coluna com muitos números 1.234,56
                                valor_col = None
                                for c in range(df_tbl.shape[1]):
                                    if c == codigo_col or c == nome_col:
                                        continue
                                    patt = df_tbl.iloc[1:, c].astype(str).str.fullmatch(r"-?\d{1,3}(?:\.\d{3})*,\d{2}")
                                    if patt.sum() >= max(3, int(0.2 * len(df_tbl)-1)):
                                        valor_col = c
                                        break
                                if nome_col is None or valor_col is None:
                                    continue

                                # construir registos
                                for _, row in df_tbl.iloc[1:].iterrows():
                                    codigo = str(row[codigo_col]).strip()
                                    nome = str(row[nome_col]).strip()
                                    valor = _to_float_pt(str(row[valor_col]))
                                    if re.fullmatch(r"\d{4}", codigo) and valor is not None:
                                        recs.append({"CodigoDesconto": codigo, "NomeDesconto": nome, "Valor_pdf": valor})
                                break
        except Exception as e:
            log.append(f"[Tables] PDF#{idx}: {e}")

    if not recs:
        return pd.DataFrame(columns=["CodigoDesconto","NomeDesconto","Valor_pdf"])

    df = pd.DataFrame(recs)
    agg = (df.groupby("CodigoDesconto", as_index=False)
             .agg(Valor_pdf=("Valor_pdf","sum"),
                  NomeDesconto=("NomeDesconto", lambda s: s.value_counts().index[0] if len(s) else "")))
    return agg

def parse_pdf_via_words(pdf_bytes_list: List[bytes],
                        auto: bool,
                        x_cut1: Optional[float],
                        x_cut2: Optional[float],
                        y_tol: float,
                        codigo_regex: str,
                        code_pos_is_second: bool,
                        pad4: bool,
                        log: List[str]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Extrai por 'palavras' com duas opções: deteção automática (gaps) ou cortes manuais x_cut1/x_cut2."""
    if pdfplumber is None:
        return pd.DataFrame(columns=["CodigoDesconto","NomeDesconto","Valor_pdf"]), pd.DataFrame()

    preview_rows = []  # para debug/preview por página
    recs = []

    for idx, fb in enumerate(pdf_bytes_list, start=1):
        try:
            with pdfplumber.open(io.BytesIO(fb)) as pdf:
                for pi, page in enumerate(pdf.pages, start=1):
                    words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
                    if not words:
                        continue

                    # 1) localizar título 'Desconto' (valor) para saber a coluna dos valores.
                    x_valor = None
                    for w in words:
                        if w["text"].strip().lower() == "desconto":
                            x_valor = w["x0"]
                            break

                    # se não encontrar, estimar via números com vírgula (mais à direita)
                    if x_valor is None:
                        nums = [w for w in words if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})*,\d{2}", w["text"].strip())]
                        if nums:
                            x_valor = sorted([n["x0"] for n in nums])[-1]
                        else:
                            log.append(f"[Words] PDF#{idx} pág.{pi}: sem coluna de valores detetável.")
                            continue

                    # 2) obter linhas por y quantizado
                    linhas = {}
                    for w in words:
                        cy = (w["top"] + w["bottom"]) / 2
                        key_y = round(cy / y_tol) * y_tol
                        linhas.setdefault(key_y, []).append(w)

                    # 3) processar cada linha
                    for y, ws in sorted(linhas.items()):
                        ws_sorted = sorted(ws, key=lambda x: x["x0"])

                        # valor numérico (mais à direita, depois de x_valor)
                        nums = [w for w in ws_sorted if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})*,\d{2}", w["text"].strip())]
                        valor = None
                        if nums:
                            cand = max(nums, key=lambda w: w["x0"])
                            if cand["x0"] >= x_valor - 3:
                                valor = _to_float_pt(cand["text"].strip())

                        # bloco de 'Descontos': tudo à esquerda da coluna de valor
                        bloco = [w for w in ws_sorted if w["x0"] < x_valor - 3]
                        if not bloco or valor is None:
                            # preview ainda assim
                            preview_rows.append({"PDF": idx, "Pagina": pi, "y": y, "valor": valor, "linha_texto": " ".join([w["text"] for w in ws_sorted])})
                            continue

                        # detetar colunas do bloco: automática por gaps ou manual por cortes
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
                            # manual
                            if x_cut1 is None or x_cut2 is None:
                                log.append(f"[Words] pág.{pi}: cortes manuais não definidos.")
                                continue
                            c1, c2 = sorted([x_cut1, x_cut2])

                        col1 = [w for w in bloco if w["x0"] < c1]
                        col2 = [w for w in bloco if c1 <= w["x0"] < c2]
                        col3 = [w for w in bloco if w["x0"] >= c2]

                        # escolher de que subcoluna vem o código
                        col_codigo = col2 if code_pos_is_second else col1
                        col_nome = col3 if code_pos_is_second else col2 if col2 else col3

                        codigo_raw = "".join([w["text"] for w in col_codigo]).strip()
                        m = re.search(codigo_regex, codigo_raw)
                        codigo = m.group(0) if m else re.sub(r"[^\d]", "", codigo_raw)
                        if not codigo:
                            preview_rows.append({"PDF": idx, "Pagina": pi, "y": y, "valor": valor, "linha_texto": " ".join([w["text"] for w in bloco])})
                            continue

                        # Nome do desconto
                        nome = " ".join([w["text"] for w in col_nome]).strip()

                        recs.append({"Ficheiro": f"PDF#{idx}", "Pagina": pi, "CodigoDesconto": codigo, "NomeDesconto": nome, "Valor_pdf": valor})
                        preview_rows.append({"PDF": idx, "Pagina": pi, "y": y, "valor": valor, "codigo": codigo, "nome": nome, "linha_texto": " ".join([w["text"] for w in bloco])})

    # construir df
    df_preview = pd.DataFrame(preview_rows)
    if not recs:
        return pd.DataFrame(columns=["CodigoDesconto","NomeDesconto","Valor_pdf"]), df_preview

    df = pd.DataFrame(recs)
    df["CodigoDesconto"] = df["CodigoDesconto"].astype(str).str.replace(r"\D","", regex=True)
    # aceitar 3 ou 4 dígitos
    df = df[df["CodigoDesconto"].str.fullmatch(r"\d{3,4}")].copy()
    if pad4:
        df["CodigoDesconto"] = df["CodigoDesconto"].str.zfill(4)
    else:
        # formato numérico: remover zeros à esquerda e guardar como string de número
        df["CodigoDesconto"] = df["CodigoDesconto"].apply(lambda x: str(int(x)))

    agg = (df.groupby("CodigoDesconto", as_index=False)
             .agg(Valor_pdf=("Valor_pdf","sum"),
                  NomeDesconto=("NomeDesconto", lambda s: s.value_counts().index[0] if len(s) else "")))
    return agg, df_preview

# --------------------------------
# UI – Uploads
# --------------------------------
st.header("1) Carregar ficheiros")
st.caption("Se o seu TXT não tiver extensão, também funciona (o seletor aceita todos os tipos).")

c1, c2 = st.columns(2)
with c1:
    txt_file = st.file_uploader("Carregar TXT (largura fixa)", type=None, accept_multiple_files=False, key="txt")
with c2:
    pdf_files = st.file_uploader("Carregar PDF(s) das listagens", type=["pdf"], accept_multiple_files=True, key="pdfs")

# Modo avançado de parsing do PDF
st.header("2) Ajustes de parsing do PDF (opcional)")

tab1, tab2 = st.tabs(["Deteção por Tabelas", "Deteção por Palavras"])

with tab1:
    st.write("**pdfplumber.extract_tables** — útil quando o PDF tem grelha ou colunas bem definidas.")
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
    st.write("**Palavras com coordenadas (x,y)** — escolha automática por gaps ou cortes manuais.")
    code_pos = st.radio("Qual subcoluna de **Descontos** contém o CÓDIGO?", options=["2ª (padrão)", "1ª"], index=0)
    code_format = st.radio("Formato do código para comparar", options=["Número (sem zeros à esquerda)", "4 dígitos (zero à esquerda)"] , index=0)
    pad4 = (code_format.endswith("zero à esquerda"))
    auto = st.radio("Modo de colunas 'Descontos'", options=["Automático (por gaps)", "Manual (definir cortes x)"], index=0)
    auto_mode = auto.startswith("Automático")
    y_tol = st.number_input("Tolerância Y (agrupamento por linha)", min_value=0.5, value=2.0, step=0.5)
    cD, cE = st.columns(2)
    with cD:
        x_cut1 = st.number_input("x-cut1 (se manual)", min_value=0.0, value=100.0, step=5.0)
    with cE:
        x_cut2 = st.number_input("x-cut2 (se manual)", min_value=0.0, value=200.0, step=5.0)
    codigo_regex = st.text_input("Regex para extrair código", value=r"\d{3,4}")

# --------------------------------
# Botão principal
# --------------------------------
log_msgs: List[str] = []
if st.button("Processar e Comparar", type="primary"):
    if not txt_file or not pdf_files:
        st.error("Por favor, carregue o TXT e pelo menos um PDF.")
        st.stop()

    # TXT
    try:
        df_txt = parse_txt_fixed_width(txt_file.getvalue())
        txt_agg = aggregate_txt(df_txt)  # CodigoDesconto | Total_txt
    except Exception as e:
        st.exception(e)
        st.stop()

    # PDF – duas tentativas: tabelas, depois palavras
    pdf_bytes_list = [f.getvalue() for f in pdf_files]

    # 1) via tabelas
    pdf_agg_tables = parse_pdf_via_tables(pdf_bytes_list, table_settings, log_msgs)

    # 2) via palavras
    pdf_agg_words, df_preview = parse_pdf_via_words(
        pdf_bytes_list,
        auto=auto_mode,
        x_cut1=(x_cut1 if not auto_mode else None),
        x_cut2=(x_cut2 if not auto_mode else None),
        y_tol=y_tol,
        codigo_regex=codigo_regex,
        code_pos_is_second=(code_pos.startswith('2ª')),
        pad4=pad4,
        log=log_msgs
    )

    # escolher melhor (preferir tabelas se trouxe algo)
    pdf_agg = pdf_agg_tables if not pdf_agg_tables.empty else pdf_agg_words

    if pdf_agg.empty:
        st.error("Não foi possível extrair dados úteis dos PDFs. Ajuste os parâmetros em 'Ajustes de parsing do PDF' e volte a tentar.")
        if 'df_preview' in locals() and not df_preview.empty:
            st.subheader("Pré-visualização do parsing (palavras por linha)")
            st.dataframe(df_preview.head(200), use_container_width=True)
        if log_msgs:
            st.subheader("Logs")
            st.code("\\n".join(log_msgs))
        st.stop()

    # Comparação
    comp = pd.merge(txt_agg, pdf_agg, on="CodigoDesconto", how="outer")
    comp["Total_txt"] = comp["Total_txt"].fillna(0.0)
    comp["Valor_pdf"] = comp["Valor_pdf"].fillna(0.0)
    comp["NomeDesconto"] = comp.get("NomeDesconto", "")
    if isinstance(comp["NomeDesconto"], pd.Series):
        comp["NomeDesconto"] = comp["NomeDesconto"].fillna("")
    comp["Diferenca"] = comp["Total_txt"] - comp["Valor_pdf"]

    st.success("Processamento concluído.")

    st.subheader("Resumo (por Código de Desconto)")
    st.dataframe(comp.sort_values("CodigoDesconto").reset_index(drop=True), use_container_width=True)

    st.subheader("Top divergências (maior |diferença|)")
    topn = comp.reindex(comp["Diferenca"].abs().sort_values(ascending=False).index).head(30)
    st.dataframe(topn.reset_index(drop=True), use_container_width=True)

    import io as _io
    out = _io.BytesIO()
    with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
        txt_agg.sort_values("CodigoDesconto").to_excel(writer, sheet_name="TXT_aggregado", index=False)
        pdf_agg.sort_values("CodigoDesconto").to_excel(writer, sheet_name="PDF_aggregado", index=False)
        comp.sort_values("CodigoDesconto").to_excel(writer, sheet_name="Comparacao", index=False)
    out.seek(0)

    st.download_button(
        label="📥 Descarregar relatório (Excel)",
        data=out,
        file_name="comparacao_descontos.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    if 'df_preview' in locals() and not df_preview.empty:
        with st.expander("📋 Pré-visualização do parsing (palavras por linha)"):
            st.dataframe(df_preview, use_container_width=True)

    if log_msgs:
        with st.expander("🧾 Logs de processamento"):
            st.code("\\n".join(log_msgs))
