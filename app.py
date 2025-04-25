import streamlit as st
import pandas as pd
from datetime import datetime
from io import BytesIO, StringIO
import unicodedata

st.set_page_config(page_title="Gerador Receita Alheia", layout="wide")
st.title("📄 Gerador de Ficheiros - Receita Alheia")

# Função de normalização de texto (lower, sem acentos, strip)
def normalize(col_name: str) -> str:
    s = col_name.strip().lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))

# 1️⃣ Carregar ficheiro de entidades
st.sidebar.header("1️⃣ Ficheiro de Entidades")
entidades_file = st.sidebar.file_uploader("Carregar ficheiro .xlsx", type=["xlsx"])
df_entidades = None
if entidades_file:
    df_entidades = pd.read_excel(entidades_file)
    # tira espaços em branco inadvertidos dos labels
    df_entidades.columns = df_entidades.columns.str.strip()
    st.sidebar.success("Entidades carregadas com sucesso.")
    # Mostra quais são as colunas lidas
    st.sidebar.write("📋 Colunas encontradas:", df_entidades.columns.tolist())

    # Detecta automaticamente a coluna de 'Código da Entidade'
    norm_map = { normalize(col): col for col in df_entidades.columns }
    chave = normalize("Código da Entidade")
    if chave in norm_map:
        # renomeia para sempre usar este nome no restante código
        df_entidades.rename(columns={ norm_map[chave]: "Código da Entidade" }, inplace=True)
    else:
        st.sidebar.error(
            "⚠️ Não encontrei nenhuma coluna equivalente a 'Código da Entidade'.\n"
            "Verifique o nome do cabeçalho no seu ficheiro."
        )

# 2️⃣ Dados para gerar Receita Alheia
st.header("2️⃣ Dados para gerar Receita Alheia")
df_input = None

metodo = st.radio(
    "Como pretendes fornecer os dados?",
    ["Upload de ficheiro", "Colar dados CSV (ponto e vírgula)"]
)

if metodo == "Upload de ficheiro":
    dados_file = st.file_uploader("Carrega um ficheiro Excel com os dados", type=["xlsx"])
    if dados_file:
        df_input = pd.read_excel(dados_file)

elif metodo == "Colar dados CSV (ponto e vírgula)":
    texto_colado = st.text_area("Cola aqui os dados no formato CSV (separador `;`):")
    if texto_colado:
        try:
            df_input = pd.read_csv(StringIO(texto_colado), sep=';')
        except Exception as e:
            st.error(f"Erro ao processar os dados colados: {e}")

# 3️⃣ Validação e geração do ficheiro final
if df_input is not None and df_entidades is not None:
    # Aqui já temos garantido que existe df_entidades["Código da Entidade"]
    codigos_validos = set(df_entidades["Código da Entidade"])
    df_input['Valido'] = df_input['Entidade'].isin(codigos_validos)

    st.subheader("🔍 Validação de Códigos")
    st.dataframe(df_input)

    erros = df_input[~df_input['Valido']]
    if not erros.empty:
        st.warning("Foram encontrados códigos de entidade inválidos:")
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

        # 4️⃣ Preparar download do Excel gerado
        buffer = BytesIO()
        df_final.to_excel(buffer, index=False)
        buffer.seek(0)

        st.download_button(
            "⬇️ Exportar Excel",
            data=buffer,
            file_name="ficheiro_RA.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
