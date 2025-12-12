import io
import re
import zipfile
from typing import Dict, List, Tuple, Optional

import pandas as pd
import streamlit as st


# ==============================
# Funções de mapeamento
# ==============================

def df_to_mapping(df: pd.DataFrame) -> Dict[str, str]:
    """
    Converte DataFrame (>=2 colunas: convenção / entidade)
    para dict {conv6: entidade}.
    Normaliza convenção para 6 dígitos (30400/30400.0 -> 030400).
    """
    if df.shape[1] < 2:
        raise ValueError("O ficheiro de mapeamento tem de ter pelo menos duas colunas.")

    conv_col = df.columns[0]
    ent_col = df.columns[1]

    mapping: Dict[str, str] = {}
    for _, row in df.iterrows():
        conv_raw = str(row[conv_col]).strip()
        ent_raw = str(row[ent_col]).strip()

        if not conv_raw or conv_raw.lower() in ("nan", "none"):
            continue
        if not ent_raw or ent_raw.lower() in ("nan", "none"):
            continue

        conv_digits = re.sub(r"\D", "", conv_raw)
        conv_code = conv_digits.zfill(6) if conv_digits else conv_raw

        try:
            ent_int = int(str(ent_raw).replace(" ", ""))
            ent_code = str(ent_int)
        except ValueError:
            ent_code = ent_raw.replace(" ", "")

        mapping[conv_code] = ent_code

    return mapping


def load_default_mapping(path: str = "mapeamentos.csv") -> Tuple[Dict[str, str], Optional[pd.DataFrame]]:
    try:
        df = pd.read_csv(path, sep=None, engine="python")
        return df_to_mapping(df), df
    except FileNotFoundError:
        return {}, None


def load_mapping_file(file) -> Tuple[Dict[str, str], pd.DataFrame]:
    filename = file.name.lower()
    if filename.endswith((".xlsx", ".xls")):
        df = pd.read_excel(file)
    else:
        df = pd.read_csv(file, sep=None, engine="python")
    return df_to_mapping(df), df


# ==============================
# Helpers de transformação
# ==============================

# Formato “antigo” (15 dígitos): 0 + conv(6) + 91 + sufixo(6)
FIELD15_RE = re.compile(r"^0(?P<conv>\d{6})91(?P<suffix>\d{6})$")

# Linha -> token1 + espaços + token2 + resto (para manter espaçamento)
SECOND_TOKEN_RE = re.compile(r"^(\S+)(\s+)(\S+)(.*)$")


def ent7_from_mapping(ent_code: str) -> str:
    """Entidade com 7 dígitos (padding se numérica)."""
    try:
        return f"{int(ent_code):07d}"
    except ValueError:
        return ent_code


# ==============================
# Transformação por linha
# ==============================

def transform_line(line: str, mapping: Dict[str, str]) -> Tuple[str, bool, bool]:
    s = line.rstrip("\n")
    changed = False
    mapping_missing = False

    # 1) Corrigir CC mal formatado: "+93  " (>=2 espaços) → "+9197"
    s2 = re.sub(r"\+93\s{2,}", "+9197", s)
    if s2 != s:
        s = s2
        changed = True

    # 2) Trabalhar APENAS no 2.º campo (token2), mantendo espaços originais
    m = SECOND_TOKEN_RE.match(s)
    if m:
        token1, sep, token2, rest = m.group(1), m.group(2), m.group(3), m.group(4)

        # 2A) NOVO formato (14 dígitos): conv(6) + last8(token1)
        # Ex.: 800892 + 91908697  -> 9809183 + 91908697
        if token2.isdigit() and len(token2) == 14:
            conv6 = token2[:6]
            tail8 = token2[6:]  # 8 dígitos

            ent_code = mapping.get(conv6)
            if ent_code is None:
                mapping_missing = True
            else:
                new_token2 = ent7_from_mapping(ent_code) + tail8  # 7 + 8 = 15
                if new_token2 != token2:
                    s = token1 + sep + new_token2 + rest
                    changed = True

        # 2B) Formato antigo (15 dígitos): 0 + conv(6) + 91 + sufixo(6)
        elif token2.isdigit() and len(token2) == 15:
            m15 = FIELD15_RE.match(token2)
            if m15:
                conv6 = m15.group("conv")
                suffix6 = m15.group("suffix")
                ent_code = mapping.get(conv6)

                if ent_code is None:
                    mapping_missing = True
                else:
                    new_token2 = ent7_from_mapping(ent_code) + "91" + suffix6
                    if new_token2 != token2:
                        s = token1 + sep + new_token2 + rest
                        changed = True

    # 3) Remover o último bloco de 9 dígitos no fim da linha (mantendo o espaço anterior)
    s2 = re.sub(r"(\s)\d{9}$", r"\1", s)
    if s2 != s:
        s = s2
        changed = True

    return s, changed, mapping_missing


# ==============================
# Transformação por ficheiro
# ==============================

def transform_file_bytes(
    file_bytes: bytes, mapping: Dict[str, str], encoding: str = "utf-8"
) -> Tuple[bytes, bytes, int, int, int]:
    try:
        text = file_bytes.decode(encoding)
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1")

    lines = text.splitlines(keepends=False)

    out_lines: List[str] = []
    error_lines: List[str] = []
    changed_count = 0
    mapping_error_count = 0

    for line in lines:
        if not line.strip():
            out_lines.append(line)
            continue

        new_line, changed, missing = transform_line(line, mapping)
        out_lines.append(new_line)

        if changed:
            changed_count += 1
        if missing:
            mapping_error_count += 1
            error_lines.append(line)

    out_text = "\n".join(out_lines) + "\n"
    err_text = "\n".join(error_lines) + "\n" if error_lines else ""

    return (
        out_text.encode(encoding),
        err_text.encode(encoding),
        changed_count,
        len(lines),
        mapping_error_count,
    )


# ==============================
# UI Streamlit
# ==============================

st.set_page_config(page_title="Conversor de Ficheiros MCDT/Termas", layout="wide")
st.title("Conversor de ficheiros MCDT/Termas")

st.write(
    """
    Esta aplicação:
    1. Usa um **mapeamento Cod. Convenção → Cod. Entidade** (CSV no repositório ou ficheiro carregado);  
    2. Corrige CC com `+93` mal formatado para `+9197`;  
    3. Atualiza o **2.º campo**, suportando:
       - formato **14 dígitos**: `conv(6)+tail(8)` → `ent(7)+tail(8)`
       - formato **15 dígitos**: `0+conv(6)+91+sufixo(6)` → `ent(7)+91+sufixo(6)`  
    4. Remove o último código de 9 dígitos no fim de cada linha;  
    5. Gera, por ficheiro:
       - apenas *_CONVERTIDO.txt* se estiver tudo mapeado;
       - apenas *_ERROS.txt* se existirem códigos sem mapeamento.
    """
)

default_mapping, default_df = load_default_mapping()

st.sidebar.header("Fonte do mapeamento")

mapping: Dict[str, str] = {}
mapping_df: Optional[pd.DataFrame] = None

if default_mapping:
    mapping_source = st.sidebar.radio(
        "Escolher fonte do mapeamento",
        ["CSV do repositório (mapeamentos.csv)", "Carregar outro ficheiro"],
        index=0,
    )
else:
    st.sidebar.info("Nenhum 'mapeamentos.csv' encontrado no repositório.")
    mapping_source = "Carregar outro ficheiro"

if mapping_source == "CSV do repositório (mapeamentos.csv)" and default_mapping:
    mapping = default_mapping
    mapping_df = default_df
    st.success(f"Mapeamento carregado de 'mapeamentos.csv' ({len(mapping)} entradas).")

if mapping_source == "Carregar outro ficheiro":
    st.header("1️⃣ Carregar ficheiro de mapeamento")
    mapping_file = st.file_uploader(
        "Ficheiro de mapeamento (CSV, TXT, XLSX, ...)",
        type=["csv", "txt", "tsv", "xlsx", "xls"],
        key="mapping_uploader",
    )
    if mapping_file is not None:
        try:
            mapping, mapping_df = load_mapping_file(mapping_file)
            st.success(f"Mapeamento carregado com {len(mapping)} códigos de convenção.")
        except Exception as e:
            st.error(f"Erro ao ler ficheiro de mapeamento: {e}")

if mapping_df is not None:
    st.header("📚 Base de dados de mapeamentos")
    st.write("Podes editar a tabela abaixo e descarregar um CSV atualizado.")

    edited_df = st.data_editor(
        mapping_df,
        num_rows="dynamic",
        use_container_width=True,
        key="mapping_editor",
    )

    csv_bytes = edited_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="⬇️ Descarregar CSV atualizado (para substituir o mapeamentos.csv no GitHub)",
        data=csv_bytes,
        file_name="mapeamentos_atualizado.csv",
        mime="text/csv",
    )
else:
    st.info("Ainda não há mapeamento carregado/selecionado.")

st.header("2️⃣ Carregar ficheiros a converter")
data_files = st.file_uploader(
    "Ficheiros de texto a converter",
    type=["txt"],
    accept_multiple_files=True,
    key="data_files_uploader",
)

if data_files and not mapping:
    st.warning("Carrega/seleciona primeiro um mapeamento válido (CSV/Excel).")

if data_files and mapping:
    st.subheader("Resultados da conversão")

    all_results = []
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for uploaded_file in data_files:
            file_bytes = uploaded_file.read()

            converted_bytes, error_bytes, changed_count, total_lines, mapping_error_count = transform_file_bytes(
                file_bytes, mapping
            )

            base_name = uploaded_file.name.rsplit(".", 1)[0]
            out_name = f"{base_name}_CONVERTIDO.txt"
            err_name = f"{base_name}_ERROS.txt"

            st.markdown(f"### {uploaded_file.name}")

            if mapping_error_count > 0:
                zipf.writestr(err_name, error_bytes)
                all_results.append(
                    {
                        "Ficheiro original": uploaded_file.name,
                        "Ficheiro convertido": "",
                        "Linhas alteradas": changed_count,
                        "Total de linhas": total_lines,
                        "Linhas com código sem mapeamento": mapping_error_count,
                    }
                )
                st.markdown(f"**Erros de mapeamento → {err_name}**")
                st.download_button(
                    label=f"⬇️ Descarregar {err_name}",
                    data=error_bytes,
                    file_name=err_name,
                    mime="text/plain",
                )
                st.warning(
                    f"{mapping_error_count} linha(s) sem mapeamento para o código de convenção. "
                    f"Apenas foi gerado o ficheiro de erros ({err_name})."
                )
            else:
                zipf.writestr(out_name, converted_bytes)
                all_results.append(
                    {
                        "Ficheiro original": uploaded_file.name,
                        "Ficheiro convertido": out_name,
                        "Linhas alteradas": changed_count,
                        "Total de linhas": total_lines,
                        "Linhas com código sem mapeamento": mapping_error_count,
                    }
                )
                st.markdown(f"**Convertido → {out_name}**")
                st.download_button(
                    label=f"⬇️ Descarregar {out_name}",
                    data=converted_bytes,
                    file_name=out_name,
                    mime="text/plain",
                )
                st.success("Nenhuma linha com código de convenção em falta no mapeamento.")

            st.write(f"- Linhas alteradas: {changed_count} / {total_lines}")
            st.divider()

    if all_results:
        st.subheader("Resumo da conversão")
        st.dataframe(pd.DataFrame(all_results))

        zip_buffer.seek(0)
        st.download_button(
            label="⬇️ Descarregar todos (convertidos + erros) em ZIP",
            data=zip_buffer,
            file_name="ficheiros_convertidos_e_erros.zip",
            mime="application/zip",
        )
