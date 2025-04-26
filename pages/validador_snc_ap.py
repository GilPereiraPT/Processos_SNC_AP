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
    "Verás uma barra de progresso e, no fim, poderás descarregar um Excel com a coluna `Erro`."
)

uploaded = st.file_uploader(
    "Selecione um ficheiro CSV", type="csv", accept_multiple_files=False
)


def extrair_rubrica(conta: str) -> str:
    partes = str(conta).split(".")
    return ".".join(partes[1:]) if len(partes) > 1 else ""


def validar_linha(idx, row):
    erros = []
    # Extrai e normaliza valores
    rd        = str(row['R/D']).strip()
    fonte     = str(row['Fonte Finan.']).strip()
    org       = str(row['Cl. Orgânica']).replace("'", "").strip()
    programa  = str(row['Programa']).replace("'", "").strip()
    medida    = str(row['Medida']).replace("'", "").strip()
    projeto   = row['Projeto']
    atividade = str(row['Atividade']).strip()
    funcional = str(row['Cl. Funcional']).replace("'", "").strip()
    entidade  = str(row['Entidade']).strip()

    # 1) Fonte não preenchida
    if not fonte:
        erros.append("Fonte de Financiamento não preenchida")
    # 2) Verifica orgânica conforme fonte (após normalizar aspas)
    elif fonte in ORG_POR_FONTE and org != ORG_POR_FONTE[fonte]:
        erros.append(f"Cl. Orgânica deve ser {ORG_POR_FONTE[fonte]} para fonte {fonte}")

    # 3) Regras específicas consoante R/D
    if rd == 'R':
        if entidade == '971010' and fonte != '511':
            erros.append("Fonte Finan. deve ser 511 para entidade 971010")
        if programa != '011':
            erros.append("Programa deve ser 011")
        if fonte not in ['483','31H','488'] and medida != '022':
            erros.append("Medida deve ser 022 (exceto fontes 483,31H,488)")
        if entidade == '971007' and fonte != '541':
            erros.append("Fonte Finan. deve ser 541 para entidade 971007")

    elif rd == 'D':
        if fonte not in ['483','31H','488'] and medida != '022':
            erros.append("Medida deve ser 022 (exceto fontes 483,31H,488)")
        if org == '101904000':
            if pd.notna(projeto) and str(projeto).strip():
                if atividade != '000':
                    erros.append("Se o Projeto estiver preenchido, a Atividade deve ser 000")
            else:
                if atividade != '130':
                    erros.append("Se o Projeto estiver vazio, a Atividade deve ser 130")
        if org == '108904000':
            if atividade != '000' or not (pd.notna(projeto) and str(projeto).strip()):
                erros.append("Atividade deve ser 000 e Projeto preenchido (Cl. Orgânica 108904000)")
        if funcional != '0730':
            erros.append("Cl. Funcional deve ser 0730")

    return erros


def validar_documentos_co(df):
    """
    Retorna lista de tuplos (índice, mensagem) para cada erro de DOCID.
    """
    erros = []
    df_co = df[df['Tipo'] == 'CO']
    for docid, grp in df_co.groupby('DOCID'):
        debs = grp[grp['Conta'].astype(str).str.startswith(('0281','0282'))]
        creds = grp[grp['Conta'].astype(str).str.startswith('0272')]
        rubs = {extrair_rubrica(c) for c in debs['Conta']}
        for idx, ln in creds.iterrows():
            rub = extrair_rubrica(ln['Conta'])
            if rub not in rubs:
                erros.append((idx, f"DOCID {docid}: sem débito para rubrica {rub}"))
    return erros

if uploaded:
    st.subheader(f"Processando: {uploaded.name}")
    # ler e ignorar linha de cabeçalhos duplicados
    df = pd.read_csv(
        io.StringIO(uploaded.getvalue().decode('ISO-8859-1')),
        sep=';', skiprows=9, names=CABECALHOS,
        dtype=str, low_memory=False
    )
    # remover eventual linha de cabeçalhos repetidos
    df = df[df['Conta'] != 'Conta']
    # filtrar "Saldo Inicial"
    df = df[~df['Data Contab.'].str.contains("Saldo Inicial", na=False)]
    n = len(df)

    # placeholders de progresso
    progress = st.progress(0)
    resumo_global = Counter()
    erros_por_linha = defaultdict(list)

    # validação linha a linha
    block = max(1, n // 100)
    for idx, row in df.iterrows():
        msgs = validar_linha(idx, row)
        if msgs:
            erros_por_linha[idx].extend(msgs)
            resumo_global.update(msgs)
        if idx % block == 0 or idx == n-1:
            progress.progress((idx+1)/n)

    # validação CO
    for idx, msg in validar_documentos_co(df):
        erros_por_linha[idx].append(msg)
        resumo_global[msg] += 1

    # preencher coluna Erro
    df['Erro'] = [
        "; ".join(erros_por_linha[i]) if erros_por_linha[i] else "Sem erros"
        for i in range(n)
    ]

    # gerar Excel em memória
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False)
    buffer.seek(0)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{uploaded.name.rstrip('.csv')}_output_{ts}.xlsx"

    st.success("Validação concluída!")
    st.dataframe(df)
    st.download_button(
        "⬇️ Descarregar Excel de output",
        data=buffer,
        file_name=fname,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # mostrar resumo de erros
    if resumo_global:
        st.subheader("📊 Resumo de Erros")
        df_res = pd.DataFrame(resumo_global.most_common(), columns=["Regra","Ocorrências"])
        st.table(df_res)
else:
    st.info("Primeiro, carrega um ficheiro CSV acima.")
