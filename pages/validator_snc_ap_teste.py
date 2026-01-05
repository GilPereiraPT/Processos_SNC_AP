# -*- coding: utf-8 -*-

import streamlit as st
import pandas as pd
import zipfile
import io

# --- Configurações ---
st.set_page_config(page_title="Teste Seletor & Deteção de Ano", layout="wide")
st.title("🧩 Mini App de Teste — Deteção Automática + Seletor de Ano")

# --- Funções auxiliares ---
def ler_csv(f):
    return pd.read_csv(
        f, sep=';', header=9, dtype=str, encoding='ISO-8859-1', low_memory=False
    )

def ler_ficheiro(uploaded_file):
    if uploaded_file.name.endswith(".zip"):
        with zipfile.ZipFile(uploaded_file) as zip_ref:
            csv_files = [n for n in zip_ref.namelist() if n.lower().endswith(".csv")]
            if not csv_files:
                raise ValueError("Nenhum CSV encontrado no ZIP.")
            with zip_ref.open(csv_files[0]) as f:
                return ler_csv(f)
    else:
        uploaded_file.seek(0)
        return ler_csv(uploaded_file)

def detectar_ano(df):
    try:
        anos = (
            df["Ano"]
            .dropna()
            .astype(str)
            .str.extract(r"(20\d{2})")[0]
            .dropna()
            .astype(int)
            .tolist()
        )
        if anos:
            return max(anos)
    except Exception:
        pass
    return None

# --- Interface ---
st.sidebar.header("Menu")
uploaded = st.sidebar.file_uploader("📂 Carrega um ficheiro CSV ou ZIP", type=["csv", "zip"])

ano_detectado = None
df_original = None

if uploaded:
    try:
        df_original = ler_ficheiro(uploaded)
        ano_detectado = detectar_ano(df_original)
        if ano_detectado:
            st.success(f"✅ Ano detetado automaticamente: {ano_detectado}")
        else:
            st.warning("⚠️ Nenhum ano detetado — selecione manualmente.")
        st.dataframe(df_original.head(10), use_container_width=True)
    except Exception as e:
        st.error(f"Erro ao ler o ficheiro: {e}")

# ✅ Selectbox sempre visível
ano_validacao = st.sidebar.selectbox(
    "📅 Selecione o ano para validação",
    [2025, 2026],
    index=[2025, 2026].index(ano_detectado) if ano_detectado in [2025, 2026] else 0,
)

# --- Resultado ---
st.divider()
st.header("🔍 Resultado do Teste")

if uploaded:
    st.write(f"📁 Ficheiro carregado: `{uploaded.name}`")
else:
    st.info("👈 Carregue um ficheiro CSV ou ZIP para começar.")

st.write(f"📅 Ano detetado automaticamente: {ano_detectado}")
st.write(f"🧭 Ano selecionado manualmente: {ano_validacao}")
st.success("✅ Se o seletor aparece na barra lateral, está tudo a funcionar corretamente!")
