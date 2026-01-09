import streamlit as st
import pandas as pd
from datetime import datetime
from io import BytesIO, StringIO
import unicodedata

# Configuração da página
st.set_page_config(page_title="Gerador Receita Alheia", layout="wide")
st.title("📄 Gerador de Ficheiros - Receita Alheia")

# Função para normalizar nomes de colunas (lowercase, sem acentos, sem espaços extra)
def normalize(col_name: str) -> str:
    s = col_name.strip().lower()
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))

# 1️⃣ – UPLOAD DO FICHEIRO DE ENTIDADES
st.sidebar.header("1️⃣ Ficheiro de Entidades")
entidades_file = st.sidebar.file_uploader("Carregar ficheiro .xlsx", type=["xlsx"])
df_entidades = None

if entidades_file:
    df_entidades = pd.read_excel(entidades_file)
    df_entidades.columns = df_entidades.columns.str.strip()
    st.sidebar.success("Entidades carregadas com sucesso.")
    st.sidebar.write("📋 Colunas encontradas em entidades:", df_entidades.columns.tolist())

    # Renomear automaticamente a coluna de código
    norm_map = { normalize(c): c for c in df_entidades.columns }
    chave = normalize("Código da Entidade")
    if chave in norm_map:
        df_entidades.rename(columns={ norm_map[chave]: "Código da Entidade" }, inplace=True)
    else:
        st.sidebar.error(
            "⚠️ Não encontrei uma coluna equivalente a 'Código da Entidade'.\n"
            "Corrige o cabeçalho no teu Excel e volta a carregar."
        )

# 2️⃣ – DADOS PARA GERAR RECEITA ALHEIA
st.header("2️⃣ Dados para gerar Receita Alheia")
df_input = None

metodo = st.radio(
    "Como pretendes fornecer os dados?",
    ["Upload de ficheiro", "Colar dados Excel (tabulação)"]
)

if metodo == "Upload de ficheiro":
    dados_file = st.file_uploader("Carrega um ficheiro Excel com os dados", type=["xlsx"])
    if dados_file:
        df_input = pd.read_excel(dados_file)

elif metodo == "Colar dados Excel (tabulação)":
    texto_colado = st.text_area(
        "Cola aqui os dados copiados do Excel (cada coluna separada por tab):"
    )
    if texto_colado:
        try:
            sep = "\t" if "\t" in texto_colado else ";"
            df_input = pd.read_csv(StringIO(texto_colado), sep=sep)
        except Exception as e:
            st.error(f"Erro ao processar os dados colados: {e}")

# Mostrar colunas do input para debug
if df_input is not None:
    st.write("📋 Colunas encontradas nos dados de input:", df_input.columns.tolist())

# 3️⃣ – VALIDAÇÃO E GERAÇÃO DO FICHEIRO FINAL
if (
    df_input is not None
    and df_entidades is not None
    and "Código da Entidade" in df_entidades.columns
):

    # Mapear Código → Nome da Entidade (usa a segunda coluna do Excel de entidades)
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

    # Flag de validade
    codigos_validos = set(df_entidades["Código da Entidade"])
    df_input["Valido"] = df_input["Entidade"].isin(codigos_validos)

    # Mostra o resultado da validação: Entidade, Valido, Nome da Entidade, depois o resto
    st.subheader("🔍 Validação de Códigos")
    ordered_cols = ["Entidade", "Valido", "Nome da Entidade"] + [
        c for c in df_input.columns
        if c not in ["Entidade", "Valido", "Nome da Entidade"]
    ]
    st.dataframe(df_input[ordered_cols])

    # Se existirem códigos inválidos, mostra warnings
    erros = df_input[~df_input["Valido"]]
    if not erros.empty:
        st.warning("Foram encontrados códigos de entidade inválidos:")
        st.dataframe(erros)
    else:
        st.success("Todos os códigos de entidade são válidos!")

        # Geração do ficheiro final de exemplo
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
                    linha['Programa'] = '015'
                    linha['Medida'] = '022'
                    linha['Atividade'] = '533'
                    linha['Classificação Orgânica'] = '121904000'
                linhas.append(linha)
            return linhas

        # Construir DataFrame final
        linhas_finais = []
        for _, row in df_input.iterrows():
            linhas_finais.extend(gerar_linhas(row))
        df_final = pd.DataFrame(linhas_finais)

        st.dataframe(df_final)

        # Botão de download
        buffer = BytesIO()
        df_final.to_excel(buffer, index=False)
        buffer.seek(0)
        st.download_button(
            "⬇️ Exportar Excel",
            data=buffer,
            file_name="ficheiro_RA.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
