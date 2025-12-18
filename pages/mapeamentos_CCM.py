import io
import re
from typing import Dict, List, Tuple, Optional

import pandas as pd
import streamlit as st

# ==============================
# Funções de mapeamento
# ==============================

def df_to_mapping(df: pd.DataFrame) -> Dict[str, str]:
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

        ent_raw2 = str(ent_raw).replace(" ", "")
        if ent_raw2.endswith(".0"):
            ent_raw2 = ent_raw2[:-2]

        mapping[conv_code] = ent_raw2

    return mapping

@st.cache_data
def load_default_mapping(path: str = "mapeamentos.csv") -> Tuple[Dict[str, str], Optional[pd.DataFrame]]:
    """Carrega o ficheiro local mapeamentos.csv automaticamente."""
    try:
        df = pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")
        return df_to_mapping(df), df
    except Exception:
        try:
            df = pd.read_csv(path, sep=None, engine="python", encoding="latin-1")
            return df_to_mapping(df), df
        except Exception:
            return {}, None

# ==============================
# Lógica de Transformação
# ==============================

def transform_line(line: str, mapping: Dict[str, str]) -> str:
    # 1. Ajuste Coluna 12: Se posição 12 (índice 11) for '0', converte em espaço
    if len(line) >= 12 and line[11] == "0":
        line = line[:11] + " " + line[12:]

    s = line.rstrip("\n")

    # 2. Corrigir CC "+93  " -> "+9197"
    s = re.sub(r"\+93\s{2,}", "+9197", s)

    # 3. Mapeamento de tokens
    second_token_re = re.compile(r"^(\S+)(\s+)(\S+)(.*)$")
    m = second_token_re.match(s)
    if m:
        token1, sep, token2, rest = m.group(1), m.group(2), m.group(3), m.group(4)

        # Formato 14 dígitos
        if token2.isdigit() and len(token2) == 14:
            conv6 = token2[:6]
            ent_code = mapping.get(conv6)
            if ent_code:
                try:
                    ent7 = f"{int(ent_code):07d}"
                    s = token1 + sep + ent7 + token2[6:] + rest
                except ValueError: pass

        # Formato 15 dígitos
        elif token2.isdigit() and len(token2) == 15:
            field15_re = re.compile(r"^0(?P<conv>\d{6})91(?P<suffix>\d{6})$")
            m15 = field15_re.match(token2)
            if m15:
                ent_code = mapping.get(m15.group("conv"))
                if ent_code:
                    try:
                        ent7 = f"{int(ent_code):07d}"
                        s = token1 + sep + ent7 + "91" + m15.group("suffix") + rest
                    except ValueError: pass

    # 4. Remover último bloco de 9 dígitos
    s = re.sub(r"(\s)\d{9}$", r"\1", s)
    
    return s

def process_file_content(file_bytes: bytes, mapping: Dict[str, str]) -> bytes:
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1")

    lines = text.splitlines()
    processed_lines = [transform_line(line, mapping) for line in lines]
    return ("\n".join(processed_lines) + "\n").encode("utf-8")

# ==============================
# UI Streamlit
# ==============================

st.set_page_config(page_title="Conversor de ficheiros MCDT/Termas", layout="wide")
st.title("Conversor de ficheiros MCDT/Termas")

mapping_dict, _ = load_default_mapping("mapeamentos.csv")

if not mapping_dict:
    st.error("Erro: Ficheiro 'mapeamentos.csv' não encontrado ou inválido.")
else:
    st.success(f"Mapeamento carregado: {len(mapping_dict)} códigos.")
    
    uploaded_files = st.file_uploader("Submeta um ou mais ficheiros", accept_multiple_files=True)

    if uploaded_files:
        st.markdown("### Ficheiros Convertidos")
        st.info("Clique nos botões abaixo para descarregar cada ficheiro individualmente.")
        
        # Criamos colunas para organizar os botões de download
        for uploaded_file in uploaded_files:
            # Processa o conteúdo
            converted_data = process_file_content(uploaded_file.read(), mapping_dict)
            new_filename = f"CONVERTIDO_{uploaded_file.name}"
            
            # Gera um botão de download individual para cada ficheiro
            st.download_button(
                label=f"📥 Descarregar {uploaded_file.name}",
                data=converted_data,
                file_name=new_filename,
                mime="text/plain",
                key=uploaded_file.name # Chave única necessária para múltiplos botões
            )

st.divider()
st.caption("Ajuste da coluna 12 e descarga individual ativa.")
