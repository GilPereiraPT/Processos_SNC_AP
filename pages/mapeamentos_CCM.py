# -*- coding: utf-8 -*-
"""Conversor MCDT / Termas — v3.0 (Estável e robusto)"""

import io
import re
import zipfile
import pandas as pd
import streamlit as st
from typing import Dict, Tuple, Optional
from datetime import datetime

# =========================================================
# 🔧 Função: Carregar Mapeamento
# =========================================================
@st.cache_data
def load_mapping(path: str = "mapeamentos.csv") -> Tuple[Dict[str, str], Optional[pd.DataFrame]]:
    """
    Lê o ficheiro CSV com mapeamentos (formato 824988;9809598)
    e devolve um dicionário limpo.
    """
    try:
        df = pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")
        mapping = {}
        c_col, e_col = df.columns[0], df.columns[1]

        for _, row in df.iterrows():
            c = str(row[c_col]).strip().replace(" ", "").replace(".", "").replace("-", "")
            e = str(row[e_col]).strip().replace(" ", "").replace(".0", "")
            if c and e and e.lower() != "nan":
                mapping[c] = e
        return mapping, df
    except Exception as e:
        st.error(f"Erro ao ler mapeamento: {e}")
        return {}, None

# =========================================================
# 🧠 Função: Substituir código dentro de linha
# =========================================================
def substituir_codigo(linha: str, mapping: Dict[str, str]) -> str:
    """
    Substitui o código de convenção (6 dígitos) pelo código da entidade (7 dígitos),
    mesmo que estejam concatenados.
    Mantém sempre o comprimento total da linha fixo.
    """
    original_len = len(linha)
    nova_linha = linha

    # Percorre o mapeamento (ordenado por comprimento descendente)
    for antigo, novo in sorted(mapping.items(), key=lambda x: len(x[0]), reverse=True):
        if antigo in nova_linha:
            nova_linha = nova_linha.replace(antigo, novo, 1)
            break  # apenas a primeira substituição por linha

    # Garante comprimento fixo
    if len(nova_linha) > original_len:
        nova_linha = nova_linha[:original_len]
    elif len(nova_linha) < original_len:
        nova_linha = nova_linha.ljust(original_len)

    return nova_linha

# =========================================================
# 📁 Função: Processar ficheiro
# =========================================================
def processar_ficheiro(uploaded_file, mapping: Dict[str, str]) -> Tuple[str, int]:
    """
    Processa todas as linhas de um ficheiro de texto e aplica substituições.
    Retorna o conteúdo corrigido e o número de substituições.
    """
    try:
        conteudo = uploaded_file.read().decode("utf-8")
    except UnicodeDecodeError:
        conteudo = uploaded_file.read().decode("latin-1")

    linhas = conteudo.splitlines(keepends=True)
    substituicoes = 0
    linhas_corrigidas = []

    for linha in linhas:
        nova = substituir_codigo(linha, mapping)
        if nova != linha:
            substituicoes += 1
        linhas_corrigidas.append(nova)

    return "".join(linhas_corrigidas), substituicoes

# =========================================================
# 🖥️ Streamlit Interface
# =========================================================
st.set_page_config(page_title="Conversor MCDT / Termas", layout="wide")
st.title("🧾 Conversor de Ficheiros MCDT / Termas — v3.0 (Estável)")
st.caption("Substitui códigos de convenção por entidade, mantendo formato fixo.")

mapping, df_map = load_mapping("mapeamentos.csv")

if not mapping:
    st.error("⚠️ Ficheiro 'mapeamentos.csv' não encontrado ou inválido.")
else:
    st.success(f"✅ {len(mapping)} códigos carregados com sucesso.")

    uploaded_files = st.file_uploader("📂 Carrega ficheiros TXT", type=["txt"], accept_multiple_files=True)

    if uploaded_files:
        if st.button("🚀 Iniciar Conversão"):
            log = []
            progress = st.progress(0)
            total_subs = 0

            # ZIP para vários ficheiros
            buffer_zip = io.BytesIO()
            with zipfile.ZipFile(buffer_zip, "w") as zipf:
                for idx, file in enumerate(uploaded_files):
                    resultado, subs = processar_ficheiro(file, mapping)
                    total_subs += subs
                    novo_nome = file.name.replace(".txt", "_CONVERTIDO.txt")
                    zipf.writestr(novo_nome, resultado)
                    log.append(f"✅ {file.name}: {subs} substituições")
                    progress.progress((idx + 1) / len(uploaded_files))

            buffer_zip.seek(0)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            nome_zip = f"ficheiros_convertidos_{ts}.zip"

            st.sidebar.download_button(
                label="📦 Descarregar ZIP Convertido",
                data=buffer_zip,
                file_name=nome_zip,
                mime="application/zip"
            )

            st.success(f"🔁 Total de substituições: {total_subs}")
            st.subheader("📋 Relatório de Conversão:")
            for linha in log:
                st.write(linha)

    else:
        st.info("👈 Carregue ficheiros TXT para iniciar a conversão.")
