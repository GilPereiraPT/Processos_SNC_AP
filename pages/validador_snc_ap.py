# -*- coding: utf-8 -*-

import streamlit as st
import pandas as pd
import zipfile
import io
import matplotlib.pyplot as plt
from collections import Counter
from datetime import datetime
import time

# --- CONFIGURAÇÕES TÉCNICAS (ESTÁTICAS) ---
CABECALHOS = [
    'Conta', 'Data Contab.', 'Data Doc.', 'Nº Lancamento', 'Entidade', 'Designação',
    'Tipo', 'Nº Documento', 'Serie', 'Ano', 'Debito', 'Credito', 'Acumulado',
    'D/C', 'R/D', 'Observações', 'Doc. Regul', 'Cl. Funcional', 'Fonte Finan.',
    'Programa', 'Medida', 'Projeto', 'Regionalização', 'Atividade', 'Natureza',
    'Cl. Orgânica', 'Mes', 'Departamento', 'DOCID', 'Ordem', 'Subtipo', 'NIF',
    'Código Parceira', 'Código Intragrupo', 'Utiliz Criação', 'Utiliz Ult Alteração', 'Data Ult Alteração'
]

COLUNAS_A_PRE_LIMPAR = [
    'R/D', 'Fonte Finan.', 'Cl. Orgânica', 'Programa', 'Medida',
    'Projeto', 'Atividade', 'Cl. Funcional', 'Entidade', 'Tipo'
]

# --- FUNÇÕES DE APOIO ---
def limpar(x):
    return str(x).strip().lstrip("'") if pd.notna(x) else ''

def extrair_rubrica(conta: str) -> str:
    partes = str(conta).split('.')
    return '.'.join(partes[1:]) if len(partes) > 1 else ''

def ler_csv(f):
    return pd.read_csv(
        f, sep=';', header=9, names=CABECALHOS,
        encoding='ISO-8859-1', dtype=str, low_memory=False
    )

def ler_ficheiro(uploaded_file):
    if uploaded_file.name.endswith('.zip'):
        with zipfile.ZipFile(uploaded_file) as zip_ref:
            csv_files = [f for f in zip_ref.namelist() if f.lower().endswith('.csv') and not f.startswith('__MACOSX')]
            if not csv_files: raise ValueError('Sem CSV no ZIP')
            with zip_ref.open(csv_files[0]) as f: return ler_csv(f)
    return ler_csv(uploaded_file)

def validar_linha(row, ORG_POR_FONTE, PROG_OBJ, ORG_1, ORG_2):
    erros = []
    rd, fonte, org = row['R/D_clean'], row['Fonte Finan._clean'], row['Cl. Orgânica_clean']
    prog, med, proj = row['Programa_clean'], row['Medida_clean'], row['Projeto_clean']
    ativ, func, ent, tipo = row['Atividade_clean'], row['Cl. Funcional_clean'], row['Entidade_clean'], row['Tipo_clean']

    # 1. Validação de Fonte vs Orgânica
    if not fonte:
        erros.append('Fonte de Finan. vazia')
    elif fonte in ORG_POR_FONTE and org != ORG_POR_FONTE[fonte]:
        erros.append(f"Orgânica incorreta (deve ser {ORG_POR_FONTE[fonte]})")

    # 2. Regras específicas R/D
    if rd == 'R':
        if prog != PROG_OBJ: erros.append(f"Programa deve ser {PROG_OBJ}")
        if fonte not in ['483', '31H', '488'] and med != '022': erros.append('Medida deve ser 022')
    elif rd == 'D':
        if func != '0730': erros.append("Funcional deve ser 0730")
        if org == ORG_1:
            if proj and ativ != '000': erros.append('Com Projeto, Atividade deve ser 000')
            elif not proj and ativ != '130': erros.append('Sem Projeto, Atividade deve ser 130')
        if org == ORG_2 and (ativ != '000' or not proj):
            erros.append('Atividade 000 e Projeto obrigatório')

    return '; '.join(erros) if erros else 'Sem erros'

# --- INTERFACE STREAMLIT ---
st.set_page_config(page_title="Validador SNC-AP", layout="wide")
st.title("🛡️ Validador de Lançamentos SNC-AP")

# --- MENU LATERAL (SEMPRE VISÍVEL) ---
st.sidebar.header("Configurações")

# O seletor de ano fica aqui, fora de qualquer IF, para estar sempre visível
ano_selecionado = st.sidebar.selectbox(
    "1. Escolha o Ano de Validação",
    options=[2026, 2025],
    index=0,
    help="Define as regras de validação (Programa e Orgânicas)"
)

uploaded_file = st.sidebar.file_uploader("2. Carregue o ficheiro (CSV/ZIP)", type=['csv', 'zip'])

# --- DEFINIÇÃO DE REGRAS (DINÂMICA) ---
if ano_selecionado == 2026:
    st.sidebar.success("✅ Regras de 2026 Ativas")
    PROGRAMA_OBRIGATORIO = '015'
    ORG_1, ORG_2 = '121904000', '128904000'
    DIP_FONTES = {
        '368': '128904000', '31H': '128904000', '483': '128904000', '488': '128904000',
        '511': '121904000', '513': '121904000', '521': '121904000', '522': '121904000',
        '541': '121904000', '724': '121904000', '721': '121904000', '361': '128904000', '415': '128904000'
    }
else:
    st.sidebar.warning("⚠️ Regras de 2025 Ativas")
    PROGRAMA_OBRIGATORIO = '011'
    ORG_1, ORG_2 = '101904000', '108904000'
    DIP_FONTES = {
        '368': '108904000', '31H': '108904000', '483': '108904000', '488': '108904000',
        '511': '101904000', '513': '101904000', '521': '101904000', '522': '101904000',
        '541': '101904000', '724': '101904000', '721': '101904000', '361': '108904000', '415': '108904000'
    }

# --- EXECUÇÃO ---
if uploaded_file:
    try:
        df = ler_ficheiro(uploaded_file)
        st.info(f"Ficheiro carregado: {uploaded_file.name}")

        if st.sidebar.button("🚀 VALIDAR AGORA"):
            # Limpeza
            for col in COLUNAS_A_PRE_LIMPAR:
                df[f'{col}_clean'] = df[col].apply(limpar) if col in df.columns else ''

            # Validação
            df['Erro'] = df.apply(
                lambda r: validar_linha(r, DIP_FONTES, PROGRAMA_OBRIGATORIO, ORG_1, ORG_2), axis=1
            )

            # Mostrar resultados
            erros_count = len(df[df['Erro'] != 'Sem erros'])
            if erros_count > 0:
                st.error(f"Encontrados {erros_count} lançamentos com erros.")
            else:
                st.success("Tudo em conformidade!")

            st.dataframe(df)

            # Download
            csv_output = df.to_csv(index=False, sep=';', encoding='utf-8-sig').encode('utf-8-sig')
            st.download_button("Baixar Resultados", csv_output, "validacao.csv", "text/csv")

    except Exception as e:
        st.error(f"Erro ao processar: {e}")
else:
    st.info("Aguardando ficheiro... Use o menu à esquerda.")
