import streamlit as st
import pandas as pd
from collections import defaultdict, Counter
from datetime import datetime
import io

# --- Configurações iniciais ---
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
    '541': '101904000', '724': '101904000',
}

st.set_page_config(page_title="Validador SNC-AP", layout="wide")
st.title("🛡️ Validador de Lançamentos SNC-AP")
st.markdown(
    "Carrega um **ficheiro CSV** gerado pelo SNC-AP para validar regras de fonte, rubrica, DOCID, etc.  \n"
    "Depois gera um Excel com a coluna `Erro` indicando, para cada linha, os erros encontrados ou 'Sem erros'."
)

uploaded = st.file_uploader(
    "Selecione um ficheiro CSV", type="csv", accept_multiple_files=False
)

# Funções de validação idênticas ao script local

def extrair_rubrica(conta):
    partes = str(conta).split('.')
    return '.'.join(partes[1:]) if len(partes) > 1 else ''


def validar_linha(idx, row):
    erros = []
    rd = str(row['R/D']).strip()
    entidade = str(row['Entidade']).strip()
    fonte = str(row['Fonte Finan.']).strip()
    org = str(row['Cl. Orgânica']).strip()
    programa = str(row['Programa']).strip()
    medida = str(row['Medida']).strip()
    projeto = row['Projeto']
    atividade = str(row['Atividade']).strip()
    funcional = str(row['Cl. Funcional']).strip()

    if not fonte:
        erros.append("Fonte de Financiamento não preenchida")
    elif fonte in ORG_POR_FONTE and org != ORG_POR_FONTE[fonte]:
        erros.append(f"Cl. Orgânica deve ser {ORG_POR_FONTE[fonte]} para fonte {fonte}, mas está {org}")

    if rd == 'R':
        if entidade == '971010' and fonte != '511':
            erros.append("Fonte Finan. deve ser 511 para entidade 971010")
        if programa != "'011":
            erros.append("Programa deve ser '011")
        if fonte not in ['483','31H','488'] and medida != "'022":
            erros.append("Medida deve ser '022 exceto para fontes 483, 31H ou 488")
        if entidade == '971007' and fonte != '541':
            erros.append("Fonte Finan. deve ser 541 para entidade 971007")
    elif rd == 'D':
        if fonte not in ['483','31H','488'] and medida != "'022":
            erros.append("Medida deve ser '022 exceto para fontes 483, 31H ou 488")
        if org == '101904000':
            if pd.notna(projeto) and str(projeto).strip():
                if atividade != '000':
                    erros.append("Se o Projeto estiver preenchido, a Atividade deve ser 000")
            else:
                if atividade != '130':
                    erros.append("Se o Projeto estiver vazio, a Atividade deve ser 130")
        if org == '108904000':
            if atividade != '000' or (not pd.notna(projeto) or not str(projeto).strip()):
                erros.append("Atividade deve ser 000 e Projeto preenchido")
        if funcional != "'0730":
            erros.append("Cl. Funcional deve ser '0730")

    return [(idx, e) for e in erros]


def validar_documentos_co(df):
    erros = []
    df_co = df[df['Tipo'] == 'CO']
    for docid, grupo in df_co.groupby('DOCID'):
        debitos = grupo[grupo['Conta'].astype(str).str.startswith(('0281','0282'))]
        creditos = grupo[grupo['Conta'].astype(str).str.startswith('0272')]
        rubricas_d = {extrair_rubrica(c) for c in debitos['Conta']}
        for idx, linha in creditos.iterrows():
            if extrair_rubrica(linha['Conta']) not in rubricas_d:
                erros.append((idx, f'DOCID {docid}: falta débito correspondente à rubrica {extrair_rubrica(linha['Conta'])}'))
    return erros

# Processamento principal
if uploaded:
    # Leitura com cabeçalhos corretamente posicionados
    content = uploaded.getvalue().decode('ISO-8859-1')
    df = pd.read_csv(
        io.StringIO(content),
        sep=';',
        header=9,
        names=CABECALHOS,
        dtype=str,
        low_memory=False
    )
    # Eliminar linhas duplicadas de cabeçalho
    df = df[df['Conta'] != 'Conta']
    # Remover "Saldo Inicial"
    df = df[~df['Data Contab.'].astype(str).str.contains('Saldo Inicial', na=False)]

    n = len(df)
    st.subheader(f"Processando {uploaded.name} ({n} linhas)")
    progresso = st.progress(0)

    erros_por_linha = defaultdict(list)
    resumo = Counter()

    # Validação linha a linha
    for idx, row in df.iterrows():
        linha_erros = validar_linha(idx, row)
        for i, msg in linha_erros:
            erros_por_linha[i].append(msg)
            resumo[msg] += 1
        progresso.progress((idx+1)/n)

    # Validação documentos CO
    for idx, msg in validar_documentos_co(df):
        erros_por_linha[idx].append(msg)
        resumo[msg] += 1

    # Construir coluna 'Erro'
    df['Erro'] = ["; ".join(erros_por_linha[i]) if erros_por_linha[i] else 'Sem erros' for i in df.index]

    # Mostrar tabela e download
    st.dataframe(df)
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False)
    buffer.seek(0)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    fname = f"{uploaded.name.rstrip('.csv')}_output_{ts}.xlsx"
    st.download_button(
        "⬇️ Descarregar Excel de output",
        data=buffer,
        file_name=fname,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # Resumo
    if resumo:
        st.subheader('📊 Resumo de Erros')
        df_resumo = pd.DataFrame(resumo.most_common(), columns=['Regra','Ocorrências'])
        st.table(df_resumo)
else:
    st.info('Primeiro, carrega um ficheiro CSV acima.')
