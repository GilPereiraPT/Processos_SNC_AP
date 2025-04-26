import streamlit as st
import pandas as pd
from datetime import datetime
from collections import defaultdict, Counter
import io

# Cabeçalhos esperados
CABECALHOS = [
    'Conta', 'Data Contab.', 'Data Doc.', 'Nº Lancamento', 'Entidade', 'Designação',
    'Tipo', 'Nº Documento', 'Serie', 'Ano', 'Debito', 'Credito', 'Acumulado',
    'D/C', 'R/D', 'Observações', 'Doc. Regul', 'Cl. Funcional', 'Fonte Finan.',
    'Programa', 'Medida', 'Projeto', 'Regionalização', 'Atividade', 'Natureza',
    'Cl. Orgânica', 'Mes', 'Departamento', 'DOCID', 'Ordem', 'Subtipo', 'NIF',
    'Código Parceira', 'Código Intragrupo', 'Utiliz Criação',
    'Utiliz Ult Alteração', 'Data Ult Alteração'
]

# Mapeamento Fonte → Cl. Orgânica esperado\NORG_POR_FONTE = {
    '368': '108904000', '31H': '108904000', '483': '108904000', '488': '108904000',
    '511': '101904000', '513': '101904000', '521': '101904000', '522': '101904000',
    '541': '101904000', '724': '101904000',
}

# Configurar Streamlit
st.set_page_config(page_title="Validador SNC-AP", layout="wide")
st.title("🛡️ Validador SNC-AP")
st.markdown(
    "Carrega um **ficheiro CSV** gerado pelo SNC-AP e valida as mesmas regras do teu script local; no fim, descarrega um Excel com a coluna `Erro`."
)

uploaded = st.file_uploader("Selecione um ficheiro CSV", type="csv")

# Função para normalizar campos de texto (remover espaços e caracteres estranhos)
def normalize(text, only_digits=False):
    txt = str(text).strip()
    # remove espaços duros e outros
    txt = txt.replace("\xa0", "").replace(" ", "")
    if only_digits:
        return ''.join(filter(str.isdigit, txt))
    else:
        return ''.join(filter(str.isalnum, txt))

# Funções de validação

def extrair_rubrica(conta):
    partes = str(conta).split('.')
    return '.'.join(partes[1:]) if len(partes) > 1 else ''


def validar_linha(idx, row):
    erros = []
    rd = normalize(row['R/D'])
    fonte = normalize(row['Fonte Finan.'])
    org = normalize(row['Cl. Orgânica'], only_digits=True)
    programa = normalize(row['Programa'])
    medida = normalize(row['Medida'])
    projeto = row['Projeto']
    atividade = normalize(row['Atividade'])
    funcional = normalize(row['Cl. Funcional'])
    entidade = normalize(row['Entidade'], only_digits=True)

    # 1) Fonte vazia
    if not fonte:
        erros.append("Fonte de Financiamento não preenchida")
    # 2) Cl. Orgânica conforme fonte
    elif fonte in ORG_POR_FONTE and org != ORG_POR_FONTE[fonte]:
        erros.append(f"Cl. Orgânica deve ser {ORG_POR_FONTE[fonte]} para fonte {fonte}, mas está {org}")

    # 3) Regras R ou D
    if rd == 'R':
        if entidade == '971010' and fonte != '511':
            erros.append("Fonte Finan. deve ser 511 para entidade 971010")
        if programa != "011":
            erros.append("Programa deve ser '011'")
        if fonte not in ['483','31H','488'] and medida != '022':
            erros.append("Medida deve ser '022' (exceto fontes 483,31H,488)")
        if entidade == '971007' and fonte != '541':
            erros.append("Fonte Finan. deve ser 541 para entidade 971007")
    elif rd == 'D':
        if fonte not in ['483','31H','488'] and medida != '022':
            erros.append("Medida deve ser '022' (exceto fontes 483,31H,488)")
        if org == '101904000':
            if pd.notna(projeto) and str(projeto).strip():
                if atividade != '000':
                    erros.append("Se o Projeto estiver preenchido, a Atividade deve ser 000")
            else:
                if atividade != '130':
                    erros.append("Se o Projeto estiver vazio, a Atividade deve ser 130")
        if org == '108904000':
            if atividade != '000' or not(pd.notna(projeto) and str(projeto).strip()):
                erros.append("Atividade deve ser 000 e Projeto preenchido")
        if funcional != '0730':
            erros.append("Cl. Funcional deve ser '0730'")
    return erros


def validar_documentos_co(df):
    erros = []
    df_co = df[df['Tipo'] == 'CO']
    for docid, grupo in df_co.groupby('DOCID'):
        debs = grupo[grupo['Conta'].astype(str).str.startswith(('0281','0282'))]
        creds = grupo[grupo['Conta'].astype(str).str.startswith('0272')]
        rubs = {extrair_rubrica(c) for c in debs['Conta']}
        for idx, ln in creds.iterrows():
            rub = extrair_rubrica(ln['Conta'])
            if rub not in rubs:
                erros.append((idx, f"DOCID {docid}: falta débito para rubrica {rub}"))
    return erros

# Processamento principal
if uploaded:
    content = uploaded.getvalue().decode('ISO-8859-1')
    df = pd.read_csv(io.StringIO(content), sep=';', header=9,
                     names=CABECALHOS, dtype=str, low_memory=False)
    # remover duplicado de cabeçalho
    df = df[df['Conta'] != 'Conta']
    # remover Saldo Inicial
    df = df[~df['Data Contab.'].str.contains('Saldo Inicial', na=False)]

    n = len(df)
    st.subheader(f"Processando {uploaded.name} ({n} linhas)")
    progresso = st.progress(0)

    erros_por_linha = defaultdict(list)
    resumo = Counter()

    for idx, row in df.iterrows():
        msgs = validar_linha(idx, row)
        if msgs:
            erros_por_linha[idx].extend(msgs)
            resumo.update(msgs)
        progresso.progress(min((idx+1)/n, 1.0))

    for idx, msg in validar_documentos_co(df):
        erros_por_linha[idx].append(msg)
        resumo.update([msg])

    # coluna de Erro
    df['Erro'] = df.index.map(lambda i: '; '.join(erros_por_linha.get(i, ['Sem erros'])))

    # exibir e download
    st.dataframe(df)
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False)
    buffer.seek(0)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    fname = f"{uploaded.name.rstrip('.csv')}_output_{ts}.xlsx"
    st.download_button("⬇️ Descarregar Excel", data=buffer, file_name=fname,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    if resumo:
        st.subheader('📊 Resumo de Erros')
        df_resumo = pd.DataFrame(resumo.most_common(), columns=['Regra','Ocorrências'])
        st.table(df_resumo)
else:
    st.info('Primeiro, carrega um ficheiro CSV acima.')
