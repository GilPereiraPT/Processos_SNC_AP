# -*- coding: utf-8 -*-
"""Página: Conversor de ficheiros MCDT/Termas — v2.4 (estável)"""

import io
import re
from typing import Dict, Tuple, Optional
import pandas as pd
import streamlit as st

# =========================================================
# Funções de Mapeamento
# =========================================================
@st.cache_data
def load_default_mapping(path: str = "mapeamentos.csv") -> Tuple[Dict[str, str], Optional[pd.DataFrame]]:
    """
    Lê o ficheiro CSV de mapeamento (com delimitador automático).
    Cria um dicionário de convenções -> entidades.
    """
    try:
        df = pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")
        mapping = {}
        c_col, e_col = df.columns[0], df.columns[1]

        for _, row in df.iterrows():
            c = re.sub(r"\D", "", str(row[c_col])).zfill(6)
            e = str(row[e_col]).strip().replace(".0", "").replace(" ", "")
            if c and e and e.lower() != "nan":
                mapping[c] = e
        return mapping, df
    except Exception:
        return {}, None

# =========================================================
# Lógica de Transformação (formato rígido)
# =========================================================
def transform_line(line: str, mapping: Dict[str, str]) -> str:
    """
    Aplica as substituições de convenção -> entidade numa linha de formato fixo.
    Mantém o comprimento total da linha.
    """

    # 1️⃣ Corrige espaços e padrões específicos
    if len(line) >= 12 and line[11] == "0":
        line = line[:11] + " " + line[12:]
    line = re.sub(r"\+93\s\s", "+9197", line)

    # 2️⃣ Analisa o segundo bloco (token2)
    m = re.search(r"^(\S+)(\s+)(\S+)", line)
    if m:
        token2 = m.group(3)
        start_pos = m.start(3)
        end_pos = m.end(3)

        matched_conv = None
        sorted_convs = sorted(mapping.keys(), key=len, reverse=True)
        for c_code in sorted_convs:
            if c_code in token2:
                matched_conv = c_code
                break

        if matched_conv:
            ent_code = mapping[matched_conv]
            try:
                ent7 = f"{int(ent_code):07d}"
                idx = token2.find(matched_conv)

                # Caso 1: há zero à esquerda (ex: "0824988")
                if idx > 0 and token2[idx-1] == '0':
                    new_token2 = token2[:idx-1] + ent7 + token2[idx+len(matched_conv):]
                else:
                    new_token2 = token2[:idx] + ent7 + token2[idx+len(matched_conv):]

                diff = len(new_token2) - len(token2)
                if diff > 0:
                    post_content = line[end_pos:]
                    line = line[:start_pos] + new_token2 + post_content[diff:]
                else:
                    line = line[:start_pos] + new_token2 + line[end_pos:]
            except ValueError:
                pass

    # 3️⃣ Remove NIF final (9 dígitos) mantendo espaços
    line = re.sub(r"(\s)\d{9}$", r"\1", line)

    return line

# =========================================================
# Função de processamento de ficheiros
# =========================================================
def processar_ficheiro(uploaded_file, mapping: Dict[str, str]) -> str:
    """
    Processa o ficheiro linha a linha e devolve o conteúdo convertido.
    """
    linhas_corrigidas = []
    conteudo = uploaded_file.read()

    try:
        texto = conteudo.decode("utf-8")
    except UnicodeDecodeError:
        texto = conteudo.decode("latin-1")

    for linha in texto.splitlines(keepends=True):
        linhas_corrigidas.append(transform_line(linha, mapping))

    return "".join(linhas_corrigidas)

# =========================================================
# Interface Streamlit
# =========================================================
st.set_page_config(page_title="Conversor MCDT (Formato Rígido)", layout="wide")
st.title("🧾 Conversor de ficheiros MCDT / Termas — v2.4 (estável)")

mapping_dict, df_mapping = load_default_mapping("mapeamentos.csv")

if not mapping_dict:
    st.error("❌ ERRO: Ficheiro 'mapeamentos.csv' não encontrado ou inválido.")
else:
    st.success(f"✅ Mapeamento carregado ({len(mapping_dict)} códigos lidos).")

    uploaded_files = st.file_uploader(
        "📂 Carrega ficheiros TXT para conversão individual",
        accept_multiple_files=True,
        type=["txt"]
    )

    if uploaded_files:
        for f in uploaded_files:
            content = f.read()
            try:
                text = content.decode("utf-8")
            except:
                text = content.decode("latin-1")

            # Processamento
            lines = text.splitlines()
            processed = [transform_line(l, mapping_dict) for l in lines]
            output = "\n".join(processed) + "\n"

            # Botão de download
            st.download_button(
                label=f"📥 Guardar {f.name}",
                data=output.encode("utf-8"),
                file_name=f"CORRIGIDO_{f.name}",
                mime="text/plain",
                key=f.name
            )
