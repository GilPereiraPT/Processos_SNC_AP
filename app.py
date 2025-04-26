import streamlit as st
import pandas as pd
import zipfile
import io
import matplotlib.pyplot as plt
import unicodedata
from collections import Counter
from datetime import datetime

# --- Configurações iniciais ---
st.set_page_config(page_title="Ferramenta Completa: Receita Alheia + Validador SNC-AP", layout="wide")

st.title("🛠️ Ferramenta Integrada: Receita Alheia e Validador SNC-AP")

# --- Seletor de aplicação ---
app_mode = st.selectbox(
    "Seleciona a funcionalidade:",
    ["Criador Receita Alheia", "Validador SNC-AP"]
)

# ==================================
# Criador Receita Alheia
# ==================================
if app_mode == "Criador Receita Alheia":
    st.header("📄 Gerador de Ficheiros - Receita Alheia")

    def normalize(col_name: str) -> str:
        s = col_name.strip().lower()
        s = unicodedata.normalize("NFKD", s)
        return "".join(ch for ch in s if not unicodedata.combining(ch))

    st.sidebar.header("1️⃣ Ficheiro de Entidades")
    entidades_file = st.sidebar.file_uploader("Carregar ficheiro .xlsx", type=["xlsx"])
    df_entidades = None

    if entidades_file:
        df_entidades = pd.read_excel(entidades_file)
        df_entidades.columns = df_entidades.columns.str.strip()
        st.sidebar.success("Entidades carregadas com sucesso.")
        st.sidebar.write("📋 Colunas encontradas:", df_entidades.columns.tolist())

        norm_map = { normalize(c): c for c in df_entidades.columns }
        chave = normalize("Código da Entidade")
        if chave in norm_map:
            df_entidades.rename(columns={ norm_map[chave]: "Código da Entidade" }, inplace=True)
        else:
            st.sidebar.error(
                "⚠️ Não encontrei uma coluna equivalente a 'Código da Entidade'. Corrige o cabeçalho."
            )

    st.header("2️⃣ Dados para gerar Receita Alheia")
    df_input = None

    metodo = st.radio(
        "Como fornecer os dados?",
        ["Upload de ficheiro", "Colar dados Excel (tabulação)"]
    )

    if metodo == "Upload de ficheiro":
        dados_file = st.file_uploader("Carrega um ficheiro Excel com os dados", type=["xlsx"])
        if dados_file:
            df_input = pd.read_excel(dados_file)

    elif metodo == "Colar dados Excel (tabulação)":
        texto_colado = st.text_area("Cola aqui os dados copiados do Excel (colunas separadas por tabulação):")
        if texto_colado:
            try:
                sep = "\t" if "\t" in texto_colado else ";"
                df_input = pd.read_csv(io.StringIO(texto_colado), sep=sep)
            except Exception as e:
                st.error(f"Erro ao processar os dados: {e}")

    if df_input is not None:
        st.write("📋 Colunas dos dados de input:", df_input.columns.tolist())

    if (
        df_input is not None
        and df_entidades is not None
        and "Código da Entidade" in df_entidades.columns
    ):
        outras_cols = [c for c in df_entidades.columns if c != "Código da Entidade"]
        if outras_cols:
            nome_col = outras_cols[0]
            mapping = dict(zip(
                df_entidades["Código da Entidade"],
                df_entidades[nome_col]
            ))
            df_input["Nome da Entidade"] = df_input["Entidade"].map(mapping)
        else:
            df_input["Nome da Entidade"] = ""

        codigos_validos = set(df_entidades["Código da Entidade"])
        df_input["Valido"] = df_input["Entidade"].isin(codigos_validos)

        st.subheader("🔍 Validação de Códigos")
        ordered_cols = ["Entidade", "Valido", "Nome da Entidade"] + [
            c for c in df_input.columns if c not in ["Entidade", "Valido", "Nome da Entidade"]
        ]
        st.dataframe(df_input[ordered_cols])

        erros = df_input[~df_input["Valido"]]
        if not erros.empty:
            st.warning("Foram encontrados códigos inválidos:")
            st.dataframe(erros)
        else:
            st.success("Todos os códigos de entidade são válidos!")

            st.subheader("📄 Ficheiro final (exemplo fictício)")
            hoje = datetime.today().strftime("%Y%m%d")

            def gerar_linhas(row):
                linhas = []
                for i in range(2):
                    linha = {
                        'RA': 'RA',
                        'Entidade': row['Entidade'],
                        'Data documento': hoje,
                        'Data Contabilistica': hoje,
                        'Nº RA': row.get('Nº RA', ''),
                        'classificador economico': row.get('classificador economico', ''),
                        'Classificador funcional': '',
                        'Fonte de financiamento': '',
                        'Programa': '',
                        'Medida': '',
                        'Projeto': '',
                        'Regionalização': '',
                        'Atividade': '',
                        'Natureza': '',
                        'Classificação Orgânica': '',
                        'Departamento/Atividade': '1',
                        'Conta Debito': '',
                        'Conta a Credito': '',
                        'Valor Lançamento': row.get('Valor Lançamento', 0),
                        'Observaçoes documento': (
                            f"Respeitante ao recibo nº {row['Observaçoes documento']}"
                            if str(row['Observaçoes documento']).isdigit()
                            else row['Observaçoes documento']
                        ),
                        'Observaçoes lançamento': '',
                        'Projeto Documento': ''
                    }
                    if i == 0:
                        linha['Conta Debito'] = '111'
                        linha['Conta a Credito'] = '2422'
                    else:
                        linha['Conta Debito'] = '0281.02.02.22.H0.00'
                        linha['Conta a Credito'] = '0272.02.02.22.H0.00'
                        linha['Classificador funcional'] = '0730'
                        linha['Fonte de financiamento'] = '511'
                        linha['Programa'] = '011'
                        linha['Medida'] = '022'
                        linha['Atividade'] = '130'
                        linha['Classificação Orgânica'] = '101904000'
                    linhas.append(linha)
                return linhas

            linhas_finais = []
            for _, row in df_input.iterrows():
                linhas_finais.extend(gerar_linhas(row))
            df_final = pd.DataFrame(linhas_finais)

            st.dataframe(df_final)

            buffer = io.BytesIO()
            df_final.to_excel(buffer, index=False)
            buffer.seek(0)
            st.download_button(
                "⬇️ Exportar Excel",
                data=buffer,
                file_name="ficheiro_RA.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

# ==================================
# Validador SNC-AP
# ==================================
elif app_mode == "Validador SNC-AP":
    st.header("🛡️ Validador de Lançamentos SNC-AP Turbo Finalíssimo")

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
        '541': '101904000', '724': '101904000', '721': '101904000', '361': '108904000', '415': '108904000'
    }

    def ler_csv(f):
        return pd.read_csv(
            f, sep=';', header=9, names=CABECALHOS,
            encoding='ISO-8859-1', dtype=str, low_memory=False
        )

    def ler_ficheiro(uploaded):
        if uploaded.name.endswith(".zip"):
            with zipfile.ZipFile(uploaded) as zip_ref:
                filenames = zip_ref.namelist()
                if filenames:
                    with zip_ref.open(filenames[0]) as f:
                        return ler_csv(f)
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
        rd = limpar(row['R/D'])
        fonte = limpar(row['Fonte Finan.'])
        org = limpar(row['Cl. Orgânica'])
        programa = limpar(row['Programa'])
        medida = limpar(row['Medida'])
        projeto = limpar(row['Projeto'])
        atividade = limpar(row['Atividade'])
        funcional = limpar(row['Cl. Funcional'])
        entidade = limpar(row['Entidade'])

        if not fonte:
            erros.append("Fonte de Finan. não preenchida")
        elif fonte in ORG_POR_FONTE and org != ORG_POR_FONTE[fonte]:
            erros.append(f"Cl. Orgânica deve ser {ORG_POR_FONTE[fonte]} para fonte {fonte}")
        if fonte == '721' and org != '101904000':
            erros.append(f"Fonte {fonte} deve ter Cl. Orgânica 101904000, mas tem {org}")
        if fonte in ['361', '415'] and org != '108904000':
            erros.append(f"Fonte {fonte} deve ter Cl. Orgânica 108904000, mas tem {org}")

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
                if projeto and atividade != '000':
                    erros.append("Se Projeto preenchido, Atividade deve ser 000")
                if not projeto and atividade != '130':
                    erros.append("Se Projeto vazio, Atividade deve ser 130")
            if org == '108904000':
                if atividade != '000' or not projeto:
                    erros.append("Atividade deve ser 000 e Projeto preenchido")
            if funcional != "0730":
                erros.append("Cl. Funcional deve ser '0730")
        return "; ".join(erros) if erros else "Sem erros"

    uploaded = st.file_uploader("Carrega um ficheiro CSV ou ZIP", type=["csv", "zip"])

    if uploaded:
        try:
            df = ler_ficheiro(uploaded)
            df = df[df['Conta'] != 'Conta']
            df = df[~df['Data Contab.'].astype(str).str.contains("Saldo Inicial", na=False)]

            with st.spinner("Validando linhas..."):
                df['Erro'] = df.apply(validar_linha, axis=1)

            st.success(f"Validação concluída. {len(df)} linhas processadas.")
            st.dataframe(df)

            resumo = Counter()
            for erros in df['Erro']:
                if erros != "Sem erros":
                    for erro in erros.split("; "):
                        resumo[erro] += 1

            if resumo:
                st.subheader("📊 Resumo de Erros")
                resumo_df = pd.DataFrame(resumo.most_common(), columns=["Regra", "Ocorrências"])
                st.table(resumo_df)

                fig, ax = plt.subplots(figsize=(8, len(resumo_df) * 0.5))
                resumo_df.plot(kind="barh", x="Regra", y="Ocorrências", ax=ax, legend=False)
                st.pyplot(fig)

            buffer = io.BytesIO()
            df.to_excel(buffer, index=False, engine='openpyxl')
            buffer.seek(0)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            nome_ficheiro = f"{uploaded.name.rstrip('.csv').rstrip('.zip')}_output_{ts}.xlsx"

            st.download_button(
                "⬇️ Descarregar Excel",
                data=buffer,
                file_name=nome_ficheiro,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

        except Exception as e:
            st.error(f"Erro ao processar: {e}")
    else:
        st.info("Carrega um ficheiro para começar.")

