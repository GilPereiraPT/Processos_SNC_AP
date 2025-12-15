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


def limpar_nome_coluna(col: str) -> str:
    """
    Remove HTML e caracteres especiais de nomes de colunas.
    Exemplo: '<span style="...">Ano</span>' → 'Ano'
    """
    # Remover tags HTML
    col = re.sub(r'<[^>]+>', '', str(col))
    # Remover espaços extras
    col = col.strip()
    return col


def get_entidade_from_empresas(df_nc: pd.DataFrame, mapping_df: pd.DataFrame) -> str:
    """
    Determina o código de Entidade a partir da(s) Empresa(s) presentes no ficheiro,
    usando o CSV de mapeamento Empresa → Entidade.
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

    return entidades_encontradas.pop()


def detectar_formato_ficheiro(df: pd.DataFrame) -> Dict[str, str]:
    """
    Deteta automaticamente qual o formato do ficheiro de NC e mapeia as colunas.
    Limpa nomes de colunas (remove HTML) antes de processar.
    """
    # Limpar nomes de colunas (remover HTML)
    colunas_limpas = {col: limpar_nome_coluna(col) for col in df.columns}
    colunas_disponiveis = list(colunas_limpas.values())
    
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
                # Encontrar a coluna original (com HTML se existir)
                for col_orig, col_limpa in colunas_limpas.items():
                    if col_limpa == alt:
                        colunas_encontradas[col_padrao] = col_orig
                        encontrada = True
                        break
                if encontrada:
                    break
        if not encontrada:
            colunas_faltantes.append(col_padrao)
    
    if colunas_faltantes:
        raise ValueError(
            f"Colunas obrigatórias não encontradas: {', '.join(colunas_faltantes)}.\n"
            f"Colunas disponíveis: {', '.join(colunas_disponiveis)}"
        )
    
    # Procurar colunas opcionais (Ano e Tranche)
    for col_orig, col_limpa in colunas_limpas.items():
        col_upper = col_limpa.upper()
        if "ANO" in col_upper and "Ano" not in colunas_encontradas:
            colunas_encontradas["Ano"] = col_orig
        if "TRANCHE" in col_upper and "Tranche" not in colunas_encontradas:
            colunas_encontradas["Tranche"] = col_orig
    
    return colunas_encontradas


def ler_notas_credito(file) -> pd.DataFrame:
    """
    Lê ficheiros de Notas de Crédito em Excel (xlsx/xls) ou CSV/TXT.
    """
    fname = file.name.lower()

    # -----------------------------
    # 1) Ficheiros Excel
    # -----------------------------
    if fname.endswith((".xlsx", ".xls")):
        file.seek(0)
        df = pd.read_excel(file)

    # -----------------------------
    # 2) CSV / TXT com autodetecção melhorada
    # -----------------------------
    else:
        file.seek(0)
        raw = file.read()

        text: Optional[str] = None
        encoding_usado: Optional[str] = None

        # Lista de encodings para testar
        encodings_para_testar = [
            "utf-8",
            "utf-8-sig",
            "latin-1",
            "cp1252",
            "iso-8859-1",
            "windows-1252",
        ]

        # Tentar cada encoding
        for enc in encodings_para_testar:
            try:
                text = raw.decode(enc)
                encoding_usado = enc
                break
            except (UnicodeDecodeError, AttributeError):
                continue

        if text is None or encoding_usado is None:
            raise ValueError(
                f"Não foi possível decodificar o ficheiro '{file.name}'. "
                f"Encodings testados: {', '.join(encodings_para_testar)}"
            )

        # Remover BOM se existir
        if text.startswith('\ufeff'):
            text = text[1:]

        lines = text.splitlines()
        if not lines:
            raise ValueError("O ficheiro está vazio.")
            
        first_line = lines[0] if lines else ""
        skip = 1 if first_line.lower().startswith("sep=") else 0

        # Detectar separador
        try:
            sample = "\n".join(lines[skip:min(skip+5, len(lines))])
            dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
            sep = dialect.delimiter
        except Exception:
            if ";" in first_line:
                sep = ";"
            elif "," in first_line:
                sep = ","
            elif "\t" in first_line:
                sep = "\t"
            else:
                sep = ";"

        buf = StringIO(text)

        # Tentar ler com várias estratégias
        df = None
        erros = []
        
        # Estratégia 1: Leitura normal
        try:
            df = pd.read_csv(buf, sep=sep, skiprows=skip)
        except Exception as e1:
            erros.append(f"Leitura normal: {str(e1)[:100]}")
            
            # Estratégia 2: Com on_bad_lines='skip' (pandas >= 1.3)
            buf = StringIO(text)
            try:
                df = pd.read_csv(
                    buf, 
                    sep=sep, 
                    skiprows=skip,
                    on_bad_lines='skip'
                )
            except Exception as e2:
                erros.append(f"Com on_bad_lines='skip': {str(e2)[:100]}")
                
                # Estratégia 3: Engine python (mais tolerante)
                buf = StringIO(text)
                try:
                    df = pd.read_csv(
                        buf,
                        sep=sep,
                        skiprows=skip,
                        engine='python',
                        on_bad_lines='skip'
                    )
                except Exception as e3:
                    erros.append(f"Engine python: {str(e3)[:100]}")
                    raise ValueError(
                        f"Não foi possível ler o ficheiro '{file.name}'.\n"
                        f"Encoding detectado: {encoding_usado}\n"
                        f"Separador detectado: '{sep}'\n"
                        f"Tentativas realizadas:\n" + "\n".join(f"- {e}" for e in erros)
                    )

    # Remover colunas completamente vazias
    df = df.dropna(axis=1, how='all')
    
    # -----------------------------
    # 3) Detectar formato e validar colunas
    # -----------------------------
    try:
        mapeamento_colunas = detectar_formato_ficheiro(df)
    except ValueError as e:
        raise ValueError(f"Erro na validação do formato do ficheiro '{file.name}': {e}")
    
    # Renomear colunas para nomes padronizados
    rename_dict = {v: k for k, v in mapeamento_colunas.items()}
    df = df.rename(columns=rename_dict)
    
    # Informação sobre o formato detectado
    formato_info = []
    if "Ano" in mapeamento_colunas:
        col_orig = mapeamento_colunas["Ano"]
        col_limpa = limpar_nome_coluna(col_orig)
        formato_info.append(f"Ano ('{col_limpa}')")
    if "Tranche" in mapeamento_colunas:
        formato_info.append("Tranche")
    
    # Guardar informação do formato no DataFrame
    df.attrs['formato_detectado'] = ", ".join(formato_info) if formato_info else "formato básico"
    df.attrs['mapeamento_colunas'] = mapeamento_colunas

    # Apenas NOTAS DE CRÉDITO
    df_nc = df[df["Tipo"].astype(str).str.upper().str.contains("NOTA DE CRÉDITO", na=False)].copy()
    if df_nc.empty:
        raise ValueError("Nenhuma linha com 'NOTA DE CRÉDITO' encontrada no ficheiro.")

    # Converter valor
    def parse_valor(v):
        s = str(v).strip()
        if not s or s.lower() in ("nan", "none"):
            return 0.0
        s = s.replace(" ", "")
        return float(s.replace(".", "").replace(",", "."))

    df_nc["ValorNum"] = df_nc["Valor (com IVA)"].apply(parse_valor)
    
    # Preservar os atributos
    df_nc.attrs = df.attrs

    return df_nc


def format_yyyymmdd(data_str: str) -> str:
    """
    Converte '2025-12-11' em '20251211'.
    """
    s = str(data_str).strip()
    if "-" in s:
        partes = s.split("-")
        if len(partes) == 3:
            return partes[0] + partes[1] + partes[2]
    if "/" in s:
        partes = s.split("/")
        if len(partes) == 3:
            dia, mes, ano = partes
            return ano + mes.zfill(2) + dia.zfill(2)
    return s


def today_yyyymmdd() -> str:
    """
    Devolve a data de hoje em formato AAAAMMDD.
    """
    hoje = date.today()
    return f"{hoje.year:04d}{hoje.month:02d}{hoje.day:02d}"


def format_valor_port(valor: float) -> str:
    """
    Converte 1234.5 em '1234,50'.
    """
    return f"{valor:.2f}".replace(".", ",")


def apenas_algarismos(texto: str) -> str:
    """
    Mantém apenas dígitos numa string.
    """
    return re.sub(r"\D", "", str(texto))


def gerar_linhas_importacao_para_ficheiro(
    df_nc: pd.DataFrame,
    entidade: str,
    tipo_nc_prefix: str,
) -> List[List[str]]:
    """
    Gera as linhas do CSV de importação.
    """
    linhas: List[List[str]] = []

    tem_ano = "Ano" in df_nc.columns
    tem_tranche = "Tranche" in df_nc.columns

    data_contab = today_yyyymmdd()

    for _, row in df_nc.iterrows():
        data_doc = format_yyyymmdd(row["Data"])
        valor = float(row["ValorNum"])
        ref = str(row["N.º / Ref.ª"])

        numero_nc = apenas_algarismos(ref)

        # Construir Observações
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

**✨ Suporta automaticamente diferentes formatos de ficheiro** das plataformas APIFARMA e PAYBACK.
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

# Tipo de NC
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

# Pré-visualização
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
                    "Estado": f"❌ {str(e)[:80]}...",
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
                erros.append(f"**{fname}**: {e}")
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
                st.markdown(f"- {e}")

        if not todas_linhas:
            st.warning("⚠️ Não foi gerada qualquer linha de importação. Verifique os erros acima.")
        else:
            st.success(
                f"✅ **Ficheiro(s) processados com sucesso!**\n\n"
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
