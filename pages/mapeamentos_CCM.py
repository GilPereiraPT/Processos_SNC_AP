# -*- coding: utf-8 -*-
"""Página: Conversor MCDT / Termas — v2.5"""

import io
import re
from typing import Dict, List, Tuple, Optional
import pandas as pd
import streamlit as st

# =========================================================
# ⚙️ Carregamento de Mapeamento
# =========================================================
@st.cache_data
def load_default_mapping(path: str = "mapeamentos.csv") -> Tuple[Dict[str, str], Optional[pd.DataFrame]]:
    """
    Lê o ficheiro de mapeamento CSV (com ; ou ,) e devolve um dicionário de códigos.
    Exemplo: 824988;9809598  → {"824988": "9809598"}
    """
    try:
        df = pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")
        mapping = {}

        # Assume que as duas primeiras colunas contêm os códigos
        c_col, e_col = df.columns[0], df.columns[1]
        for _, row in df.iterrows():
            c = str(row[c_col]).strip().replace(" ", "").replace(".", "").replace("-", "")
            e = str(row[e_col]).strip().replace(" ", "").replace(".0", "")
            if c and e and e.lower() != "nan":
                mapping[c] = e
        return mapping, df
    except Exception:
        return {}, None

# =========================================================
# 🔁 Função de Substituição Rígida
# =========================================================
def transform_line(line: str, mapping: Dict[str, str]) -> str:
    """
    Substitui códigos de convenção (CCM) por entidades em ficheiros de formato fixo.
    - Procura os códigos em toda a linha (não apenas num bloco específico);
    - Mantém o comprimento total da linha;
    - Substitui mesmo dentro de blocos concatenados;
    - Remove NIF no final da linha (9 dígitos seguidos).
    """

    # 1️⃣ Correções específicas (mantidas da versão original)
    if len(line) >= 12 and line[11] == "0":
        line = line[:11] + " " + line[12:]

    # Correção padrão para certos padrões conhecidos
    line = re.sub(r"\+93\s\s", "+9197", line)

    old_len = len(line)

    # 2️⃣ Substituição inteligente: percorre todos os códigos do mapeamento
    for c_code, ent_code in sorted(mapping.items(), key=lambda x: len(x[0]), reverse=True):
        if c_code in line:
            start = line.find(c_code)
            if start != -1:
                end = start + len(c_code)
                # Substituição direta
                line = line[:start] + ent_code + line[end:]
                # Ajustar o comprimento total (mantém fixo)
                if len(line) > old_len:
                    line = line[:old_len]
                elif len(line) < old_len:
                    line = line.ljust(old_len)
                break  # só substitui a primeira ocorrência por linha

    # 3️⃣ Remover NIF no fim (mantendo espaço)
    line = re.sub(r"(\s)\d{9}$", r"\1", line)

    # 4️⃣ Garantir que o comprimento final é igual ao original
    if len(line) != old_len:
        line = line[:old_len].ljust(old_len)

    return line

# =========================================================
# 🧰 Função de Processamento de Ficheiros
# =========================================================
def processar_ficheiro(uploaded_file, mapping: Dict[str, str]) -> Tuple[str, int, int]:
    """
    Processa um ficheiro linha a linha e aplica as substituições de códigos.
    Retorna o novo conteúdo, o número total de linhas e o número de substituições realizadas.
    """
    content = uploaded_file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    linhas = text.splitlines(keepends=True)
    total_linhas = len(linhas)
    substituicoes = 0
    output = []

    for line in linhas:
        old_line = line
        new_line = transform_line(line, mapping)
        if old_line != new_line:
            substituicoes += 1
        output.append(new_line)

    return "".join(output), total_linhas, substituicoes

# =========================================================
# 🖥️ Interface Streamlit
# =========================================================
st.set_page_config(page_title="Conversor MCDT (Formato Rígido)", layout="wide")
st.title("📄 Conversor de Ficheiros MCDT / Termas — v2.5")
st.caption("Suporta substituições concatenadas e mantém alinhamento fixo em todas as linhas.")

# Carregamento do mapeamento
mapping_dict, df_mapping = load_default_mapping("mapeamentos.csv")

if not mapping_dict:
    st.error("❌ ERRO: Ficheiro 'mapeamentos.csv' não encontrado ou inválido.")
else:
    st.success(f"✅ Mapeamento carregado com {len(mapping_dict)} códigos válidos.")

    uploaded_files = st.file_uploader("📂 Submete ficheiros TXT para conversão", accept_multiple_files=True, type=["txt"])

    if uploaded_files:
        if st.button("🚀 Iniciar Conversão"):
            progress_bar = st.progress(0)
            log = []

            if len(uploaded_files) == 1:
                uploaded_file = uploaded_files[0]
                resultado, total, subs = processar_ficheiro(uploaded_file, mapping_dict)

                buffer_txt = io.BytesIO(resultado.encode("utf-8"))
                novo_nome = uploaded_file.name.replace(".txt", "_CONVERTIDO.txt")

                st.sidebar.download_button(
                    "📥 Descarregar Ficheiro Convertido",
                    data=buffer_txt,
                    file_name=novo_nome,
                    mime="text/plain"
                )

                st.info(f"📊 Total de linhas: {total:,}")
                st.success(f"🔁 Substituições efetuadas: {subs:,}")

            else:
                buffer_zip = io.BytesIO()
                total_linhas = 0
                total_subs = 0

                with zipfile.ZipFile(buffer_zip, "w") as zipf:
                    for idx, uploaded_file in enumerate(uploaded_files):
                        resultado, total, subs = processar_ficheiro(uploaded_file, mapping_dict)
                        novo_nome = uploaded_file.name.replace(".txt", "_CONVERTIDO.txt")
                        zipf.writestr(novo_nome, resultado)
                        total_linhas += total
                        total_subs += subs
                        log.append(f"✅ {uploaded_file.name}: {subs} substituições em {total} linhas.")
                        progress_bar.progress((idx + 1) / len(uploaded_files))

                buffer_zip.seek(0)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                nome_zip = f"ficheiros_convertidos_{ts}.zip"

                st.sidebar.download_button(
                    "📦 Descarregar ZIP Convertido",
                    data=buffer_zip,
                    file_name=nome_zip,
                    mime="application/zip"
                )

                st.info(f"📊 Total de linhas processadas: {total_linhas:,}")
                st.success(f"🔁 Substituições efetuadas: {total_subs:,}")

            # Exibir log final
            st.subheader("📋 Relatório de Operações:")
            for linha in log:
                st.write(linha)
