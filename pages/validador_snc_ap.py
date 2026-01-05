# -*- coding: utf-8 -*-

import streamlit as st
import pandas as pd
import zipfile
import io
from collections import Counter
from datetime import datetime

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Validador SNC-AP 2026", layout="wide")

# --- 1. SELEÇÃO DO ANO (FORA DE QUALQUER CONDICIONAL) ---
st.sidebar.header("⚙️ Configuração Crítica")
ano_selecionado = st.sidebar.selectbox(
    "Selecione o Ano de Validação",
    options=[2026, 2025],
    index=0,
    help="Define se usamos as regras de 2026 (Prog 015) ou 2025 (Prog 011)"
)

# --- 2. DEFINIÇÃO DAS REGRAS COM BASE NO ANO ---
if ano_selecionado == 2026:
    ST_COLOR = "blue"
    PROGRAMA_OBJ = '015'
    ORG_1, ORG_2 = '121904000', '128904000'
    FONTES_MAP = {
        '368': '128904000', '31H': '128904000', '483': '128904000', '488': '128904000',
        '511': '121904000', '513': '121904000', '521': '121904000', '522': '121904000',
        '541': '121904000', '724': '121904000', '721': '121904000', '361': '128904000', '415': '128904000'
    }
else:
    ST_COLOR = "orange"
    PROGRAMA_OBJ = '011'
    ORG_1, ORG_2 = '101904000', '108904000'
    FONTES_MAP = {
        '368': '108904000', '31H': '108904000', '483': '108904000', '488': '108904000',
        '511': '101904000', '513': '101904000', '521': '101904000', '522': '101904000',
        '541': '101904000', '724': '101904000', '721': '101904000', '361': '108904000', '415': '108904000'
    }

st.title(f"🛡️ Validador SNC-AP - Modo {ano_selecionado}")
st.sidebar.markdown(f"**Regras Ativas:** Programa {PROGRAMA_OBJ}")

# --- 3. FUNÇÕES DE LIMPEZA (CORRIGIDAS PARA O TEU CSV) ---
def limpar_valor(x):
    """Remove aspas simples, espaços e garante que é string"""
    if pd.isna(x): return ""
    return str(x).replace("'", "").strip()

def validar_linha(row):
    erros = []
    # Captura valores limpos
    f = limpar_valor(row.get('Fonte Finan.', ''))
    o = limpar_valor(row.get('Cl. Orgânica', ''))
    p = limpar_valor(row.get(' Programa', '')) # Espaço antes de Programa no teu CSV
    rd = limpar_valor(row.get('R/D', ''))
    func = limpar_valor(row.get('Cl. Funcional', ''))
    
    # Validação Programa
    if p != PROGRAMA_OBJ:
        erros.append(f"Programa incorreto: '{p}' (esperado {PROGRAMA_OBJ})")
    
    # Validação Fonte vs Orgânica
    if f in FONTES_MAP and o != FONTES_MAP[f]:
        erros.append(f"Orgânica {o} não condiz com Fonte {f}")
        
    # Validação Funcional (Despesa)
    if rd == 'D' and func != '0730':
        erros.append(f"Funcional {func} deve ser 0730 na Despesa")

    return "; ".join(erros) if erros else "Sem erros"

# --- 4. CARREGAMENTO E PROCESSAMENTO ---
uploaded_file = st.sidebar.file_uploader("Suba o ficheiro CSV", type=['csv'])

if uploaded_file:
    try:
        # Lemos a partir da linha 9 como o teu ficheiro original pede
        df = pd.read_csv(uploaded_file, sep=';', header=9, encoding='ISO-8859-1', dtype=str)
        
        if st.sidebar.button("🚀 Executar Validação"):
            with st.spinner("A analisar lançamentos..."):
                # Aplica a validação
                df['Resultado Validação'] = df.apply(validar_linha, axis=1)
                
                # Filtra apenas erros para o resumo
                df_erros = df[df['Resultado Validação'] != "Sem erros"]
                
                # Métricas
                c1, c2 = st.columns(2)
                c1.metric("Total de Linhas", len(df))
                c2.metric("Linhas com Erros", len(df_erros), delta=len(df_erros), delta_color="inverse")
                
                st.subheader("Resultados")
                st.dataframe(df, use_container_width=True)
                
                # Download
                output = io.BytesIO()
                df.to_csv(output, index=False, sep=';', encoding='utf-8-sig')
                st.download_button(
                    label="⬇️ Descarregar Relatório de Erros",
                    data=output.getvalue(),
                    file_name=f"validacao_{ano_selecionado}.csv",
                    mime="text/csv"
                )
    except Exception as e:
        st.error(f"Erro ao ler o ficheiro: {e}")
else:
    st.info("Aguardando ficheiro CSV no menu lateral.")
