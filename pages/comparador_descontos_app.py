
import io
import re
import math
import zipfile
import pandas as pd
import streamlit as st
from typing import List, Tuple, Dict, Optional

# Optional heavy parsers — fallback to pdfplumber if available
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
    - Somar o **Valor** **apenas** das linhas com `Sinal = "+"` (valor antes do `+`).

    **Passo 2 — PDF**  
    - Em cada página, localizar a coluna **Descontos** (3 sub-colunas) e a coluna **Desconto** (valor).  
    - Desprezar a 1.ª subcoluna de **Descontos**.  
    - Usar a 2.ª subcoluna como **Código** e a 3.ª como **Nome do desconto**.  
    - Somar a coluna **Desconto** (valor) por **Código**.  
    - Manter um nome representativo por código (mais frequente).

    **Comparação**  
    - Junta por `CodigoDesconto` e calcula `Diferença = Total_txt - Total_pdf`.
    """)

# -----------------------------
# Helpers
# -----------------------------
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

# -----------------------------
# TXT parsing
# -----------------------------
def parse_txt_fixed_width(b: bytes) -> pd.DataFrame:
    txt = _decode_bytes(b)
    lines = [ln.rstrip("\r\n") for ln in txt.splitlines() if ln.strip()]
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
    # Filtros de negócio
    m = (df["COD"] == "101") \
        & (~df["Entidade"].fillna("").str.startswith("9963")) \
        & (df["Entidade"].fillna("").str.startswith("999000")) \
        & (df["Sinal"] == "+")
    use = df.loc[m].copy()

    # Código de desconto: últimos 4 dígitos da entidade
    use["CodigoDesconto"] = use["Entidade"].str[-4:]

    # Normalizar Valor (antes do '+')
    use["ValorNum"] = use["Valor"].apply(_to_float_pt)
    use = use.dropna(subset=["ValorNum"])

    agg = (use.groupby("CodigoDesconto", as_index=False)["ValorNum"]
               .sum()
               .rename(columns={"ValorNum": "Total_txt"}))

    return agg

# -----------------------------
# PDF parsing
# -----------------------------
def parse_pdf_descontos(files: List[bytes], log: List[str]) -> pd.DataFrame:
    if pdfplumber is None:
        st.error("pdfplumber não está instalado. Verifique o requirements.txt.")
        return pd.DataFrame(columns=["CodigoDesconto","NomeDesconto","Valor_pdf"])

    recs = []

    for file_idx, fb in enumerate(files, start=1):
        try:
            with pdfplumber.open(io.BytesIO(fb)) as pdf:
                for pi, page in enumerate(pdf.pages, start=1):
                    words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
                    if not words:
                        continue

                    # Localizar os cabeçalhos "Descontos" e "Desconto" (valor)
                    hdr_y = None
                    x_descontos = None
                    x_valor = None

                    for w in words:
                        t = w["text"].strip().lower()
                        if t == "descontos" and hdr_y is None:
                            hdr_y = (w["top"] + w["bottom"]) / 2
                            x_descontos = w["x0"]
                        if t == "desconto" and x_valor is None:
                            x_valor = w["x0"]

                    if hdr_y is None or x_valor is None:
                        # não encontrou cabeçalhos — tentar fallback heurístico
                        # Heurística: procurar uma coluna de valores numéricos à direita
                        nums = [w for w in words if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})*,\d{2}", w["text"].strip())]
                        if nums:
                            # assumir a coluna de valores como o cluster de x mais à direita
                            x_valor = sorted([n["x0"] for n in nums])[-1]
                            hdr_y = min([n["top"] for n in nums]) - 20  # acima dos números
                            # e estimar início de "Descontos" um pouco à esquerda
                            x_descontos = min([w["x0"] for w in words]) + 40
                            log.append(f"[Fallback] Página {pi}: cabeçalho estimado.")
                        else:
                            log.append(f"[Aviso] Página {pi}: não encontrei cabeçalhos nem números de 'Desconto'.")
                            continue

                    # Agrupar por linha visual (Y)
                    linhas = {}
                    for w in words:
                        cy = (w["top"] + w["bottom"]) / 2
                        if cy <= hdr_y + 2:
                            continue
                        key_y = round(cy, 1)
                        linhas.setdefault(key_y, []).append(w)

                    for y, ws in sorted(linhas.items()):
                        ws_sorted = sorted(ws, key=lambda x: x["x0"])

                        # Valor: número com vírgula, mais à direita, depois de x_valor
                        nums = [w for w in ws_sorted if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})*,\d{2}", w["text"].strip())]
                        valor = None
                        if nums:
                            cand = max(nums, key=lambda w: w["x0"])
                            if cand["x0"] >= x_valor - 5:
                                valor = _to_float_pt(cand["text"])

                        # Bloco "Descontos": entre x_descontos e x_valor
                        bloco = [w for w in ws_sorted if (w["x0"] >= x_descontos - 5 and w["x0"] < x_valor - 5)]
                        if not bloco or valor is None:
                            continue

                        xs_sorted = sorted(set([w["x0"] for w in bloco]))
                        if len(xs_sorted) < 3:
                            # não dá para segmentar 3 subcolunas
                            continue

                        # Procurar 2 maiores gaps para separar 3 subcolunas
                        gaps = [(xs_sorted[i+1]-xs_sorted[i], xs_sorted[i], xs_sorted[i+1]) for i in range(len(xs_sorted)-1)]
                        gaps_sorted = sorted(gaps, key=lambda g: g[0], reverse=True)
                        if len(gaps_sorted) < 2:
                            continue
                        cut1 = gaps_sorted[0][2]
                        cut2 = gaps_sorted[1][2]
                        c1, c2 = sorted([cut1, cut2])

                        col1 = [w for w in bloco if w["x0"] < c1]
                        col2 = [w for w in bloco if c1 <= w["x0"] < c2]  # Código
                        col3 = [w for w in bloco if w["x0"] >= c2]       # Nome

                        codigo = "".join([w["text"] for w in col2]).strip()
                        codigo = re.sub(r"[^\d]", "", codigo)
                        if not codigo:
                            continue
                        if len(codigo) >= 4:
                            codigo = codigo[-4:]  # normalizar para 4 últimos dígitos

                        nome = " ".join([w["text"] for w in col3]).strip()

                        recs.append({
                            "Ficheiro": f"PDF#{file_idx}",
                            "Pagina": pi,
                            "CodigoDesconto": codigo,
                            "NomeDesconto": nome,
                            "Valor_pdf": valor
                        })
        except Exception as e:
            log.append(f"[Erro] PDF #{file_idx}: {e}")

    if not recs:
        return pd.DataFrame(columns=["CodigoDesconto","NomeDesconto","Valor_pdf"])

    df = pd.DataFrame(recs)
    # Manter somente códigos com 4 dígitos
    df = df[df["CodigoDesconto"].str.fullmatch(r"\d{4}")].copy()

    # Agregar por código e escolher um nome representativo
    agg = (df.groupby("CodigoDesconto", as_index=False)
             .agg(Valor_pdf=("Valor_pdf","sum"),
                  NomeDesconto=("NomeDesconto", lambda s: s.value_counts().index[0] if len(s) else "")))

    return agg

# -----------------------------
# UI
# -----------------------------
st.header("1) Carregar ficheiros")
st.caption("Se o seu TXT não tiver extensão, também funciona (o seletor aceita todos os tipos).")

c1, c2 = st.columns(2)
with c1:
    txt_file = st.file_uploader("Carregar TXT (largura fixa)", type=None, accept_multiple_files=False, key="txt")
with c2:
    pdf_files = st.file_uploader("Carregar PDF(s) das listagens", type=["pdf"], accept_multiple_files=True, key="pdfs")

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

    # PDF
    pdf_bytes_list = [f.getvalue() for f in pdf_files]
    pdf_agg = parse_pdf_descontos(pdf_bytes_list, log_msgs)

    if pdf_agg.empty:
        st.warning("Não foi possível extrair dados dos PDFs. Verifique o layout ou ative o fallback.")

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

    # Exportar Excel
    out = io.BytesIO()
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

    with st.expander("📋 Registo de processamento / logs"):
        if log_msgs:
            st.code("\n".join(log_msgs))
        else:
            st.write("Sem avisos/erros.")
