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
    """Carrega o ficheiro local por defeito."""
    try:
        # Tenta ler com deteção automática de separador (virgula ou ponto e virgula)
        df = pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")
        return df_to_mapping(df), df
    except Exception:
        try:
            # Segunda tentativa com latin-1 se utf-8 falhar
            df = pd.read_csv(path, sep=None, engine="python", encoding="latin-1")
            return df_to_mapping(df), df
        except Exception:
            return {}, None

# ==============================
# Regex auxiliares
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
# Transformação
# ==============================

def transform_line(line: str, mapping: Dict[str, str]) -> Tuple[str, bool, bool]:
    # --- AJUSTE COLUNA 12 ---
    if len(line) >= 12 and line[11] == "0":
        line = line[:11] + " " + line[12:]

    s = line.rstrip("\n")
    changed = False
    mapping_missing = False

    s2 = re.sub(r"\+93\s{2,}", "+9197", s)
    if s2 != s:
        s = s2
        changed = True

    m = SECOND_TOKEN_RE.match(s)
    if m:
        token1, sep, token2, rest = m.group(1), m.group(2), m.group(3), m.group(4)

        if token2.isdigit() and len(token2) == 14:
            conv6 = token2[:6]
            ent_code = mapping.get(conv6)
            if ent_code:
                new_token2 = ent7_from_mapping(ent_code) + token2[6:]
                if new_token2 != token2:
                    s = token1 + sep + new_token2 + rest
                    changed = True
            else:
                mapping_missing = True

        elif token2.isdigit() and len(token2) == 15:
            m15 = FIELD15_RE.match(token2)
            if m15:
                ent_code = mapping.get(m15.group("conv"))
                if ent_code:
                    new_token2 = ent7_from_mapping(ent_code) + "91" + m15.group("suffix")
                    if new_token2 != token2:
                        s = token1 + sep + new_token2 + rest
                        changed = True
                else:
                    mapping_missing = True
        else:
            for match in EMBEDDED_CONV_RE.finditer(token1):
                ent_code = mapping.get(match.group("conv"))
                if ent_code:
                    ent7 = ent7_from_mapping(ent_code)
                    new_token1 = token1[:match.start()] + ent7 + token1[match.end():]
                    s = new_token1 + sep + token2 + rest
                    changed = True
                    break

    s2 = re.sub(r"(\s)\d{9}$", r"\1", s)
    if s2 != s:
        s = s2
        changed = True

    return s, changed, mapping_missing

def transform_file_bytes(file_bytes: bytes, mapping: Dict[str, str], encoding: str = "utf-8"):
    try:
        text = file_bytes.decode(encoding)
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1")

    lines = text.splitlines(keepends=False)
    out_lines = []
    changed_count = 0
    mapping_error_count = 0

    for line in lines:
        if not line.strip():
            out_lines.append(line)
            continue
        new_line, changed, missing = transform_line(line, mapping)
        out_lines.append(new_line)
        if changed: changed_count += 1
        if missing: mapping_error_count += 1

    return "\n".join(out_lines).encode(encoding), changed_count, len(lines), mapping_error_count

# ==============================
# UI Streamlit
# ==============================

st.set_page_config(page_title="Conversor de ficheiros MCDT/Termas", layout="wide")
st.title("Conversor de ficheiros MCDT/Termas")

# Carregamento Automático
mapping_dict, df_map = load_default_mapping("mapeamentos.csv")

if not mapping_dict:
    st.error("ERRO: Não foi possível encontrar ou ler o ficheiro 'mapeamentos.csv' na pasta do script.")
else:
    st.success(f"Mapeamento carregado automaticamente ({len(mapping_dict)} registos).")
    
    uploaded_files = st.file_uploader("Selecione os ficheiros para converter", accept_multiple_files=True)

    if uploaded_files:
        if st.button("Executar Conversão"):
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zf:
                for f in uploaded_files:
                    # Tenta converter usando utf-8, falha para latin-1 se necessário
                    out_b, chg, tot, miss = transform_file_bytes(f.read(), mapping_dict)
                    zf.writestr(f"CORRIGIDO_{f.name}", out_b)
            
            st.download_button(
                label="📥 Descarregar Ficheiros Corrigidos (ZIP)",
                data=zip_buffer.getvalue(),
                file_name="mcdt_processados.zip",
                mime="application/zip"
            )
