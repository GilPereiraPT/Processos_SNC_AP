import os
import io
import unicodedata
from datetime import datetime
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Ficheiro CM — ULSLA", page_icon="📄", layout="wide")
st.title("📄 Gerar Ficheiro CM a partir de INFOCB*")
st.caption("Lê um CSV que começa por 'INFOCB' e gera o FicheiroCMYYYYMMDD.csv com o layout pretendido.")

# ------------------ utilidades ------------------
def normalize(txt: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", txt) if not unicodedata.combining(ch)).casefold()

def find_col(df, *candidates):
    cols = list(df.columns)
    # exact
    for name in candidates:
        if name in cols:
            return name
    # casefold
    lowered = {c.casefold(): c for c in cols}
    for name in candidates:
        if name.casefold() in lowered:
            return lowered[name.casefold()]
    # no accents
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

def build_output(df: pd.DataFrame) -> pd.DataFrame:
    # colunas origem (todas como texto, vazios como "")
    df = df.copy()
    if df.dtypes.apply(lambda x: x != "object").any():
        df = df.astype(str)
    df = df.fillna("")

    src_num_proc = find_col(df, "Num Proc. Aquisicao", "Num Proc. Aquisição", "Nº Proc. Aquisicao")
    src_data     = find_col(df, "Data", "Data documento", "Data Doc.")
    src_class_e  = find_col(df, "Classificador", "Classif. Economico")
    src_class_f  = find_col(df, "Class Funcional", "Classificador funcional")
    src_ff       = find_col(df, "Fonte de financiamento")
    src_prog     = find_col(df, "Programa")
    src_medida   = find_col(df, "Medida")
    src_proj     = find_col(df, "Projeto")
    src_reg      = find_col(df, "Regionalização", "Regionalizacao")
    src_ativ     = find_col(df, "Atividade")
    src_nat      = find_col(df, "Natureza")
    src_dept     = find_col(df, "Departamento/ Atividade", "Departamento/Atividade")
    src_conta    = find_col(df, "Conta")
    src_valor    = find_col(df, "Valor", "Valor lançamento", "Valor lancamento")
    src_class_o  = find_col(df, "Classificação orgânica", "Classificacao organica")

    today_str = datetime.now().strftime("%Y%m%d")
    ano_cb = today_str[:4]

    desired_cols = [
        "CM",
        "N§ Processo de Aquisi‡Æo (CB)",
        "Data documento",
        "Data Contabilistica",
        "Ano CB",
        "classificador economico ",
        "Classificador funcional ",
        "Fonte de financiamento ",
        "Programa ",
        "Medida",
        "Projeto",
        "Regionaliza‡Æo",
        "Atividade",
        "Natureza",
        "Departamento/ Atividade",
        "Conta",
        "Valor lan‡amento",
        "Observa‡äes Documento ",
        "Observa‡oes lan‡amento",
        "Classifica‡Æo Orgƒnica",
        "Referencia Grupo",
        "Projeto Documento",
        "S‚rie (CB)",
    ]

    out = pd.DataFrame(index=df.index)
    out["CM"] = "CM"
    out["N§ Processo de Aquisi‡Æo (CB)"] = df[src_num_proc] if src_num_proc else ""
    out["Data documento"] = df[src_data].map(to_yyyymmdd_from_ddmmyyyy) if src_data else ""
    out["Data Contabilistica"] = today_str
    out["Ano CB"] = ano_cb

    # Classificadores: texto exato (preserva zeros à esquerda)
    out["classificador economico "] = df[src_class_e] if src_class_e else ""
    out["Classificador funcional "] = df[src_class_f] if src_class_f else ""

    # cópias diretas
    out["Fonte de financiamento "] = df[src_ff] if src_ff else ""
    out["Programa "] = df[src_prog] if src_prog else ""
    out["Medida"] = df[src_medida] if src_medida else ""
    out["Projeto"] = df[src_proj] if src_proj else ""
    out["Regionaliza‡Æo"] = df[src_reg] if src_reg else ""
    out["Atividade"] = df[src_ativ] if src_ativ else ""
    out["Natureza"] = df[src_nat] if src_nat else ""
    out["Departamento/ Atividade"] = df[src_dept] if src_dept else ""
    out["Conta"] = df[src_conta] if src_conta else ""

    # Valor lançamento → número com vírgula e 2 casas
    if src_valor:
        def fmt_val(v):
            v = str(v).strip().replace(".", "").replace(" ", "")  # remove separador de milhar caso exista
            v = v.replace(",", ".")  # decimal -> ponto para float
            try:
                n = float(v)
                # volta a vírgula como decimal, sem símbolo de moeda
                return f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            except Exception:
                return ""
        out["Valor lan‡amento"] = df[src_valor].map(fmt_val)
    else:
        out["Valor lan‡amento"] = ""

    # vazios
    out["Observa‡äes Documento "] = ""
    out["Observa‡oes lan‡amento"] = ""
    out["Classifica‡Æo Orgƒnica"] = df[src_class_o] if src_class_o else ""
    out["Referencia Grupo"] = ""
    out["Projeto Documento"] = ""
    out["S‚rie (CB)"] = ""

    return out[desired_cols]

# ------------------ interface ------------------
with st.sidebar:
    modo = st.radio("Escolha o modo de entrada", ["Selecionar ficheiro numa pasta", "Carregar ficheiro (upload)"])
    st.caption("O ficheiro deve começar por **INFOCB** e ser CSV com separador **;** (cp1252).")

df_in = None
input_name = None
input_dir = None

if modo == "Selecionar ficheiro numa pasta":
    pasta = st.text_input("Pasta local", value=os.getcwd())
    if os.path.isdir(pasta):
        candidatos = [f for f in os.listdir(pasta) if f.upper().startswith("INFOCB") and f.upper().endswith(".CSV")]
        if not candidatos:
            st.info("Não foram encontrados ficheiros INFOCB*.CSV nesta pasta.")
        else:
            escolhido = st.selectbox("Ficheiro", sorted(candidatos))
            if escolhido:
                caminho = os.path.join(pasta, escolhido)
                try:
                    df_in = pd.read_csv(caminho, sep=";", encoding="cp1252", dtype=str).fillna("")
                    input_name = escolhido
                    input_dir = pasta
                    st.success(f"Lido: {escolhido} ({df_in.shape[0]} linhas, {df_in.shape[1]} colunas)")
                except Exception as e:
                    st.error(f"Erro a ler o ficheiro: {e}")
    else:
        st.warning("A pasta indicada não existe.")

else:  # upload
    up = st.file_uploader("Carregar ficheiro INFOCB*.CSV", type=["csv"])
    if up is not None:
        if up.name.upper().startswith("INFOCB") and up.name.upper().endswith(".CSV"):
            try:
                df_in = pd.read_csv(up, sep=";", encoding="cp1252", dtype=str).fillna("")
                input_name = up.name
                st.success(f"Lido: {up.name} ({df_in.shape[0]} linhas, {df_in.shape[1]} colunas)")
            except Exception as e:
                st.error(f"Erro a ler o ficheiro: {e}")
        else:
            st.error("O nome do ficheiro deve começar por 'INFOCB' e terminar em '.CSV'.")

if df_in is None:
    st.stop()

with st.expander("Pré-visualização do ficheiro de origem (100 linhas)"):
    st.dataframe(df_in.head(100), use_container_width=True, height=280)

out_df = build_output(df_in)

st.subheader("Resultado")
with st.expander("Pré-visualização do resultado (100 linhas)", expanded=True):
    st.dataframe(out_df.head(100), use_container_width=True, height=320)

# nome de saída
hoje = datetime.now().strftime("%Y%m%d")
output_name = f"FicheiroCM{hoje}.csv"

col1, col2 = st.columns(2)
with col1:
    csv_bytes = io.StringIO()
    out_df.to_csv(csv_bytes, sep=";", index=False, encoding="cp1252")
    st.download_button(
        "💾 Descarregar (FicheiroCMYYYYMMDD.csv)",
        data=csv_bytes.getvalue().encode("cp1252", errors="replace"),
        file_name=output_name,
        mime="text/csv",
        use_container_width=True
    )

with col2:
    if input_dir is not None:
        save_path = os.path.join(input_dir, output_name)
        if st.button(f"📝 Guardar na mesma pasta ({save_path})", use_container_width=True):
            try:
                out_df.to_csv(save_path, sep=";", index=False, encoding="cp1252")
                st.success(f"Guardado em: {save_path}")
            except Exception as e:
                st.error(f"Falhou ao guardar: {e}")
    else:
        st.caption("Para guardar automaticamente na mesma pasta, use o modo **Selecionar ficheiro numa pasta**.")
