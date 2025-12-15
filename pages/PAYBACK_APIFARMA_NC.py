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
    """
    df = pd.read_csv(path, sep=";", encoding="latin-1")
    df.columns = [str(c).strip() for c in df.columns]
    obrig = ["Empresa", "Entidade"]
    for c in obrig:
        if c not in df.columns:
            raise ValueError(f"O ficheiro de mapeamento tem de ter as colunas: {obrig}")
    return df


def normalizar_texto(s: str) -> str:
    """
    Normaliza texto para comparação.
    """
    s = str(s).strip()
    s = re.sub(r"\s+", " ", s)
    return s.upper()


def limpar_nome_coluna(col: str) -> str:
    """
    Remove HTML e caracteres especiais de nomes de colunas.
    """
    col = re.sub(r'<[^>]+>', '', str(col))
    col = col.strip()
    return col


def get_entidade_from_empresas(df_nc: pd.DataFrame, mapping_df: pd.DataFrame) -> str:
    """
    Determina o código de Entidade a partir das Empresas.
    """
    empresas_file = (
        df_nc["Empresa"]
        .dropna()
        .map(normalizar_texto)
        .unique()
    )

    if len(empresas_file) == 0:
        raise ValueError("Nenhuma 'Empresa' válida encontrada.")

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
            "As seguintes empresas não têm mapeamento: "
            + "; ".join(empresas_sem_mapa)
        )

    if len(entidades_encontradas) > 1:
        raise ValueError(
            "Várias entidades diferentes no mesmo ficheiro: "
            + "; ".join(sorted(entidades_encontradas))
        )

    return entidades_encontradas.pop()


def detectar_formato_ficheiro(df: pd.DataFrame) -> Dict[str, str]:
    """
    Deteta formato do ficheiro e mapeia colunas.
    """
    colunas_limpas = {col: limpar_nome_coluna(col) for col in df.columns}
    colunas_disponiveis = list(colunas_limpas.values())
    
    mapeamento_alternativas = {
        "Data": ["Data", "Data Documento", "Data NC"],
        "Empresa": ["Empresa", "Nome Empresa"],
        "Instituição": ["Instituição", "Instituicao", "Cliente"],
        "Tipo": ["Tipo", "Tipo Documento"],
        "N.º / Ref.ª": ["N.º / Ref.ª", "Nº Documento", "Número", "Referência"],
        "Valor (com IVA)": ["Valor (com IVA)", "Valor", "Total"],
    }
    
    colunas_encontradas = {}
    colunas_faltantes = []
    
    for col_padrao, alternativas in mapeamento_alternativas.items():
        encontrada = False
        for alt in alternativas:
            if alt in colunas_disponiveis:
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
    
    # Colunas opcionais
    for col_orig, col_limpa in colunas_limpas.items():
        col_upper = col_limpa.upper()
        if "ANO" in col_upper and "Ano" not in colunas_encontradas:
            colunas_encontradas["Ano"] = col_orig
        if "TRANCHE" in col_upper and "Tranche" not in colunas_encontradas:
            colunas_encontradas["Tranche"] = col_orig
    
    return colunas_encontradas


def ler_notas_credito(file) -> pd.DataFrame:
    """
    Lê ficheiros de Notas de Crédito (Excel ou CSV/TXT).
    ⚠️ CORRIGIDO: UTF-16 em primeiro lugar!
    """
    fname = file.name.lower()

    # Excel
    if fname.endswith((".xlsx", ".xls")):
        file.seek(0)
        df = pd.read_excel(file)
    else:
        # CSV/TXT
        file.seek(0)
        raw = file.read()

        text: Optional[str] = None
        encoding_usado: Optional[str] = None

        # ⚠️ IMPORTANTE: UTF-16 PRIMEIRO!
        encodings_para_testar = [
            "utf-16",          # ← ADICIONADO EM PRIMEIRO!
            "utf-16-le",
            "utf-16-be",
            "utf-8",
            "utf-8-sig",
            "latin-1",
            "cp1252",
            "iso-8859-1",
        ]

        for enc in encodings_para_testar:
            try:
                text = raw.decode(enc)
                encoding_usado = enc
                break
            except (UnicodeDecodeError, AttributeError):
                continue

        if text is None:
            raise ValueError(
                f"Não foi possível decodificar '{file.name}'. "
                f"Encodings testados: {', '.join(encodings_para_testar)}"
            )

        # Remover BOM
        if text.startswith('\ufeff'):
            text = text[1:]

        lines = text.splitlines()
        if not lines:
            raise ValueError("Ficheiro vazio.")
            
        first_line = lines[0]
        skip = 1 if first_line.lower().strip().startswith(('sep=', '"sep=')) else 0

        # Detectar separador
        if ";" in first_line:
            sep = ";"
        elif "," in first_line:
            sep = ","
        elif "\t" in first_line:
            sep = "\t"
        else:
            sep = ";"

        buf = StringIO(text)

        # Ler CSV
        try:
            df = pd.read_csv(buf, sep=sep, skiprows=skip)
        except Exception as e:
            raise ValueError(
                f"Erro ao ler '{file.name}'.\n"
                f"Encoding: {encoding_usado}, Separador: '{sep}'\n"
                f"Erro: {e}"
            )

    # Remover colunas vazias
    df = df.dropna(axis=1, how='all')
    
    # Detectar formato
    try:
        mapeamento_colunas = detectar_formato_ficheiro(df)
    except ValueError as e:
        raise ValueError(f"Erro no formato de '{file.name}': {e}")
    
    # Renomear
    rename_dict = {v: k for k, v in mapeamento_colunas.items()}
    df = df.rename(columns=rename_dict)
    
    # Info formato
    formato_info = []
    if "Ano" in mapeamento_colunas:
        col_limpa = limpar_nome_coluna(mapeamento_colunas["Ano"])
        formato_info.append(f"Ano ('{col_limpa}')")
    if "Tranche" in mapeamento_colunas:
        formato_info.append("Tranche")
    
    df.attrs['formato_detectado'] = ", ".join(formato_info) if formato_info else "formato básico"
    df.attrs['mapeamento_colunas'] = mapeamento_colunas

    # Apenas NC
    df_nc = df[df["Tipo"].astype(str).str.upper().str.contains("NOTA DE CRÉDITO", na=False)].copy()
    if df_nc.empty:
        raise ValueError("Nenhuma 'NOTA DE CRÉDITO' encontrada.")

    # Converter valor
    def parse_valor(v):
        s = str(v).strip()
        if not s or s.lower() in ("nan", "none"):
            return 0.0
        s = s.replace(" ", "")
        return float(s.replace(".", "").replace(",", "."))

    df_nc["ValorNum"] = df_nc["Valor (com IVA)"].apply(parse_valor)
    df_nc.attrs = df.attrs

    return df_nc


def format_yyyymmdd(data_str: str) -> str:
    """Converte data para AAAAMMDD."""
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
    """Data de hoje em AAAAMMDD."""
    hoje = date.today()
    return f"{hoje.year:04d}{hoje.month:02d}{hoje.day:02d}"


def format_valor_port(valor: float) -> str:
    """1234.5 → '1234,50'"""
    return f"{valor:.2f}".replace(".", ",")


def apenas_algarismos(texto: str) -> str:
    """Apenas dígitos."""
    return re.sub(r"\D", "", str(texto))


def gerar_linhas_importacao_para_ficheiro(
    df_nc: pd.DataFrame,
    entidade: str,
    tipo_nc_prefix: str,
) -> List[List[str]]:
    """Gera linhas do CSV de importação."""
    linhas: List[List[str]] = []

    tem_ano = "Ano" in df_nc.columns
    tem_tranche = "Tranche" in df_nc.columns
    data_contab = today_yyyymmdd()

    for _, row in df_nc.iterrows():
        data_doc = format_yyyymmdd(row["Data"])
        valor = float(row["ValorNum"])
        ref = str(row["N.º / Ref.ª"])
        numero_nc = apenas_algarismos(ref)

        # Observações
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
        observacoes_doc = f"{tipo_nc_prefix} {observacoes_base}".strip() if observacoes_base else tipo_nc_prefix

        linha: Dict[str, str] = {col: "" for col in HEADER}

        linha["NC"] = "NC"
        linha["Entidade"] = entidade
        linha["Data documento"] = data_doc
        linha["Data Contabilistica"] = data_contab
        linha["Nº NC"] = numero_nc
        linha["classificador economico "] = "02.01.09.C0.00"
        linha["Classificador funcional "] = "0730"
        linha["Fonte de financiamento "] = "511"
        linha["Programa "] = "011"
        linha["Medida"] = "022"
        linha["Atividade"] = "130"
        linha["Conta Debito"] = "21111"
        linha["Conta a Credito "] = "3186111"
        linha["Valor Lançamento"] = format_valor_port(valor)
        linha["Observações Documento "] = observacoes_doc
        linha["Classificação Orgânica"] = "101904000"

        linhas.append([linha[col] for col in HEADER])

    return linhas


def escrever_csv_bytes(linhas: List[List[str]]) -> bytes:
    """Escreve CSV em bytes."""
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

st.title("Conversor de Notas de Crédito APIFARMA / PAYBACK")

st.markdown("""
Converte ficheiros de **Notas de Crédito** (Excel ou CSV) para importação contabilística.

**✨ Suporta automaticamente diferentes formatos** (APIFARMA e PAYBACK).
""")

# Carregar mapeamento
try:
    mapping_df = load_empresa_mapping(MAPPING_CSV_PATH)
    st.success(f"✅ Mapa carregado: {len(mapping_df)} empresas")
    with st.expander("Ver mapeamento"):
        st.dataframe(mapping_df, use_container_width=True)
except Exception as e:
    st.error(f"❌ Erro no mapeamento: {e}")
    st.stop()

st.divider()

# Tipo NC
st.header("1️⃣ Tipo de Nota de Crédito")
tipo_nc = st.radio("Seleciona:", ["APIFARMA", "PAYBACK"], horizontal=True)
tipo_nc_prefix = tipo_nc

st.header("2️⃣ Carregar ficheiros")

uploaded_files = st.file_uploader(
    "Ficheiros de NC (Excel/CSV/TXT)",
    type=["xlsx", "xls", "csv", "txt"],
    accept_multiple_files=True,
)

# Pré-visualização
if uploaded_files:
    preview_rows = []
    for file in uploaded_files:
        try:
            df_nc = ler_notas_credito(file)
            entidade = get_entidade_from_empresas(df_nc, mapping_df)
            empresas = ", ".join(sorted(df_nc["Empresa"].dropna().map(normalizar_texto).unique()))
            formato = df_nc.attrs.get('formato_detectado', 'N/A')
            preview_rows.append({
                "Ficheiro": file.name,
                "Empresas": empresas,
                "Entidade": entidade,
                "Formato": formato,
                "Estado": "✅ OK"
            })
        except Exception as e:
            preview_rows.append({
                "Ficheiro": file.name,
                "Empresas": "",
                "Entidade": "",
                "Formato": "",
                "Estado": f"❌ {str(e)[:60]}..."
            })

    st.subheader("Pré-visualização")
    st.dataframe(pd.DataFrame(preview_rows), use_container_width=True)

process_button = st.button("▶️ Converter", type="primary")

if process_button:
    if not uploaded_files:
        st.error("❌ Carrega ficheiros primeiro.")
    else:
        todas_linhas = []
        erros = []
        total_notas = 0
        formatos = set()

        for file in uploaded_files:
            try:
                df_nc = ler_notas_credito(file)
                entidade = get_entidade_from_empresas(df_nc, mapping_df)
                formatos.add(df_nc.attrs.get('formato_detectado', 'N/A'))
                total_notas += len(df_nc)
                linhas = gerar_linhas_importacao_para_ficheiro(df_nc, entidade, tipo_nc_prefix)
                todas_linhas.extend(linhas)
            except Exception as e:
                erros.append(f"**{file.name}**: {e}")

        if erros:
            st.error("⚠️ Problemas:")
            for e in erros:
                st.markdown(f"- {e}")

        if todas_linhas:
            st.success(
                f"✅ **Sucesso!**\n\n"
                f"- NCs: {total_notas}\n"
                f"- Linhas: {len(todas_linhas)}\n"
                f"- Tipo: {tipo_nc_prefix}\n"
                f"- Formatos: {', '.join(sorted(formatos))}"
            )

            csv_bytes = escrever_csv_bytes(todas_linhas)
            st.download_button(
                "⬇️ Descarregar ficheiro",
                csv_bytes,
                f"NC_{tipo_nc_prefix}_importacao.csv",
                "text/csv"
            )
        else:
            st.warning("⚠️ Nenhuma linha gerada.")
