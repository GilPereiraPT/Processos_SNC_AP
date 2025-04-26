import streamlit as st
import pandas as pd
import io
import re
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
    "Carrega um **ficheiro CSV** gerado pelo SNC-AP para validar regras de fonte, rubrica, DOCID, etc.  \n"
    "Verás uma barra de progresso e, no fim, poderás descarregar um Excel com a coluna `Erro`."
)

uploaded = st.file_uploader("Selecione um ficheiro CSV", type="csv", accept_multiple_files=False)

def limpar_texto(x: str) -> str:
    # remove espaços, apóstrofos, símbolos e normaliza
    return re.sub(r"[^\w\d]", "", str(x or "")).strip()

def extrair_rubrica(conta: str) -> str:
    partes = str(conta).split(".")
    return ".".join(partes[1:]) if len(partes) > 1 else ""

def validar_linha(idx, row):
    erros = []
    # normalização
    rd        = limpar_texto(row['R/D'])
    fonte     = limpar_texto(row['Fonte Finan.'])
    org       = limpar_texto(row['Cl. Orgânica'])
    programa  = limpar_texto(row['Programa'])
    medida    = limpar_texto(row['Medida'])
    projeto   = str(row['Projeto']).strip()
    atividade = limpar_texto(row['Atividade'])
    funcional = limpar_texto(row['Cl. Funcional'])
    entidade  = limpar_texto(row['Entidade'])

    # Fonte não preenchida
    if not fonte:
        erros.append("Fonte de Finan. não preenchida")
    # Cl. Orgânica conforme fonte
    elif fonte in ORG_POR_FONTE and org != ORG_POR_FONTE[fonte]:
        erros.append(f"Cl. Orgânica deve ser {ORG_POR_FONTE[fonte]} para fonte {fonte}")

    # Regras R / D
    if rd == 'R':
        if entidade == '971010' and fonte != '511':
            erros.append("Fonte Finan. deve ser 511 para entidade 971010")
        if programa != "011":
            erros.append("Programa deve ser 011")
        if fonte not in ['483', '31H', '488'] and medida != "022":
            erros.append("Medida deve ser 022 (exceto fontes 483,31H,488)")
        if entidade == '971007' and fonte != '541':
            erros.append("Fonte Finan. deve ser 541 para entidade 971007")

    elif rd == 'D':
        if fonte not in ['483', '31H', '488'] and medida != "022":
            erros.append("Medida deve ser 022 (exceto fontes 483,31H,488)")
        if org == '101904000':
            if projeto and atividade != '000':
                erros.append("Projeto preenchido → Atividade deve ser 000")
            if not projeto and atividade != '130':
                erros.append("Projeto vazio → Atividade deve ser 130")
        if org == '108904000':
            if atividade != '000' or not projeto:
                erros.append("Cl. Orgânica 108904000 → Atividade=000 e Projeto preenchido")
        if funcional != "0730":
            erros.append("Cl. Funcional deve ser 0730")

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
    # leitura e limpeza
    df = pd.read_csv(
        io.StringIO(uploaded.getvalue().decode('ISO-8859-1')),
        sep=';', skiprows=9, names=CABECALHOS,
        dtype=str, keep_default_na=False, low_memory=False
    )
    # filtrar cabeçalhos repetidos e "Saldo Inicial"
    df = df[df['Conta'] != 'Conta']
    df = df[~df['Data Contab.'].str.contains("Saldo Inicial", na=False)]
    n = len(df)

    progresso = st.progress(0)
    resumo = Counter()
    erros_por_linha = defaultdict(list)

    # valida linha a linha
    block = max(1, n // 100)
    for i, row in df.iterrows():
        msgs = validar_linha(i, row)
        if msgs:
            erros_por_linha[i].extend(msgs)
            resumo.update(msgs)
        if i % block == 0 or i == n - 1:
            progresso.progress(min((i + 1) / n, 1.0))

    # valida CO
    for idx, msg in validar_documentos_co(df):
        erros_por_linha[idx].append(msg)
        resumo[msg] += 1

    # preencher coluna Erro
    df['Erro'] = [
        "; ".join(erros_por_linha[i]) if erros_por_linha[i] else "Sem erros"
        for i in range(n)
    ]

    # gerar Excel e botão de download
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

    # resumo geral
    if resumo:
        st.subheader("📊 Resumo de Erros")
        st.table(pd.DataFrame(resumo.most_common(), columns=["Regra", "Ocorrências"]))

else:
    st.info("Primeiro, carrega um ficheiro CSV acima.")
