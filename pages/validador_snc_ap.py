# -*- coding: utf-8 -*-

import streamlit as st
import pandas as pd
import zipfile
import io
import matplotlib.pyplot as plt
from collections import Counter
from datetime import datetime
import time # Adicionado para demonstração de tempo, pode ser removido

# --- Configurações Iniciais ---
CABECALHOS = [
    'Conta', 'Data Contab.', 'Data Doc.', 'Nº Lancamento', 'Entidade', 'Designação',
    'Tipo', 'Nº Documento', 'Serie', 'Ano', 'Debito', 'Credito', 'Acumulado',
    'D/C', 'R/D', 'Observações', 'Doc. Regul', 'Cl. Funcional', 'Fonte Finan.',
    'Programa', 'Medida', 'Projeto', 'Regionalização', 'Atividade', 'Natureza',
    'Cl. Orgânica', 'Mes', 'Departamento', 'DOCID', 'Ordem', 'Subtipo', 'NIF',
    'Código Parceira', 'Código Intragrupo', 'Utiliz Criação',
    'Utiliz Ult Alteração', 'Data Ult Alteração'
]

ORG_POR_FONTE = {
    '368': '108904000', '31H': '108904000', '483': '108904000', '488': '108904000',
    '511': '101904000', '513': '101904000', '521': '101904000', '522': '101904000',
    '541': '101904000', '724': '101904000', '721': '101904000', '361': '108904000',
    '415': '108904000'
}

# MELHORIA: Definir colunas que serão pré-limpas
COLUNAS_A_PRE_LIMPAR = [
    'R/D', 'Fonte Finan.', 'Cl. Orgânica', 'Programa', 'Medida',
    'Projeto', 'Atividade', 'Cl. Funcional', 'Entidade', 'Tipo'
]

# --- Funções Auxiliares ---
def ler_csv(f):
    return pd.read_csv(
        f, sep=';', header=9, names=CABECALHOS,
        encoding='ISO-8859-1', dtype=str, low_memory=False
    )

def ler_ficheiro(uploaded_file):
    if uploaded_file.name.endswith(".zip"):
        with zipfile.ZipFile(uploaded_file) as zip_ref:
            filenames = zip_ref.namelist()
            csv_files = [f_name for f_name in filenames if f_name.lower().endswith('.csv') and not f_name.startswith('__MACOSX')]
            if csv_files:
                with zip_ref.open(csv_files[0]) as f:
                    return ler_csv(f)
            else:
                raise ValueError("Nenhum ficheiro CSV encontrado no ZIP!")
    else:
        uploaded_file.seek(0)
        return ler_csv(uploaded_file)

def limpar(x):
    return str(x).strip().lstrip("'") if pd.notna(x) else ""

def extrair_rubrica(conta: str) -> str:
    partes = str(conta).split(".")
    return ".".join(partes[1:]) if len(partes) > 1 else ""

def validar_linha(row):
    erros = []
    rd        = row['R/D_clean']
    fonte     = row['Fonte Finan._clean']
    org       = row['Cl. Orgânica_clean']
    programa  = row['Programa_clean']
    medida    = row['Medida_clean']
    projeto   = row['Projeto_clean']
    atividade = row['Atividade_clean']
    funcional = row['Cl. Funcional_clean']
    entidade  = row['Entidade_clean']
    tipo      = row['Tipo_clean']

    if not fonte:
        erros.append("Fonte de Finan. não preenchida")
    elif fonte in ORG_POR_FONTE and org != ORG_POR_FONTE[fonte]:
        erros.append(f"Cl. Orgânica deve ser {ORG_POR_FONTE[fonte]} para fonte {fonte}")

    if rd == 'R':
        if entidade == '971010' and fonte != '511':
            erros.append("Fonte Finan. deve ser 511 para entidade 971010")
        if entidade == '971007' and fonte != '541':
            erros.append("Fonte Finan. deve ser 541 para entidade 971007")
        if programa != '011':
            erros.append("Programa deve ser '011'")
        if fonte not in ['483', '31H', '488'] and medida != '022':
            erros.append("Medida deve ser '022' exceto para fontes 483, 31H ou 488")
        if tipo.upper() == 'PG' and fonte != '513':
            erros.append("Fonte Finan. deve ser 513 quando R/D = R e Tipo = PG")

    elif rd == 'D':
        if fonte not in ['483', '31H', '488'] and medida != '022':
            erros.append("Medida deve ser '022' exceto para fontes 483, 31H ou 488")
        if org == '101904000':
            if projeto and atividade != '000':
                erros.append("Se o Projeto estiver preenchido, a Atividade deve ser 000")
            elif not projeto and atividade != '130':
                erros.append("Se o Projeto estiver vazio, a Atividade deve ser 130")
        if org == '108904000':
            if atividade != '000' or not projeto:
                erros.append("Atividade deve ser 000 e Projeto preenchido")
        if funcional != '0730':
            erros.append("Cl. Funcional deve ser '0730'")
        if tipo == 'CO' and fonte != '511':
            erros.append("Se R/D = D e Tipo = CO, Fonte Finan. tem de ser 511")

    return "; ".join(erros) if erros else "Sem erros"

def validar_documentos_co(df_input):
    erros = []
    df_co = df_input[df_input['Tipo_clean'] == 'CO']

    for docid, grp in df_co.groupby('DOCID'):
        debs = grp[grp['Conta'].str.startswith(('0281','0282'))]
        creds = grp[grp['Conta'].str.startswith('0272')]
        rubs = {extrair_rubrica(c) for c in debs['Conta']}
        for idx, ln in creds.iterrows():
            rub = extrair_rubrica(ln['Conta'])
            if rub not in rubs:
                erros.append((idx, f"DOCID {docid}: sem débito para rubrica {rub}"))
    return erros

# --- App Streamlit ---
st.set_page_config(page_title="Validador SNC-AP Turbo Finalíssimo", layout="wide")
st.title("🛡️ Validador de Lançamentos SNC-AP Turbo Finalíssimo")

st.sidebar.title("Menu")
uploaded = st.sidebar.file_uploader("Carrega um ficheiro CSV ou ZIP", type=["csv", "zip"])

if uploaded:
    try:
        df_original = ler_ficheiro(uploaded)
        df = df_original.copy()

        df = df[df['Conta'] != 'Conta']
        df = df[~df['Data Contab.'].astype(str).str.contains("Saldo Inicial", na=False)]
        df.reset_index(drop=True, inplace=True)

        st.info(f"Ficheiro '{uploaded.name}' carregado. Total de linhas a processar: {len(df)}")

        total_etapas = 3
        progresso_atual = 0
        barra_progresso = st.progress(0, text="A iniciar validação...")
        tempo_inicio_total = time.time()

        barra_progresso.progress(progresso_atual / total_etapas, text="Fase 1/3: A preparar dados (pré-limpeza)...")
        tempo_inicio_etapa = time.time()
        for col_original in COLUNAS_A_PRE_LIMPAR:
            if col_original in df.columns:
                df[f'{col_original}_clean'] = df[col_original].apply(limpar)
            else:
                df[f'{col_original}_clean'] = ""
                st.warning(f"Coluna '{col_original}' não encontrada no ficheiro. Será tratada como vazia para validação.")
        st.write(f"Tempo Fase 1 (Pré-limpeza): {time.time() - tempo_inicio_etapa:.2f}s")
        progresso_atual += 1

        barra_progresso.progress(progresso_atual / total_etapas, text="Fase 2/3: A validar lançamentos linha a linha...")
        tempo_inicio_etapa = time.time()
        df['Erro'] = df.apply(validar_linha, axis=1)
        st.write(f"Tempo Fase 2 (Validação de Linhas): {time.time() - tempo_inicio_etapa:.2f}s")
        progresso_atual += 1

        barra_progresso.progress(progresso_atual / total_etapas, text="Fase 3/3: A validar documentos CO...")
        tempo_inicio_etapa = time.time()
        co_erros = validar_documentos_co(df)
        for idx, msg in co_erros:
            if idx in df.index:
                if df.at[idx, 'Erro'] == "Sem erros":
                    df.at[idx, 'Erro'] = msg
                else:
                    df.at[idx, 'Erro'] += f"; {msg}"
            else:
                st.warning(f"Índice {idx} de erro CO não encontrado no DataFrame principal. O erro '{msg}' não foi atribuído.")
        st.write(f"Tempo Fase 3 (Validação CO e Consolidação): {time.time() - tempo_inicio_etapa:.2f}s")
        progresso_atual += 1
        barra_progresso.progress(progresso_atual / total_etapas, text="Validação concluída!")

        st.success(f"Validação concluída. Total de linhas: {len(df)}. Tempo total: {time.time() - tempo_inicio_total:.2f}s")

        df_para_mostrar = df.copy()
        colunas_a_remover_do_output = [f'{c}_clean' for c in COLUNAS_A_PRE_LIMPAR if f'{c}_clean' in df_para_mostrar.columns]
        if colunas_a_remover_do_output:
            df_para_mostrar.drop(columns=colunas_a_remover_do_output, inplace=True)

        with st.expander("🔍 Dados Validados"):
            st.dataframe(df_para_mostrar, use_container_width=True)

        with st.expander("📊 Resumo de Erros"):
            resumo = Counter()
            for erros_linha in df['Erro']:
                if erros_linha != "Sem erros":
                    for erro_msg in erros_linha.split("; "):
                        resumo[erro_msg] += 1

            if resumo:
                resumo_df = pd.DataFrame(resumo.most_common(), columns=["Regra", "Ocorrências"])
                st.table(resumo_df)
                altura_grafico = max(5, len(resumo_df) * 0.35)
                fig, ax = plt.subplots(figsize=(10, altura_grafico))
                resumo_df.sort_values(by='Ocorrências', ascending=True).plot(
                    kind="barh", x="Regra", y="Ocorrências", ax=ax, legend=False,
                    title="Ocorrências de Erros por Regra"
                )
                plt.tight_layout()
                st.pyplot(fig)
            else:
                st.info("🎉 Fantástico! Nenhum erro encontrado nas validações.")

        # --- Download ---
        st.info("DEBUG: A iniciar preparação para download do relatório CSV...")
        buffer = io.BytesIO()
        st.info("DEBUG: Buffer BytesIO criado.")

        # Usar df_para_mostrar para o CSV (sem colunas _clean)
        try:
            st.info(f"DEBUG: A gerar CSV com {len(df_para_mostrar)} linhas e {len(df_para_mostrar.columns)} colunas...")
            # Gerar CSV
            df_para_mostrar.to_csv(
                buffer,
                index=False,        # Não escrever o índice do DataFrame
                sep=';',            # Usar ponto e vírgula como separador
                encoding='utf-8-sig' # utf-8-sig ajuda o Excel a abrir o CSV corretamente com acentos
            )
            st.info("DEBUG: Ficheiro CSV gerado com sucesso no buffer.")
        except Exception as e_csv:
            st.error(f"ERRO CRÍTICO ao gerar o ficheiro CSV: {e_csv}")
            raise # Re-lança a excepção para parar e ver o erro nos logs do Streamlit

        buffer.seek(0)
        st.info("DEBUG: Buffer seek(0) executado.")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        nome_ficheiro_base = uploaded.name.split('.')[0].replace(' ', '_')
        # Alterar extensão para .csv
        nome_ficheiro_csv = f"{nome_ficheiro_base}_output_{ts}.csv"

        st.info(f"DEBUG: A preparar botão de download para '{nome_ficheiro_csv}'.")
        st.sidebar.download_button(
            "⬇️ Descarregar CSV com Erros", # Texto do botão atualizado
            data=buffer,
            file_name=nome_ficheiro_csv,
            mime="text/csv" # MIME type para CSV
        )
        st.info("DEBUG: Botão de download CSV adicionado à barra lateral.")

    except ValueError as ve:
        st.error(f"Erro de Validação: {ve}")
    except KeyError as ke:
        st.error(f"Erro de Processamento: Coluna não encontrada no ficheiro - {ke}. Verifique se o ficheiro CSV tem os cabeçalhos esperados.")
    except Exception as e:
        st.error(f"Ocorreu um erro inesperado durante o processamento: {e}")
        # Para debugging mais aprofundado, pode descomentar a linha abaixo para ver o traceback na UI
        # st.exception(e)
else:
    st.info("👈 Por favor, carregue um ficheiro CSV ou ZIP para começar.")
