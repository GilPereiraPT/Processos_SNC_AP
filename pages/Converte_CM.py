import io
import unicodedata
from datetime import datetime
import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Ficheiro CM — ULSLA", page_icon="📄", layout="wide")
st.title("📄 Gerar Ficheiro CM a partir de INFOCB* (upload)")
st.caption("Carrega um CSV cujo nome começa por **INFOCB** (separador ';', codificação cp1252) e gera o FicheiroCMYYYYMMDD.csv.")

# ---------- utilidades ----------
def normalize(txt: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", txt) if not unicodedata.combining(ch)).casefold()

def find_col(df, *candidates):
    cols = list(df.columns)
    for name in candidates:
        if name in cols:
            return name
    lowered = {c.casefold(): c for c in cols}
    for name in candidates:
        if name.casefold() in lowered:
            return lowered[name.casefold()]
    normed = {normalize(c): c for c in cols}
    for name in candidates:
        if normalize(name) in normed:
            return normed[normalize(name)]
    return None

def to_yyyymmdd_from_ddmmyyyy(s: str) -> str:
    s = str(s).strip()
    if not s:
        return ""
    d = pd.to_datetime(s, dayfirst=True, errors="coerce")
    return "" if pd.isna(d) else d.strftime("%Y%m%d")

def parse_money_pt_to_str_with_comma(v: str) -> str:
    """
    Converte valores em formato PT/variantes para string com vírgula e 2 casas.
    Exemplos aceites: '1.234,56', '1234,56', '1 234,56', '€ 1.234,56', '1234.56', '1234,56-', '(1.234,56)'
    """
    s = str(v).strip().replace("\xa0", " ")
    if not s:
        return ""
    # negativo com parênteses ou traço no fim
    neg = False
    if s.endswith("-"):
        neg, s = True, s[:-1].strip()
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1].strip()
    # remover moeda e quaisquer caracteres não dígitos/.,,/
    s = s.replace("€", "").replace("EUR", "").strip()
    # remover espaços de milhar
    s = s.replace(" ", "")
    # se houver vírgula, assume vírgula decimal → remove pontos como milhar
    if "," in s:
        s = s.replace(".", "")
        s = s.replace(",", ".")
    # senão, já estará com ponto decimal (ou inteiro)
    # remover quaisquer coisas extra
    s = re.sub(r"[^0-9.\-]", "", s)
    if s.count(".") > 1:
        # fallback: manter apenas a última como decimal
        parts = s.split(".")
        s = "".join(parts[:-1]) + "." + parts[-1]
    try:
        n = float(s)
        if neg:
            n = -n
        # formatar com vírgula decimal e 2 casas
        return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return ""

def build_output(df: pd.DataFrame) -> pd.DataFrame:
    # garantir texto + vazios
    df = df.astype(str).fillna("")

    # mapear colunas
    src_num_proc = find_col(df, "Num Proc. Aquisicao", "Num Proc. Aquisição", "Nº Proc. Aquisicao")
    src_data     = find_col(df, "Data", "Data documento", "Data Doc.")
    src_class_e  = find_col(df, "Classificador", "Classif. Economico", "Classif. Económico")
    src_class_f  = find_col(df, "Class Funcional", "Classificador funcional", "Classif. Funcional")
    src_ff       = find_col(df, "Fonte de financiamento", "Fonte de financiamento ")
    src_prog     = find_col(df, "Programa", "Programa ")
    src_medida   = find_col(df, "Medida")
    src_proj     = find_col(df, "Projeto")
    src_reg      = find_col(df, "Regionalização", "Regionalizacao")
    src_ativ     = find_col(df, "Atividade")
    src_nat      = find_col(df, "Natureza")
    src_dept     = find_col(df, "Departamento/ Atividade", "Departamento/Atividade")
    src_conta    = find_col(df, "Conta")
    # valor — tentar várias hipóteses
    src_valor    = find_col(df, "Valor", "Valor lançamento", "Valor lancamento", "Valor lan‡amento")
    src_class_o  = find_col(df, "Classificação orgânica", "Classificacao organica", "Classificação orgânica ")

    today_str = datetime.now().strftime("%Y%m%d")
    ano_cb = today_str[:4]

    desired_cols = [
        "CM","N§ Processo de Aquisi‡Æo (CB)","Data documento","Data Contabilistica","Ano CB",
        "classificador economico ","Classificador funcional ","Fonte de financiamento ","Programa ","Medida","Projeto",
        "Regionaliza‡Æo","Atividade","Natureza","Departamento/ Atividade","Conta","Valor lan‡amento",
        "Observa‡äes Documento ","Observa‡oes lan‡amento","Classifica‡Æo Orgƒnica","Referencia Grupo","Projeto Documento","S‚rie (CB)",
    ]

    out = pd.DataFrame(index=df.index)
    out["CM"] = "CM"
    out["N§ Processo de Aquisi‡Æo (CB)"] = df[src_num_proc] if src_num_proc else ""
    out["Data documento"] = df[src_data].map(to_yyyymmdd_from_ddmmyyyy) if src_data else ""
    out["Data Contabilistica"] = today_str
    out["Ano CB"] = ano_cb
    out["classificador economico "] = df[src_class_e] if src_class_e else ""
    out["Classificador funcional "] = df[src_class_f] if src_class_f else ""
    out["Fonte de financiamento "] = df[src_ff] if src_ff else ""
    out["Programa "] = df[src_prog] if src_prog else ""
    out["Medida"] = df[src_medida] if src_medida else ""
    out["Projeto"] = df[src_proj] if src_proj else ""
    out["Regionaliza‡Æo"] = df[src_reg] if src_reg else ""
    out["Atividade"] = df[src_ativ] if src_ativ else ""
    out["Natureza"] = df[src_nat] if src_nat else ""
    out["Departamento/ Atividade"] = df[src_dept] if src_dept else ""
    out["Conta"] = df[src_conta] if src_conta else ""

    # Valor lan‡amento — agora robusto
    if src_valor:
        out["Valor lan‡amento"] = df[src_valor].map(parse_money_pt_to_str_with_comma)
    else:
        out["Valor lan‡amento"] = ""

    out["Observa‡äes Documento "] = ""
    out["Observa‡oes lan‡amento"] = ""
    out["Classifica‡Æo Orgƒnica"] = df[src_class_o] if src_class_o else ""
    out["Referencia Grupo"] = ""
    out["Projeto Documento"] = ""
    out["S‚rie (CB)"] = ""

    return out[desired_cols]

# ---------- upload ----------
uploaded = st.file_uploader("Carregar ficheiro INFOCB*.CSV", type=["csv"])
if not uploaded:
    st.stop()

if not uploaded.name.upper().startswith("INFOCB") or not uploaded.name.upper().endswith(".CSV"):
    st.error("O nome do ficheiro deve começar por 'INFOCB' e terminar em '.CSV'.")
    st.stop()

try:
    df_in = pd.read_csv(uploaded, sep=";", encoding="cp1252", dtype=str).fillna("")
except Exception as e:
    st.error(f"Erro a ler o ficheiro: {e}")
    st.stop()

st.success(f"Lido: {uploaded.name} ({df_in.shape[0]} linhas, {df_in.shape[1]} colunas)")
with st.expander("Pré-visualização do ficheiro de origem (100 linhas)"):
    st.dataframe(df_in.head(100), use_container_width=True, height=280)

out_df = build_output(df_in)

st.subheader("Resultado")
with st.expander("Pré-visualização do resultado (100 linhas)", expanded=True):
    st.dataframe(out_df.head(100), use_container_width=True, height=320)

# nome de saída — apenas download (upload não permite gravar na pasta local)
output_name = f"FicheiroCM{datetime.now().strftime('%Y%m%d')}.csv"
csv_buf = io.StringIO()
out_df.to_csv(csv_buf, sep=";", index=False, encoding="cp1252")

st.download_button(
    "💾 Descarregar FicheiroCMYYYYMMDD.csv",
    data=csv_buf.getvalue().encode("cp1252", errors="replace"),
    file_name=output_name,
    mime="text/csv",
    use_container_width=True
)
