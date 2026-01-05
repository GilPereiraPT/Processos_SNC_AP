# -*- coding: utf-8 -*-

import streamlit as st
import pandas as pd
import zipfile
import io
import matplotlib.pyplot as plt
from collections import Counter
from datetime import datetime
import time

# --- Configurações Iniciais ---
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

# --- Funções Auxiliares ---
def ler_csv(f):
    return pd.read_csv(
        f, sep=';', header=9, names=CABECALHOS,
        encoding='ISO-8859-1', dtype=str, low_memory=False
    )

def ler_ficheiro(uploaded_file):
    if uploaded_file.name.endswith('.zip'):
        with zipfile.ZipFile(uploaded_file) as zip_ref:
            filenames = zip_ref.namelist()
            csv_files = [f for f in filenames if f.lower().endswith('.csv') and not f.startswith('__MACOSX')]
            if csv_files:
                with zip_ref.open(csv_files[0]) as f:
                    return ler_csv(f)
            else:
                raise ValueError('Nenhum ficheiro CSV encontrado no ZIP!')
    else:
        uploaded_file.seek(0)
        return ler_csv(uploaded_file)

def limpar(x):
    return str(x).strip().lstrip("'") if pd.notna(x) else ''

def extrair_rubrica(conta: str) -> str:
    partes = str(conta).split('.')
    return '.'.join(partes[1:]) if len(partes) > 1 else ''

def validar_linha(row, ORG_POR_FONTE, PROGRAMA_OBRIGATORIO, ORG_1, ORG_2):
    erros = []
    rd = row['R/D_clean']
    fonte = row['Fonte Finan._clean']
    org = row['Cl. Orgânica_clean']
    programa = row['Programa_clean']
    medida = row['Medida_clean']
    projeto = row['Projeto_clean']
    atividade = row['Atividade_clean']
    funcional = row['Cl. Funcional_clean']
    entidade = row['Entidade_clean']
    tipo = row['Tipo_clean']

    if not fonte:
        erros.append('Fonte de Finan. não preenchida')
    elif fonte in ORG_POR_FONTE and org != ORG_POR_FONTE[fonte]:
        erros.append(f"Cl. Orgânica deve ser {ORG_POR_FONTE[fonte]} para fonte {fonte}")

    if rd == 'R':
        if fonte == '511' and entidade not in ['9999999', '971010']:
            erros.append('Se R/D = R e Fonte Finan. = 511, então Entidade deve ser 9999999 ou 971010')

        if entidade == '971010':
            if '07.02.05.01.78' in str(row['Conta']):
                if fonte != '511':
                    erros.append('Se Entidade = 971010 e Conta contém 07.02.05.01.78, então Fonte Finan. deve ser 511')
            elif medida == '102':
                if fonte != '483':
                    erros.append('Se Entidade = 971010 e Medida = 102, então Fonte Finan. deve ser 483')
            else:
                if fonte != '513':
                    erros.append('Se Entidade = 971010 e não se aplicam as exceções, então Fonte Finan. deve ser 513')

        if entidade == '971007' and fonte != '541':
            erros.append('Fonte Finan. deve ser 541 para entidade 971007')

        if programa != PROGRAMA_OBRIGATORIO:
            erros.append(f"Programa deve ser '{PROGRAMA_OBRIGATORIO}'")

        if fonte not in ['483', '31H', '488'] and medida != '022':
            erros.append('Medida deve ser "022" exceto para fontes 483, 31H ou 488')

        if tipo.upper() == 'PG' and fonte != '513':
            erros.append('Fonte Finan. deve ser 513 quando R/D = R e Tipo = PG')

    elif rd == 'D':
        if fonte not in ['483', '31H', '488'] and medida != '022':
            erros.append('Medida deve ser "022" exceto para fontes 483, 31H ou 488')

        if org == ORG_1:
            if projeto and atividade != '000':
                erros.append('Se o Projeto estiver preenchido, a Atividade deve ser 000')
            elif not projeto and atividade != '130':
                erros.append('Se o Projeto estiver vazio, a Atividade deve ser 130')

        if org == ORG_2:
            if atividade != '000' or not projeto:
                erros.append('Atividade deve ser 000 e Projeto preenchido')

        if funcional != '0730':
            erros.append("Cl. Funcional deve ser '0730'")

        if tipo == 'CO' and fonte != '511':
            erros.append('Se R/D = D e Tipo = CO, Fonte Finan. tem de ser 511')

    return '; '.join(erros) if erros else 'Sem erros'

def validar_documentos_co(df_input):
    erros = []
    df_co = df_input[df_input['Tipo_clean'] == 'CO']

    for docid, grp in df_co.groupby('DOCID'):
        debs = grp[grp['Conta'].str.startswith(('0281', '0282'))]
        creds = grp[grp['Conta'].str.startswith('0272')]
        rubs = {extrair_rubrica(c) for c in debs['Conta']}
        for idx, ln in creds.iterrows():
            rub = extrair_rubrica(ln['Conta'])
            if rub not in rubs:
                erros.append((idx, f"DOCID {docid}: sem débito para rubrica {rub}"))
    return erros

# --- App Streamlit ---
st.set_page_config(page_title='Validador SNC-AP Turbo 2026.7', layout='wide')
st.title('🛡️ Validador de Lançamentos SNC-AP Turbo Finalíssimo 2026.7')

st.sidebar.title('Menu de Controlo')
uploaded = st.sidebar.file_uploader('📂 Carrega um ficheiro CSV ou ZIP', type=['csv', 'zip'])

if uploaded:
    try:
        # Carregamento do ficheiro
        df_original = ler_ficheiro(uploaded)
        st.success(f"Ficheiro '{uploaded.name}' carregado com sucesso!")
        
        with st.expander("👀 Pré-visualização dos dados (Top 10)"):
            st.dataframe(df_original.head(10), use_container_width=True)

        # Seleção do Ano com Chave de Estado (Session State)
        ano_validacao = st.sidebar.selectbox(
            '📅 Selecione o ano para validação',
            [2025, 2026, 2027],
            index=None,
            placeholder='Escolha o ano...',
            key='ano_regra'
        )

        # Botão de Validação
        if st.sidebar.button('🚀 Iniciar Validação'):
            if ano_validacao is None:
                st.sidebar.error("⚠️ Seleção obrigatória: Escolha o ano antes de validar.")
            else:
                # Início do processo
                df = df_original.copy()
                df = df[df['Conta'] != 'Conta'] # Remove cabeçalhos repetidos se houver
                df.reset_index(drop=True, inplace=True)

                # --- Configuração de Regras por Ano ---
                # Definimos explicitamente cada cenário para evitar que o "else" assuma valores errados
                if ano_validacao >= 2026:
                    st.info(f'⚙️ Configuração: Regras de {ano_validacao} ativadas (Prog: 015).')
                    ORG_POR_FONTE = {
                        '368': '128904000', '31H': '128904000', '483': '128904000', '488': '128904000',
                        '511': '121904000', '513': '121904000', '521': '121904000', '522': '121904000',
                        '541': '121904000', '724': '121904000', '721': '121904000',
                        '361': '128904000', '415': '128904000'
                    }
                    PROGRAMA_OBRIGATORIO = '015'
                    ORG_1, ORG_2 = '121904000', '128904000'
                
                else: # Ano 2025 ou inferior
                    st.info(f'⚙️ Configuração: Regras de 2025 ativadas (Prog: 011).')
                    ORG_POR_FONTE = {
                        '368': '108904000', '31H': '108904000', '483': '108904000', '488': '108904000',
                        '511': '101904000', '513': '101904000', '521': '101904000', '522': '101904000',
                        '541': '101904000', '724': '101904000', '721': '101904000',
                        '361': '108904000', '415': '108904000'
                    }
                    PROGRAMA_OBRIGATORIO = '011'
                    ORG_1, ORG_2 = '101904000', '108904000'

                # --- Processamento ---
                barra_progresso = st.progress(0, text='A processar...')
                tempo_inicio = time.time()

                # Fase 1: Limpeza
                barra_progresso.progress(20, text='Limpando colunas...')
                for col in COLUNAS_A_PRE_LIMPAR:
                    if col in df.columns:
                        df[f'{col}_clean'] = df[col].apply(limpar)
                    else:
                        df[f'{col}_clean'] = ''
                
                # Fase 2: Validação de Linhas
                barra_progresso.progress(50, text='Validando regras de negócio...')
                df['Erro'] = df.apply(
                    lambda row: validar_linha(row, ORG_POR_FONTE, PROGRAMA_OBRIGATORIO, ORG_1, ORG_2), axis=1
                )

                # Fase 3: Validação de Documentos CO
                barra_progresso.progress(80, text='Verificando integridade CO...')
                co_erros = validar_documentos_co(df)
                for idx, msg in co_erros:
                    if idx in df.index:
                        if df.at[idx, 'Erro'] == 'Sem erros':
                            df.at[idx, 'Erro'] = msg
                        else:
                            df.at[idx, 'Erro'] += f'; {msg}'

                barra_progresso.progress(100, text='Concluído!')
                st.success(f"✅ Validação terminada em {time.time() - tempo_inicio:.2f} segundos.")

                # --- Resultados ---
                df_final = df.copy()
                df_final['Ano_Regra_Aplicada'] = ano_validacao

                col1, col2 = st.columns(2)
                
                with col1:
                    st.metric("Total Linhas", len(df))
                with col2:
                    linhas_com_erro = len(df[df['Erro'] != 'Sem erros'])
                    st.metric("Linhas com Erro", linhas_com_erro, delta=linhas_com_erro, delta_color="inverse")

                with st.expander("📊 Relatório Detalhado de Erros"):
                    resumo = Counter()
                    for e in df['Erro']:
                        if e != 'Sem erros':
                            for sub_e in e.split('; '):
                                resumo[sub_e] += 1
                    
                    if resumo:
                        resumo_df = pd.DataFrame(resumo.most_common(), columns=['Tipo de Erro', 'Frequência'])
                        st.table(resumo_df)
                        
                        # Gráfico
                        fig, ax = plt.subplots()
                        resumo_df.sort_values(by='Frequência').plot(kind='barh', x='Tipo de Erro', y='Frequência', ax=ax, color='salmon')
                        plt.tight_layout()
                        st.pyplot(fig)
                    else:
                        st.balloons()
                        st.success("Fantástico! Não foram encontrados erros.")

                # Download
                buffer = io.BytesIO()
                df_final.to_csv(buffer, index=False, sep=';', encoding='utf-8-sig')
                buffer.seek(0)
                
                st.sidebar.download_button(
                    label="⬇️ Descarregar Resultados (CSV)",
                    data=buffer,
                    file_name=f"validacao_{ano_validacao}_{datetime.now().strftime('%H%M%S')}.csv",
                    mime="text/csv"
                )

    except Exception as e:
        st.error(f"Ocorreu um erro crítico: {e}")

else:
    st.info("👈 Por favor, carrega o ficheiro CSV ou ZIP no menu lateral para começar.")
