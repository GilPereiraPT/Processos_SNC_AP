import streamlit as st
import pandas as pd
import zipfile
import io
import matplotlib.pyplot as plt
from collections import Counter
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

# --- Funções auxiliares ---

def ler_csv(f):
    return pd.read_csv(
        f,
        sep=';',
        header=9,
        names=CABECALHOS,
        encoding='ISO-8859-1',
        dtype=str,
        low_memory=False
    )

def ler_ficheiro(uploaded):
    if uploaded.name.endswith(".zip"):
        with zipfile.ZipFile(uploaded) as zip_ref:
            filenames = zip_ref.namelist()
            if filenames:
                with zip_ref.open(filenames[0]) as f:
                    return ler_csv(f)
            else:
                raise ValueError("ZIP vazio!")
    else:
        uploaded.seek(0)
        return ler_csv(uploaded)

def extrair_rubrica(conta: str) -> str:
    partes = str(conta).split(".")
    return ".".join(partes[1:]) if len(partes) > 1 else ""

def limpar(x):
    return str(x).strip().lstrip("'") if pd.notna(x) else ""

def validar_linha(row):
    erros = []
    rd        = limpar(row['R/D'])
    fonte     = limpar(row['Fonte Finan.'])
    org       = limpar(row['Cl. Orgânica'])
    programa  = limpar(row['Programa'])
    medida    = limpar(row['Medida'])
    projeto   = limpar(row['Projeto'])
    atividade = limpar(row['Atividade'])
    funcional = limpar(row['Cl. Funcional'])
    entidade  = limpar(row['Entidade'])

    if not fonte:
        erros.append("Fonte de Finan. não preenchida")
    elif fonte in ORG_POR_FONTE and org != ORG_POR_FONTE[fonte]:
        erros.append(f"Cl. Orgânica deve ser {ORG_POR_FONTE[fonte]} para fonte {fonte}")

    if rd == 'R':
        if entidade == '971010' and fonte != '511':
            erros.append("Fonte Finan. deve ser 511 para entidade 971010")
        if entidade == '971007' and fonte != '541':
            erros.append("Fonte Finan. deve ser 541 para entidade 971007")
        if programa != "011":
            erros.append("Programa deve ser '011")
        if fonte not in ['483', '31H', '488'] and medida != "022":
            erros.append("Medida deve ser '022 exceto para fontes 483, 31H ou 488")

    elif rd == 'D':
        if fonte not in ['483', '31H', '488'] and medida != "022":
            erros.append("Medida deve ser '022 exceto para fontes 483, 31H ou 488")

        if org == '101904000':
            if projeto:
                if atividade != '000':
                    erros.append("Se o Projeto estiver preenchido, a Atividade deve ser 000")
            else:
                if atividade != '130':
                    erros.append("Se o Projeto estiver vazio, a Atividade deve ser 130")

        if org == '108904000':
            if atividade != '000' or not projeto:
                erros.append("Atividade deve ser 000 e Projeto preenchido")

        if funcional != "0730":
            erros.append("Cl. Funcional deve ser '0730")

    return "; ".join(erros) if erros else "Sem erros"

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

# --- Streamlit App ---
st.set_page_config(page_title="Validador SNC-AP Turbo Corrigido", layout="wide")
st.title("🛡️ Validador de Lançamentos SNC-AP Turbo Corrigido")

uploaded = st.file_uploader("Carrega um ficheiro CSV ou ZIP", type=["csv", "zip"])

if uploaded:
    try:
        st.subheader(f"Processando {uploaded.name}...")
        df = ler_ficheiro(uploaded)
        df = df[df['Conta'] != 'Conta']
        df = df[~df['Data Contab.'].astype(str).str.contains("Saldo Inicial", na=False)]

        # Validação rápida
        with st.spinner("Validando linhas..."):
            df['Erro'] = df.apply(validar_linha, axis=1)

            # Validar documentos CO
            co_erros = validar_documentos_co(df)
            for idx, msg in co_erros:
                if df.at[idx, 'Erro'] == "Sem erros":
                    df.at[idx, 'Erro'] = msg
                else:
                    df.at[idx, 'Erro'] += f"; {msg}"

        # Mostrar DataFrame
        st.success(f"Validação concluída. Total de linhas: {len(df)}")
        st.dataframe(df)

        # Resumo de Erros
        resumo = Counter()
        for erros in df['Erro']:
            if erros != "Sem erros":
                for erro in erros.split("; "):
                    resumo[erro] += 1

        if resumo:
            st.subheader("📊 Resumo de Erros")
            resumo_df = pd.DataFrame(resumo.most_common(), columns=["Regra", "Ocorrências"])
            st.table(resumo_df)

            # Gráfico
            fig, ax = plt.subplots(figsize=(8, len(resumo_df) * 0.5))
            resumo_df.plot(kind="barh", x="Regra", y="Ocorrências", ax=ax, legend=False)
            st.pyplot(fig)

        # Gerar Excel
        buffer = io.BytesIO()
        df.to_excel(buffer, index=False, engine='openpyxl')
        buffer.seek(0)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        nome_ficheiro = f"{uploaded.name.rstrip('.csv').rstrip('.zip')}_output_{ts}.xlsx"

        st.download_button(
            "⬇️ Descarregar Excel com erros",
            data=buffer,
            file_name=nome_ficheiro,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        st.error(f"Erro ao processar: {e}")
else:
    st.info("Carrega primeiro um ficheiro CSV ou ZIP para começar.")
