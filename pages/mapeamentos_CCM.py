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
    Converte DataFrame para dict {conv6: entidade}.
    Normaliza convenção para 6 dígitos e limpa a entidade.
    """
    if df.shape[1] < 2:
        return {}

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

        ent_clean = str(ent_raw).replace(" ", "")
        if ent_clean.endswith(".0"):
            ent_clean = ent_clean[:-2]

        mapping[conv_code] = ent_clean

    return mapping

def load_mapping_file(file) -> Tuple[Dict[str, str], pd.DataFrame]:
    filename = file.name.lower()
    if filename.endswith((".xlsx", ".xls")):
        df = pd.read_excel(file)
    else:
        df = pd.read_csv(file, sep=None, engine="python")
    return df_to_mapping(df), df

# ==============================
# Regex e Auxiliares
# ==============================

FIELD15_RE = re.compile(r"^0(?P<conv>\d{6})91(?P<suffix>\d{6})$")
SECOND_TOKEN_RE = re.compile(r"^(\S+)(\s+)(\S+)(.*)$")
EMBEDDED_CONV_RE = re.compile(r"(?P<conv>\d{6})")

def ent7_from_mapping(ent_code: str) -> str:
    try:
        return f"{int(ent_code):07d}"
    except ValueError:
        return ent_code

# ==============================
# Transformação Central
# ==============================

def transform_line(line: str, mapping: Dict[str, str]) -> Tuple[str, bool, bool]:
    # --- NOVO AJUSTE: COLUNA 12 ---
    # Se a posição 12 (índice 11) for '0', converte para espaço vazio
    if len(line) >= 12 and line[11] == "0":
        line = line[:11] + " " + line[12:]
    
    s = line.rstrip("\n\r")
    changed = False
    mapping_missing = False

    # 1) Corrigir CC "+93  " → "+9197"
    s2 = re.sub(r"\+93\s{2,}", "+9197", s)
    if s2 != s:
        s = s2
        changed = True

    # 2) Atualizar campos baseados em mapeamento
    m = SECOND_TOKEN_RE.match(s)
    if m:
        token1, sep, token2, rest = m.group(1), m.group(2), m.group(3), m.group(4)

        # 2A) Formato 14 dígitos
        if token2.isdigit() and len(token2) == 14:
            conv6 = token2[:6]
            tail8 = token2[6:]
            ent_code = mapping.get(conv6)
            if ent_code:
                new_token2 = ent7_from_mapping(ent_code) + tail8
                if new_token2 != token2:
                    s = token1 + sep + new_token2 + rest
                    changed = True
            else:
                mapping_missing = True

        # 2B) Formato antigo 15 dígitos
        elif token2.isdigit() and len(token2) == 15:
            m15 = FIELD15_RE.match(token2)
            if m15:
                conv6 = m15.group("conv")
                ent_code = mapping.get(conv6)
                if ent_code:
                    new_token2 = ent7_from_mapping(ent_code) + "91" + m15.group("suffix")
                    if new_token2 != token2:
                        s = token1 + sep + new_token2 + rest
                        changed = True
                else:
                    mapping_missing = True

        # 2C) Convenção embebida no 1.º campo
        else:
            for match in EMBEDDED_CONV_RE.finditer(token1):
                conv6 = match.group("conv")
                ent_code = mapping.get(conv6)
                if ent_code:
                    ent7 = ent7_from_mapping(ent_code)
                    new_token1 = token1[:match.start()] + ent7 + token1[match.end():]
                    if new_token1 != token1:
                        s = new_token1 + sep + token2 + rest
                        changed = True
                    break

    # 3) Remover último bloco de 9 dígitos
    s2 = re.sub(r"(\s)\d{9}$", r"\1", s)
    if s2 != s:
        s = s2
        changed = True

    return s, changed, mapping_missing

# ==============================
# Processamento em Lote
# ==============================

def process_all_files(uploaded_files, mapping, encoding):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        for file in uploaded_files:
            content = file.read()
            try:
                text = content.decode(encoding)
            except UnicodeDecodeError:
                text = content.decode("latin-1")
            
            lines = text.splitlines()
            processed_lines = [transform_line(line, mapping)[0] for line in lines]
            
            final_text = "\n".join(processed_lines) + "\n"
            zf.writestr(f"CORRIGIDO_{file.name}", final_text.encode(encoding))
            
    return zip_buffer

# ==============================
# Interface Streamlit
# ==============================

st.set_page_config(page_title="Conversor MCDT", layout="wide")
st.title("Conversor de Ficheiros MCDT (Ajuste Coluna 12)")

col1, col2 = st.columns(2)

with col1:
    st.header("1. Mapeamento")
    map_file = st.file_uploader("Upload Tabela (CSV/Excel)", type=["csv", "xlsx"])
    encoding_choice = st.selectbox("Encoding", ["utf-8", "iso-8859-1", "latin-1"])

with col2:
    st.header("2. Ficheiros de Dados")
    data_files = st.file_uploader("Ficheiros para processar", accept_multiple_files=True)

if map_file and data_files:
    mapping_dict, _ = load_mapping_file(map_file)
    
    if st.button("Processar e Gerar ZIP"):
        if not mapping_dict:
            st.error("Erro ao carregar mapeamento.")
        else:
            zip_result = process_all_files(data_files, mapping_dict, encoding_choice)
            st.success("Concluído!")
            st.download_button(
                label="Descarregar ZIP",
                data=zip_result.getvalue(),
                file_name="mcdt_corrigidos.zip",
                mime="application/zip"
            )
