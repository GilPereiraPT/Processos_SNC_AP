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
    Converte DataFrame (>=2 colunas: convenção / entidade) para dict {conv6: entidade}.
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

        ent_raw2 = str(ent_raw).replace(" ", "")
        if ent_raw2.endswith(".0"):
            ent_raw2 = ent_raw2[:-2]

        mapping[conv_code] = ent_raw2

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
# CSV "em condições" (PT/Excel)
# ==============================

def clean_mapping_df(df: pd.DataFrame) -> pd.DataFrame:
    df2 = df.copy()

    df2.iloc[:, 0] = (
        df2.iloc[:, 0]
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.replace(r"\D", "", regex=True)
        .str.zfill(6)
    )

    df2.iloc[:, 1] = (
        df2.iloc[:, 1]
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
        .str.replace(" ", "", regex=False)
    )

    df2 = df2[(df2.iloc[:, 0] != "") & (df2.iloc[:, 0].str.lower() != "nan")]
    df2 = df2[(df2.iloc[:, 1] != "") & (df2.iloc[:, 1].str.lower() != "nan")]

    return df2


def df_to_csv_bytes_pt(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")


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
    # --- NOVO AJUSTE: COLUNA 12 ---
    # Se na posição 12 (índice 11) houver um '0', substitui por um espaço
    if len(line) >= 12 and line[11] == "0":
        line = line[:11] + " " + line[12:]

    s = line.rstrip("\n")
    changed = False
    mapping_missing = False

    # 1) Corrigir CC "+93  " → "+9197"
    s2 = re.sub(r"\+93\s{2,}", "+9197", s)
    if s2 != s:
        s = s2
        changed = True

    # 2) Atualizar campos
    m = SECOND_TOKEN_RE.match(s)
    if m:
        token1, sep, token2, rest = m.group(1), m.group(2), m.group(3), m.group(4)

        # 2A) Formato 14 dígitos
        if token2.isdigit() and len(token2) == 14:
            conv6 = token2[:6]
            tail8 = token2[6:]

            ent_code = mapping.get(conv6)
            if ent_code is None:
                mapping_missing = True
            else:
                new_token2 = ent7_from_mapping(ent_code) + tail8
                if new_token2 != token2:
                    s = token1 + sep + new_token2 + rest
                    changed = True

        # 2B) Formato antigo 15 dígitos
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

        # 2C) Convenção embebida no 1.º campo (NOVO)
        else:
            for match in EMBEDDED_CONV_RE.finditer(token1):
                conv6 = match.group("conv")

                ent_code = mapping.get(conv6)
                if ent_code is None:
                    continue

                ent7 = ent7_from_mapping(ent_code)

                new_token1 = (
                    token1[:match.start()]
                    + ent7
                    + token1[match.end():]
                )

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

st.set_page_config(page_title="Conversor de ficheiros MCDT/Termas", layout="wide")
st.title("Conversor de ficheiros MCDT/Termas")

# Aqui podes continuar com o resto da tua UI original (st.file_uploader, etc.)
