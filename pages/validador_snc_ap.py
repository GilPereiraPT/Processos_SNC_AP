import streamlit as st
import pandas as pd
import io
from collections import defaultdict, Counter
from datetime import datetime

# --- Configurações ---
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
    '368': '108904000',
    '31H': '108904000',
    '483': '108904000',
    '488': '108904000',
    '511': '101904000',
    '513': '101904000',
    '521': '101904000',
    '522': '101904000',
    '541': '101904000',
    '724': '101904000',
}

st.set_page_config(page_title="Validador SNC-AP", layout="wide")
st.title("🛡️ Validador de Lançamentos SNC-AP")
st.markdown(
    "Carrega um **ficheiro CSV** gerado pelo SNC-AP para validar regras específicas de Receita (R).  \n"
    "**Importante**: Só aplicamos regras especiais para entidade 971010 e 971007 em Receitas (R)."
)

uploaded = st.file_uploader("Selecione um ficheiro CSV", type="csv", accept_multiple_files=False)

def extrair_rubrica(conta: str) -> str:
    partes = str(conta).split(".")
    return ".".join(partes[1:]) if len(partes) > 1 else ""

def validar_linha(idx, row):
    erros = []
    rd        = str(row['R/D']).strip()
    fonte     = str(row['Fonte Finan.']).strip()
    org       = str(row['Cl. Orgânica']).strip()
    programa  = str(row['Programa']).strip()
    medida    = str(row['Medida']).strip()
    projeto   = row['Projeto']
    atividade = str(row['Atividade']).strip()
    funcional = str(row['Cl. Funcional']).strip()
    entidade  = str(row['Entidade']).strip()

    # Fonte não preenchida
    if not fonte:
        erros.append("Fonte de Finan. não preenchida")
    # Cl. Orgânica conforme fonte
    elif fonte in ORG_POR_FONTE and org != ORG_POR_FONTE[fonte]:
        erros.append(f"Cl. Orgânica deve ser {ORG_POR_FONTE[fonte]} para fonte {fonte}")

    # Validações específicas apenas para Receita (R)
    if rd == 'R':
        if entidade == '971010' and fonte != '511':
            erros.append("Fonte Finan. deve ser 511 para entidade 971010")
        if entidade == '971007' and fonte != '541':
            erros.append("Fonte Finan. deve ser 541 para entidade 971007")

        if programa != "'011":
            erros.append("Programa deve ser '011")
        if fonte not in ['483', '31H', '488'] and medida != "'022":
            erros.append("Medida deve ser '022 exceto para fontes 483, 31H ou 488")

    elif rd == 'D':
        if fonte not in ['483', '31H', '488'] and medida != "'022":
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

    return erros

def validar_documentos_co(df):
    erros = []
    df_co = df[df['Tipo'] == 'CO']
    for docid, grp in df_co.groupby('DOCID'):
        debs  = grp[grp['Conta'].astype(str).str.startswith(('0281','0282'))]
        creds = grp[grp['Conta'].astype(str).str.startswith('0272')]
        rubs = {extrair_rubrica(c) for c in debs['Conta']}
        for idx, ln in creds.iterrows():
            rub = extrair_rubrica(ln['Conta'])
            if rub not in rubs:
                erros.append((idx, f"DOCID {docid}: sem débito para rubrica {rub}"))
    return erros

if uploaded:
    st.subheader(f"Processando {uploaded.name}")
    df = pd.read_csv(
        io.StringIO(uploaded.getvalue().decode('ISO-8859-1')),
        sep=';', header=9, names=CABECALHOS,
        dtype=str, low_memory=False
    )
    # Filtrar linhas erradas
    df = df[df['Conta'] != 'Conta']
    df = df[~df['Data Contab.'].astype(str).str.contains("Saldo Inicial", na=False)]
    n = len(df)

    progresso = st.progress(0)
    resumo = Counter()
    erros_por_linha = defaultdict(list)

    block = max(1, n // 100)
    for i, row in df.iterrows():
        msgs = validar_linha(i, row)
        if msgs:
            erros_por_linha[i].extend(msgs)
            resumo.update(msgs)
        if i % block == 0 or i == n - 1:
            progresso.progress(min((i + 1) / n, 1.0))

    # Validação extra de CO
    for idx, msg in validar_documentos_co(df):
        erros_por_linha[idx].append(msg)
        resumo[msg] += 1

    # Adicionar coluna de Erros
    df['Erro'] = [
        "; ".join(erros_por_linha[i]) if erros_por_linha[i] else "Sem erros"
        for i in range(n)
    ]

    # Gerar ficheiro de saída
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False)
    buffer.seek(0)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome_ficheiro = f"{uploaded.name.rstrip('.csv')}_output_{ts}.xlsx"

    st.success("Validação concluída!")
    st.dataframe(df)
    st.download_button(
        "⬇️ Descarregar Excel com erros",
        data=buffer, file_name=nome_ficheiro,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    if resumo:
        st.subheader("📊 Resumo de Erros")
        st.table(pd.DataFrame(resumo.most_common(), columns=["Regra", "Ocorrências"]))

else:
    st.info("Primeiro, carrega um ficheiro CSV acima.")
