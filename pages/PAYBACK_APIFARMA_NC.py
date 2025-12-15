import csv
import os
import re
from datetime import date
from io import StringIO, BytesIO
from typing import List, Dict, Optional

import pandas as pd
import streamlit as st


# =====================================================
# 1. Caminho do CSV de mapeamento Empresa → Entidade
# =====================================================

def get_mapping_path(default_path: str) -> str:
    """
    Tenta encontrar o ficheiro de mapeamento.
    Primeiro procura no caminho fornecido, depois no diretório do script.
    """
    if os.path.isfile(default_path):
        return default_path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(script_dir, "mapeamento_entidades_nc.csv")
    if os.path.isfile(candidate):
        return candidate
    return default_path

MAPPING_CSV_PATH = get_mapping_path("mapeamento_entidades_nc.csv")


# =====================================================
# 2. Cabeçalhos EXACTOS do ficheiro de importação
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
# 3. Funções de base
# =====================================================

def load_empresa_mapping(path: str = MAPPING_CSV_PATH) -> pd.DataFrame:
    """
    Lê o CSV de mapeamento Empresa;Entidade do repositório.
    Espera colunas: 'Empresa' e 'Entidade'.
    """
    df = pd.read_csv(path, sep=";", encoding="latin-1")
    # Normaliza nomes de colunas (remove espaços extras)
    df.columns = [str(c).strip() for c in df.columns]
    obrig = ["Empresa", "Entidade"]
    for c in obrig:
        if c not in df.columns:
            raise ValueError(f"O ficheiro de mapeamento tem de ter as colunas: {obrig}")
    return df


def normalizar_texto(s: str) -> str:
    """
    Normaliza texto para comparação:
    - strip
    - colapsa espaços
    - upper
    """
    s = str(s).strip()
    s = re.sub(r"\s+", " ", s)
    return s.upper()


def get_entidade_from_empresas(df_nc: pd.DataFrame, mapping_df: pd.DataFrame) -> str:
    """
    Determina o código de Entidade a partir da(s) Empresa(s) presentes no ficheiro,
    usando o CSV de mapeamento Empresa → Entidade.

    - Se houver várias empresas diferentes com entidades diferentes → erro
    - Se houver empresa sem mapeamento → erro
    - Se todas as empresas mapeiam para a mesma entidade → devolve essa entidade
    """
    empresas_file = (
        df_nc["Empresa"]
        .dropna()
        .map(normalizar_texto)
        .unique()
    )

    if len(empresas_file) == 0:
        raise ValueError("Nenhuma 'Empresa' válida encontrada no ficheiro de notas de crédito.")

    # Construir dicionário Empresa_normalizada → Entidade
    map_dict: Dict[str, str] = {}
    for _, row in mapping_df.iterrows():
        emp = normalizar_texto(row["Empresa"])
        ent = str(row["Entidade"]).strip()
        if not emp or not ent or ent.lower() in ("nan", "none"):
            continue
        map_dict[emp] = ent

    entidades_encontradas = set()
    empresas_sem_mapa = []

    for emp in empresas_file:
        if emp in map_dict:
            entidades_encontradas.add(map_dict[emp])
        else:
            empresas_sem_mapa.append(emp)

    if empresas_sem_mapa:
        raise ValueError(
            "As seguintes empresas não têm mapeamento no CSV de entidades: "
            + "; ".join(empresas_sem_mapa)
        )

    if len(entidades_encontradas) > 1:
        raise ValueError(
            "Foram encontradas várias entidades diferentes no mesmo ficheiro: "
            + "; ".join(sorted(entidades_encontradas))
        )

    # neste ponto há exatamente uma entidade
    return entidades_encontradas.pop()


def detectar_formato_ficheiro(df: pd.DataFrame) -> Dict[str, str]:
    """
    Deteta automaticamente qual o formato do ficheiro de NC e mapeia as colunas.
    
    Retorna dicionário com mapeamento: coluna_padrao -> coluna_real
    """
    colunas_disponiveis = [str(c).strip() for c in df.columns]
    
    # Mapeamento de nomes alternativos para cada coluna obrigatória
    mapeamento_alternativas = {
        "Data": ["Data", "Data Documento", "Data NC", "Data do Documento"],
        "Empresa": ["Empresa", "Nome Empresa", "Nome da Empresa"],
        "Instituição": ["Instituição", "Instituicao", "Cliente", "Entidade Cliente"],
        "Tipo": ["Tipo", "Tipo Documento", "Tipo de Documento"],
        "N.º / Ref.ª": ["N.º / Ref.ª", "Nº Documento", "Número", "Referência", "Nº / Ref.ª"],
        "Valor (com IVA)": ["Valor (com IVA)", "Valor", "Total", "Valor Total"],
    }
    
    colunas_encontradas = {}
    colunas_faltantes = []
    
    # Procurar cada coluna obrigatória
    for col_padrao, alternativas in mapeamento_alternativas.items():
        encontrada = False
        for alt in alternativas:
            if alt in colunas_disponiveis:
                colunas_encontradas[col_padrao] = alt
                encontrada = True
                break
        if not encontrada:
            colunas_faltantes.append(col_padrao)
    
    if colunas_faltantes:
        raise ValueError(
            f"Colunas obrigatórias não encontradas: {', '.join(colunas_faltantes)}.\n"
            f"Colunas disponíveis no ficheiro: {', '.join(colunas_disponiveis)}"
        )
    
    # Procurar colunas opcionais (Ano e Tranche)
    for col in colunas_disponiveis:
        col_upper = col.upper()
        if "ANO" in col_upper and "Ano" not in colunas_encontradas:
            colunas_encontradas["Ano"] = col
        if "TRANCHE" in col_upper and "Tranche" not in colunas_encontradas:
            colunas_encontradas["Tranche"] = col
    
    return colunas_encontradas


def ler_notas_credito(file) -> pd.DataFrame:
    """
    Lê ficheiros de Notas de Crédito em Excel (xlsx/xls) ou CSV/TXT.

    - Se a extensão for .xls/.xlsx → usa read_excel.
    - Caso contrário → tenta decodificar como texto e detetar separador.

    Devolve apenas as linhas onde Tipo contém 'NOTA DE CRÉDITO'.
    """
    fname = file.name.lower()

    # -----------------------------
    # 1) Ficheiros Excel
    # -----------------------------
    if fname.endswith((".xlsx", ".xls")):
        file.seek(0)
        df = pd.read_excel(file)

    # -----------------------------
    # 2) CSV / TXT com autodetecção
    # -----------------------------
    else:
        file.seek(0)
        raw = file.read()

        last_exc: Optional[Exception] = None
        text: Optional[str] = None

        # Detectar encoding
        for enc in ["utf-16", "utf-8-sig", "latin-1"]:
            try:
                text = raw.decode(enc)
                break
            except Exception as e:
                last_exc = e

        if text is None:
            raise ValueError(
                "Não foi possível decodificar o ficheiro (utf-16, utf-8-sig, latin-1). "
                f"Último erro: {last_exc}"
            )

        lines = text.splitlines()
        first_line = lines[0] if lines else ""
        skip = 1 if first_line.lower().startswith("sep=") else 0

        # detetar automaticamente separador
        try:
            dialect = csv.Sniffer().sniff(text, delimiters=";,")
            sep = dialect.delimiter
        except Exception:
            sep = ";"

        buf = StringIO(text)

        try:
            df = pd.read_csv(buf, sep=sep, skiprows=skip)
        except Exception as e:
            raise ValueError(f"Erro ao ler CSV com separador '{sep}': {e}")

    # -----------------------------
    # 3) Detectar formato e validar colunas
    # -----------------------------
    try:
        mapeamento_colunas = detectar_formato_ficheiro(df)
    except ValueError as e:
        raise ValueError(f"Erro na validação do formato do ficheiro: {e}")
    
    # Renomear colunas para nomes padronizados
    rename_dict = {v: k for k, v in mapeamento_colunas.items()}
    df = df.rename(columns=rename_dict)
    
    # Mostrar informação sobre o formato detectado
    formato_info = []
    if "Ano" in mapeamento_colunas:
        formato_info.append(f"Ano (coluna: {mapeamento_colunas['Ano']})")
    if "Tranche" in mapeamento_colunas:
        formato_info.append(f"Tranche (coluna: {mapeamento_colunas['Tranche']})")
    
    # Guardar informação do formato no DataFrame (como atributo)
    df.attrs['formato_detectado'] = ", ".join(formato_info) if formato_info else "formato base"
    df.attrs['mapeamento_colunas'] = mapeamento_colunas

    # Apenas NOTAS DE CRÉDITO
    df_nc = df[df["Tipo"].astype(str).str.upper().str.contains("NOTA DE CRÉDITO")].copy()
    if df_nc.empty:
        raise ValueError("Nenhuma linha com 'NOTA DE CRÉDITO' encontrada no ficheiro.")

    # Converter valor
    def parse_valor(v):
        s = str(v).strip()
        if not s or s.lower() in ("nan", "none"):
            return 0.0
        return float(s.replace(".", "").replace(",", "."))

    df_nc["ValorNum"] = df_nc["Valor (com IVA)"].apply(parse_valor)
    
    # Preservar os atributos no DataFrame filtrado
    df_nc.attrs = df.attrs

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
    if "/" in s:
        # tratar datas tipo DD/MM/AAAA
        partes = s.split("/")
        if len(partes) == 3:
            dia, mes, ano = partes
            return ano + mes.zfill(2) + dia.zfill(2)
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
    tipo_nc_prefix: str,
) -> List[List[str]]:
    """
    Gera as linhas do CSV de importação, no formato do ficheiro modelo,
    para UM ficheiro de origem.
    
    Adapta-se automaticamente ao formato detectado (com Ano, Tranche, ou ambos).

    Regras fixas:
      - NC fixo = "NC"
      - Entidade obtida do CSV Empresa→Entidade
      - Data doc = coluna Data (AAAAMMDD)
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
      - Observações Documento = "<tipo_nc_prefix> " + (Ano e/ou Tranche conforme disponível)
    """
    linhas: List[List[str]] = []

    # Verificar quais colunas opcionais estão disponíveis
    tem_ano = "Ano" in df_nc.columns
    tem_tranche = "Tranche" in df_nc.columns

    data_contab = today_yyyymmdd()

    for _, row in df_nc.iterrows():
        data_doc = format_yyyymmdd(row["Data"])
        valor = float(row["ValorNum"])
        ref = str(row["N.º / Ref.ª"])

        numero_nc = apenas_algarismos(ref)

        # Construir Observações baseado nas colunas disponíveis
        obs_parts = []
        
        if tem_ano and pd.notna(row["Ano"]):
            ano_val = str(row["Ano"]).strip()
            if ano_val and ano_val.lower() not in ("nan", "none", ""):
                obs_parts.append(ano_val)
        
        if tem_tranche and pd.notna(row["Tranche"]):
            tranche_val = str(row["Tranche"]).strip()
            if tranche_val and tranche_val.lower() not in ("nan", "none", ""):
                obs_parts.append(tranche_val)
        
        observacoes_base = " ".join(obs_parts).strip()

        if observacoes_base:
            observacoes_doc = f"{tipo_nc_prefix} {observacoes_base}".strip()
        else:
            observacoes_doc = tipo_nc_prefix

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
        linha["Observações Documento "] = observacoes_doc
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


def escrever_csv_bytes(linhas: List[List[str]]) -> bytes:
    """
    Escreve as linhas num CSV (em memória) e devolve bytes.
    Encoding latin-1, separador ';'.
    """
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
# 4. Interface Streamlit
# =====================================================

st.set_page_config(page_title="NC APIFARMA / PAYBACK → Importação", layout="wide")

st.title("Conversor de Notas de Crédito APIFARMA / PAYBACK para ficheiro de importação contabilística")

st.markdown(
    """
Esta página converte ficheiros de **Notas de Crédito** (Excel ou CSV)  
num ficheiro **CSV pronto a importar na contabilidade**, com o layout oficial.

O mapeamento **Empresa → Entidade** é lido automaticamente do ficheiro
`mapeamento_entidades_nc.csv` existente no repositório.

**Suporta automaticamente diferentes formatos de ficheiro** das plataformas APIFARMA e PAYBACK.
"""
)

# Tentar carregar o CSV de mapeamento
try:
    mapping_df = load_empresa_mapping(MAPPING_CSV_PATH)
    st.success(
        f"✅ Mapa Empresa → Entidade carregado de `{MAPPING_CSV_PATH}` "
        f"({len(mapping_df)} linhas)."
    )
    with st.expander("Ver mapeamento Empresa → Entidade"):
        st.dataframe(mapping_df, use_container_width=True)
except Exception as e:
    st.error(f"❌ Erro ao carregar o ficheiro de mapeamento `{MAPPING_CSV_PATH}`: {e}")
    st.stop()

st.divider()

# Tipo de NC (prefixo para as observações)
st.header("1️⃣ Tipo de Nota de Crédito")
tipo_nc = st.radio(
    "Seleciona o tipo de NC:",
    ["APIFARMA", "PAYBACK"],
    horizontal=True,
)
tipo_nc_prefix = "APIFARMA" if tipo_nc == "APIFARMA" else "PAYBACK"

st.header("2️⃣ Carregar ficheiros de Notas de Crédito")

uploaded_files = st.file_uploader(
    "Ficheiros de Notas de Crédito (Excel: xlsx/xls ou CSV/TXT)",
    type=["xlsx", "xls", "csv", "txt"],
    accept_multiple_files=True,
    key="nc_files_uploader",
)

# Pré-visualização do mapeamento Empresa → Entidade por ficheiro
if uploaded_files:
    preview_rows = []
    for file in uploaded_files:
        fname = file.name
        try:
            df_nc_preview = ler_notas_credito(file)
            entidade_preview = get_entidade_from_empresas(df_nc_preview, mapping_df)
            empresas_preview = ", ".join(
                sorted(
                    df_nc_preview["Empresa"]
                    .dropna()
                    .map(normalizar_texto)
                    .unique()
                )
            )
            formato_detectado = df_nc_preview.attrs.get('formato_detectado', 'N/A')
            preview_rows.append(
                {
                    "Ficheiro": fname,
                    "Empresas no ficheiro": empresas_preview,
                    "Entidade mapeada": entidade_preview,
                    "Formato": formato_detectado,
                    "Estado": "✅ OK",
                }
            )
        except Exception as e:
            preview_rows.append(
                {
                    "Ficheiro": fname,
                    "Empresas no ficheiro": "",
                    "Entidade mapeada": "",
                    "Formato": "",
                    "Estado": f"❌ Erro: {e}",
                }
            )

    st.subheader("Pré-visualização: Empresa(s), Entidade e Formato por ficheiro")
    st.dataframe(pd.DataFrame(preview_rows), use_container_width=True)

process_button = st.button("▶️ Converter para ficheiro de importação", type="primary")

if process_button:
    if not uploaded_files:
        st.error("❌ Carrega pelo menos um ficheiro de notas de crédito.")
    else:
        todas_linhas: List[List[str]] = []
        erros: List[str] = []
        total_notas = 0
        formatos_processados = set()

        for file in uploaded_files:
            fname = file.name
            try:
                df_nc = ler_notas_credito(file)
                entidade = get_entidade_from_empresas(df_nc, mapping_df)
                formato = df_nc.attrs.get('formato_detectado', 'desconhecido')
                formatos_processados.add(formato)
            except Exception as e:
                erros.append(f"[{fname}] {e}")
                continue

            total_notas += len(df_nc)

            linhas = gerar_linhas_importacao_para_ficheiro(
                df_nc=df_nc,
                entidade=entidade,
                tipo_nc_prefix=tipo_nc_prefix,
            )
            todas_linhas.extend(linhas)

        if erros:
            st.error("⚠️ Ocorreram os seguintes problemas:")
            for e in erros:
                st.write(f"- {e}")

        if not todas_linhas:
            st.warning("⚠️ Não foi gerada qualquer linha de importação. Verifique os erros acima.")
        else:
            st.success(
                f"✅ Ficheiro(s) processados com sucesso!\n\n"
                f"- **Notas de crédito total:** {total_notas}\n"
                f"- **Linhas de importação geradas:** {len(todas_linhas)}\n"
                f"- **Tipo de NC aplicado:** {tipo_nc_prefix}\n"
                f"- **Formatos detectados:** {', '.join(sorted(formatos_processados))}"
            )

            csv_bytes = escrever_csv_bytes(todas_linhas)

            st.download_button(
                label="⬇️ Descarregar ficheiro de importação (CSV)",
                data=csv_bytes,
                file_name=f"NC_{tipo_nc_prefix}_importacao_contabilidade.csv",
                mime="text/csv",
            )
