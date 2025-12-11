import csv
import os
import re
from datetime import date
from typing import List, Dict, Optional

import pandas as pd
import streamlit as st


# =====================================================
# 1. Cabeçalhos EXACTOS do ficheiro de importação
# =====================================================

HEADER = [
    "NC",
    "Entidade",
    "Data documento",
    "Data Contabilistica",
    "Nº NC",
    "Série",
    "Subtipo",
    "classificador economico ",
    "Classificador funcional ",
    "Fonte de financiamento ",
    "Programa ",
    "Medida",
    "Projeto",
    "Regionalização",
    "Atividade",
    "Natureza",
    "Departamento/Atividade",
    "Conta Debito",
    "Conta a Credito ",
    "Valor Lançamento",
    "Centro de custo",
    "Observações Documento ",
    "Observaçoes lançamento",
    "Classificação Orgânica",
    "Litigio",
    "Data Litigio",
    "Data Fim Litigio",
    "Plano Pagamento",
    "Data Plano Pagamento",
    "Data Fim Plano Pag",
    "Pag Factoring",
    "Nº Compromisso Assumido",
    "Projeto Documento",
    "Ano Compromisso Assumido",
    "Série Compromisso Assumido",
]


# =====================================================
# 2. Funções base
# =====================================================

def get_entidade_from_filename(file_name: str, mapping_df: pd.DataFrame) -> str:
    """
    Determina o código de Entidade a partir do nome do ficheiro,
    usando um DataFrame de mapeamento:
      colunas: 'Padrao_nome_ficheiro', 'Entidade'

    Procura cada padrão como substring no nome do ficheiro (case-insensitive).
    """
    fname = file_name.upper()

    for _, row in mapping_df.iterrows():
        padrao = str(row["Padrao_nome_ficheiro"]).strip()
        entidade = str(row["Entidade"]).strip()
        if not padrao or not entidade or entidade.lower() in ("nan", "none"):
            continue
        if padrao.upper() in fname:
            return entidade

    raise ValueError(
        f"Não foi possível determinar o código de Entidade a partir do nome do ficheiro "
        f"'{file_name}'. Verifique/atualize o mapeamento."
    )


def ler_notas_credito(file) -> pd.DataFrame:
    """
    Lê o ficheiro CSV de notas de crédito (UTF-16, com linha 'sep=;')
    e devolve apenas as linhas do tipo 'NOTA DE CRÉDITO'.
    """
    df = pd.read_csv(
        file,
        sep=";",
        encoding="utf-16",
        skiprows=1,  # ignora a linha 'sep=;'
    )

    obrig = [
        "Data",
        "Empresa",
        "Instituição",
        "Tipo",
        "N.º / Ref.ª",
        "Valor (com IVA)",
    ]
    for c in obrig:
        if c not in df.columns:
            raise ValueError(f"Coluna obrigatória '{c}' não encontrada: {c}")

    # Só NOTAS DE CRÉDITO
    df_nc = df[df["Tipo"].str.upper().str.contains("NOTA DE CRÉDITO")].copy()

    if df_nc.empty:
        raise ValueError("Nenhuma linha com 'NOTA DE CRÉDITO' encontrada no ficheiro.")

    # Converter valor
    def parse_valor(v):
        s = str(v).strip()
        if s == "" or s.lower() in ("nan", "none"):
            return 0.0
        # remover separadores de milhar e usar ponto como decimal
        s = s.replace(".", "").replace(",", ".")
        return float(s)

    df_nc["ValorNum"] = df_nc["Valor (com IVA)"].apply(parse_valor)

    return df_nc


def format_yyyymmdd(data_str: str) -> str:
    """
    Converte '2025-12-11' em '20251211'.
    Se já vier em AAAAMMDD, devolve como está.
    """
    s = str(data_str).strip()
    if "-" in s:
        partes = s.split("-")
        if len(partes) == 3:
            return partes[0] + partes[1] + partes[2]
    return s  # assume já no formato correto / AAAAMMDD


def today_yyyymmdd() -> str:
    """
    Devolve a data de hoje em formato AAAAMMDD.
    """
    hoje = date.today()
    return f"{hoje.year:04d}{hoje.month:02d}{hoje.day:02d}"


def format_valor_port(valor: float) -> str:
    """
    Converte 1234.5 em '1234,50' (sem separador de milhar).
    """
    return f"{valor:.2f}".replace(".", ",")


def apenas_algarismos(texto: str) -> str:
    """
    Mantém apenas dígitos numa string (remove letras, underscores, etc.).
    """
    return re.sub(r"\D", "", str(texto))


def gerar_linhas_importacao_para_ficheiro(
    df_nc: pd.DataFrame,
    entidade: str,
) -> list[list[str]]:
    """
    Gera as linhas do CSV de importação, no formato do ficheiro modelo,
    para UM ficheiro de origem.
    Aplica as regras acordadas:
      - NC fixo
      - Entidade obtida por mapeamento
      - Data doc = coluna Data
      - Data contabilística = data do dia
      - Nº NC = só algarismos de N.º / Ref.ª
      - Série vazia
      - classificador económico = 02.01.09.C0.00
      - classificador funcional = 0730
      - fonte financiamento = 511
      - Programa = 011
      - Medida = 022
      - Atividade = 130
      - Classificação Orgânica = 101904000
      - Conta Debito = 21111
      - Conta a Credito = 3186111
      - Valor Lançamento = Valor (com IVA) em 1234,56
      - Observações Documento = concat col H + col I (Ano + Tranche)
    """
    linhas: list[list[str]] = []

    # Coluna H e I (Ano e Tranche)
    col_h_candidates = [c for c in df_nc.columns if "Ano" in c]
    col_h: Optional[str] = col_h_candidates[0] if col_h_candidates else None
    col_i = "Tranche" if "Tranche" in df_nc.columns else None

    data_contab = today_yyyymmdd()

    for _, row in df_nc.iterrows():
        data_doc = format_yyyymmdd(row["Data"])
        valor = float(row["ValorNum"])
        ref = str(row["N.º / Ref.ª"])

        numero_nc = apenas_algarismos(ref)

        # Observações: H + I
        obs_parts = []
        if col_h and pd.notna(row[col_h]):
            obs_parts.append(str(row[col_h]))
        if col_i and pd.notna(row[col_i]):
            obs_parts.append(str(row[col_i]))
        observacoes = " ".join(obs_parts).strip()

        linha: Dict[str, str] = {col: "" for col in HEADER}

        linha["NC"] = "NC"
        linha["Entidade"] = entidade
        linha["Data documento"] = data_doc
        linha["Data Contabilistica"] = data_contab
        linha["Nº NC"] = numero_nc
        linha["Série"] = ""
        linha["Subtipo"] = ""

        linha["classificador economico "] = "02.01.09.C0.00"
        linha["Classificador funcional "] = "0730"
        linha["Fonte de financiamento "] = "511"
        linha["Programa "] = "011"
        linha["Medida"] = "022"
        linha["Projeto"] = ""
        linha["Regionalização"] = ""
        linha["Atividade"] = "130"
        linha["Natureza"] = ""

        linha["Departamento/Atividade"] = ""
        linha["Conta Debito"] = "21111"
        linha["Conta a Credito "] = "3186111"
        linha["Valor Lançamento"] = format_valor_port(valor)
        linha["Centro de custo"] = ""
        linha["Observações Documento "] = observacoes
        linha["Observaçoes lançamento"] = ""
        linha["Classificação Orgânica"] = "101904000"

        linha["Litigio"] = ""
        linha["Data Litigio"] = ""
        linha["Data Fim Litigio"] = ""
        linha["Plano Pagamento"] = ""
        linha["Data Plano Pagamento"] = ""
        linha["Data Fim Plano Pag"] = ""
        linha["Pag Factoring"] = ""

        linha["Nº Compromisso Assumido"] = ""
        linha["Projeto Documento"] = ""
        linha["Ano Compromisso Assumido"] = ""
        linha["Série Compromisso Assumido"] = ""

        linha_final = [linha[col] for col in HEADER]
        linhas.append(linha_final)

    return linhas


def escrever_csv_bytes(linhas: list[list[str]]) -> bytes:
    """
    Escreve as linhas num CSV (em memória) e devolve bytes.
    Encoding latin-1, separador ';'.
    """
    from io import StringIO, BytesIO

    buffer_text = StringIO()
    writer = csv.writer(buffer_text, delimiter=";")
    writer.writerow(HEADER)
    writer.writerows(linhas)

    text_value = buffer_text.getvalue()
    buffer_bytes = BytesIO()
    buffer_bytes.write(text_value.encode("latin-1"))
    buffer_bytes.seek(0)
    return buffer_bytes.read()


# =====================================================
# 8. Interface Streamlit
# =====================================================

st.set_page_config(page_title="Conversor Notas de Crédito → Importação", layout="wide")

st.title("Conversor de Notas de Crédito para ficheiro de importação contabilística")

st.markdown(
    """
Esta página converte ficheiros de **Notas de Crédito** (exportação tipo Excel/CSV, com `sep=;` e UTF-16)  
num ficheiro **CSV pronto a importar na contabilidade**, com o layout que forneceste.

**Regras aplicadas:**

- `NC` fica sempre **NC**  
- `Entidade` é obtida por **mapeamento do nome do ficheiro**  
- `Data documento` vem da coluna **Data** (formato AAAAMMDD)  
- `Data Contabilistica` é a **data de hoje** (AAAAMMDD)  
- `Nº NC` = apenas algarismos da coluna **N.º / Ref.ª**  
- `Série` fica em branco  
- Classificadores e contas:
  - `classificador economico` → `02.01.09.C0.00`
  - `Classificador funcional` → `0730`
  - `Fonte de financiamento` → `511`
  - `Programa` → `011`
  - `Medida` → `022`
  - `Atividade` → `130`
  - `Classificação Orgânica` → `101904000`
  - `Conta Debito` → `21111`
  - `Conta a Credito` → `3186111`
- `Valor Lançamento` vem de **Valor (com IVA)**, no formato `1234,56`  
- `Observações Documento` = concatenação das colunas **Ano** (coluna H) e **Tranche** (coluna I), quando existirem.
"""
)

st.divider()

st.header("1️⃣ Mapeamento de Entidade por nome de ficheiro")

st.write(
    """
Preenche abaixo o mapeamento entre **padrões do nome do ficheiro** e o código de **Entidade**.
O padrão é uma parte do nome do ficheiro (sem caminho), por exemplo:

- `GLAXOSMITHKLINE` → `1`  
- `PFIZER` → `2`  

Se o padrão aparecer no nome do ficheiro, será usada a Entidade correspondente.
"""
)

default_mapping_df = pd.DataFrame(
    {
        "Padrao_nome_ficheiro": [],
        "Entidade": [],
    }
)

mapping_df = st.data_editor(
    default_mapping_df,
    num_rows="dynamic",
    use_container_width=True,
    key="mapping_editor_nc",
)

st.header("2️⃣ Carregar ficheiros de Notas de Crédito")

uploaded_files = st.file_uploader(
    "Ficheiros CSV de Notas de Crédito (UTF-16, com linha 'sep=;')",
    type=["csv", "txt"],
    accept_multiple_files=True,
    key="nc_files_uploader",
)

process_button = st.button("▶️ Converter para ficheiro de importação")

if process_button:
    if not uploaded_files:
        st.error("Carrega pelo menos um ficheiro de notas de crédito.")
    elif mapping_df.empty or mapping_df["Padrao_nome_ficheiro"].fillna("").str.strip().eq("").all():
        st.error("Preenche pelo menos uma linha no mapeamento de Entidade (padrão → código).")
    else:
        todas_linhas: list[list[str]] = []
        erros: list[str] = []
        total_notas = 0

        for file in uploaded_files:
            fname = file.name
            try:
                entidade = get_entidade_from_filename(fname, mapping_df)
            except ValueError as e:
                erros.append(str(e))
                continue

            try:
                df_nc = ler_notas_credito(file)
            except Exception as e:
                erros.append(f"Erro ao ler/filtrar '{fname}': {e}")
                continue

            total_notas += len(df_nc)

            linhas = gerar_linhas_importacao_para_ficheiro(
                df_nc=df_nc,
                entidade=entidade,
            )
            todas_linhas.extend(linhas)

        if erros:
            st.error("Ocorreram os seguintes problemas:")
            for e in erros:
                st.write(f"- {e}")

        if not todas_linhas:
            st.warning("Não foi gerada qualquer linha de importação. Verifique os erros acima.")
        else:
            st.success(
                f"Ficheiro(s) processados com sucesso. Notas de crédito total: {total_notas}. "
                f"Linhas de importação geradas: {len(todas_linhas)}."
            )

            csv_bytes = escrever_csv_bytes(todas_linhas)

            st.download_button(
                label="⬇️ Descarregar ficheiro de importação (CSV)",
                data=csv_bytes,
                file_name="NC_importacao_contabilidade.csv",
                mime="text/csv",
            )
