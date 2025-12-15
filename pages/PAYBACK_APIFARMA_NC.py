import os
import re
from datetime import date
from typing import List, Dict, Optional, Tuple

import pandas as pd
import streamlit as st
from io import StringIO, BytesIO


# =====================================================
# 1. Caminho do CSV de mapeamento Empresa → Entidade
# =====================================================

def get_mapping_path(default_path: str) -> str:
    """Tenta encontrar o ficheiro de mapeamento."""
    if os.path.isfile(default_path):
        return default_path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.join(script_dir, "mapeamento_entidades_nc.csv")
    if os.path.isfile(candidate):
        return candidate
    return default_path

MAPPING_CSV_PATH = get_mapping_path("mapeamento_entidades_nc.csv")
ENTIDADE_PADRAO = "999"


# =====================================================
# 2. Cabeçalhos EXACTOS do ficheiro de importação
# =====================================================

COLUNAS_FINAIS = [
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

# Colunas que devem ser TEXTO (preservar zeros à esquerda)
COLUNAS_TEXTO = [
    "Classificador funcional ",
    "Programa ",
    "Medida",
    "Classificação Orgânica"
]


# =====================================================
# 3. Funções de base
# =====================================================

def load_empresa_mapping(path: str = MAPPING_CSV_PATH) -> pd.DataFrame:
    """Lê o CSV de mapeamento Empresa;Entidade."""
    df = pd.read_csv(path, sep=";", encoding="latin-1")
    df.columns = [str(c).strip() for c in df.columns]
    obrig = ["Empresa", "Entidade"]
    for c in obrig:
        if c not in df.columns:
            raise ValueError(f"O ficheiro de mapeamento tem de ter as colunas: {obrig}")
    return df


def normalizar_texto(s: str) -> str:
    """Normaliza texto para comparação."""
    s = str(s).strip()
    s = re.sub(r"\s+", " ", s)
    return s.upper()


def limpar_nome_coluna(col: str) -> str:
    """Remove HTML e caracteres especiais de nomes de colunas."""
    col = re.sub(r'<[^>]+>', '', str(col))
    col = col.strip()
    return col


def obter_mapa_empresas(mapping_df: pd.DataFrame) -> Dict[str, str]:
    """Cria dicionário de mapeamento Empresa → Entidade."""
    map_dict: Dict[str, str] = {}
    for _, row in mapping_df.iterrows():
        emp = normalizar_texto(row["Empresa"])
        ent = str(row["Entidade"]).strip()
        if not emp or not ent or ent.lower() in ("nan", "none"):
            continue
        map_dict[emp] = ent
    return map_dict


def separar_por_entidade(
    df_nc: pd.DataFrame, 
    mapping_df: pd.DataFrame
) -> Dict[str, Tuple[pd.DataFrame, List[str]]]:
    """Separa o DataFrame por entidade."""
    map_dict = obter_mapa_empresas(mapping_df)
    
    def get_entidade_para_linha(empresa):
        emp_norm = normalizar_texto(empresa)
        return map_dict.get(emp_norm, ENTIDADE_PADRAO)
    
    df_nc = df_nc.copy()
    df_nc['_entidade_calculada'] = df_nc['Empresa'].apply(get_entidade_para_linha)
    
    resultado = {}
    empresas_sem_mapa = []
    
    for entidade in df_nc['_entidade_calculada'].unique():
        df_ent = df_nc[df_nc['_entidade_calculada'] == entidade].copy()
        empresas_desta_ent = sorted(
            df_ent['Empresa'].dropna().map(normalizar_texto).unique()
        )
        
        for emp in empresas_desta_ent:
            if emp not in map_dict:
                empresas_sem_mapa.append(emp)
        
        resultado[entidade] = (df_ent.drop(columns=['_entidade_calculada']), empresas_desta_ent)
    
    resultado['_empresas_sem_mapa'] = empresas_sem_mapa
    return resultado


def detectar_formato_ficheiro(df: pd.DataFrame) -> Dict[str, str]:
    """Deteta formato do ficheiro e mapeia colunas."""
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
    
    for col_orig, col_limpa in colunas_limpas.items():
        col_upper = col_limpa.upper()
        if "ANO" in col_upper and "Ano" not in colunas_encontradas:
            colunas_encontradas["Ano"] = col_orig
        if "TRANCHE" in col_upper and "Tranche" not in colunas_encontradas:
            colunas_encontradas["Tranche"] = col_orig
    
    return colunas_encontradas


def ler_notas_credito(file) -> pd.DataFrame:
    """Lê ficheiros de Notas de Crédito."""
    fname = file.name.lower()

    if fname.endswith((".xlsx", ".xls")):
        file.seek(0)
        df = pd.read_excel(file)
    else:
        file.seek(0)
        raw = file.read()
        text = None
        
        for enc in ["utf-16", "utf-16-le", "utf-16-be", "utf-8", "utf-8-sig", "latin-1", "cp1252", "iso-8859-1"]:
            try:
                text = raw.decode(enc)
                break
            except (UnicodeDecodeError, AttributeError):
                continue

        if text is None:
            raise ValueError(f"Não foi possível decodificar '{file.name}'.")

        if text.startswith('\ufeff'):
            text = text[1:]

        lines = text.splitlines()
        if not lines:
            raise ValueError("Ficheiro vazio.")
            
        first_line = lines[0]
        skip = 1 if first_line.lower().strip().startswith(('sep=', '"sep=')) else 0
        sep = ";" if ";" in first_line else ("," if "," in first_line else "\t")

        df = pd.read_csv(StringIO(text), sep=sep, skiprows=skip)

    df = df.dropna(axis=1, how='all')
    mapeamento_colunas = detectar_formato_ficheiro(df)
    rename_dict = {v: k for k, v in mapeamento_colunas.items()}
    df = df.rename(columns=rename_dict)
    
    formato_info = []
    if "Ano" in mapeamento_colunas:
        formato_info.append("Ano")
    if "Tranche" in mapeamento_colunas:
        formato_info.append("Tranche")
    
    df.attrs['formato_detectado'] = ", ".join(formato_info) if formato_info else "formato básico"

    df_nc = df[df["Tipo"].astype(str).str.upper().str.contains("NOTA DE CRÉDITO", na=False)].copy()
    if df_nc.empty:
        raise ValueError("Nenhuma 'NOTA DE CRÉDITO' encontrada.")

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


def gerar_dataframe_importacao(
    df_nc: pd.DataFrame,
    entidade: str,
    tipo_nc_prefix: str,
) -> pd.DataFrame:
    """
    Gera DataFrame final para exportação.
    ⚠️ CRÍTICO: Campos com zeros à esquerda são definidos como STRINGS
    """
    linhas_finais = []

    tem_ano = "Ano" in df_nc.columns
    tem_tranche = "Tranche" in df_nc.columns
    data_contab = today_yyyymmdd()

    for _, row in df_nc.iterrows():
        data_doc = format_yyyymmdd(row["Data"])
        valor = float(row["ValorNum"])
        ref = str(row["N.º / Ref.ª"])
        numero_nc = apenas_algarismos(ref)

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

        linha = {
            "NC": "NC",
            "Entidade": entidade,
            "Data documento": data_doc,
            "Data Contabilistica": data_contab,
            "Nº NC": numero_nc,
            "Série": "",
            "Subtipo": "",
            "classificador economico ": "02.01.09.C0.00",
            "Classificador funcional ": "0730",  # TEXTO - preservar zero
            "Fonte de financiamento ": "511",
            "Programa ": "011",  # TEXTO - preservar zero
            "Medida": "022",  # TEXTO - preservar zero
            "Projeto": "",
            "Regionalização": "",
            "Atividade": "130",
            "Natureza": "",
            "Departamento/Atividade": "1",
            "Conta Debito": "221111",
            "Conta a Credito ": "31826111",
            "Valor Lançamento": format_valor_port(valor),
            "Centro de custo": "",
            "Observações Documento ": observacoes_doc,
            "Observaçoes lançamento": "",
            "Classificação Orgânica": "101904000",  # TEXTO - preservar zero
            "Litigio": "",
            "Data Litigio": "",
            "Data Fim Litigio": "",
            "Plano Pagamento": "",
            "Data Plano Pagamento": "",
            "Data Fim Plano Pag": "",
            "Pag Factoring": "",
            "Nº Compromisso Assumido": "",
            "Projeto Documento": "",
            "Ano Compromisso Assumido": "",
            "Série Compromisso Assumido": "",
        }
        
        linhas_finais.append(linha)

    # Criar DataFrame
    df_final = pd.DataFrame(linhas_finais)
    
    # ⚠️ CRÍTICO: Forçar colunas específicas como STRING (dtype=object)
    # Isso garante que 0730, 011, 022 sejam mantidos como texto
    for col in COLUNAS_TEXTO:
        if col in df_final.columns:
            df_final[col] = df_final[col].astype(str)
    
    # Garantir a ordem correta das colunas
    df_final = df_final[COLUNAS_FINAIS]
    
    return df_final


# =====================================================
# 4. Interface Streamlit
# =====================================================

st.set_page_config(page_title="Gerador NC - Importação", layout="wide")
st.title("📄 Gerador de Ficheiros de Importação - Notas de Crédito")

st.markdown("""
### 📋 Instruções
1. **Carrega o ficheiro de mapeamento** (Empresa → Entidade) no sidebar
2. **Carrega o ficheiro de Notas de Crédito** (CSV ou Excel)
3. **Revê as empresas sem mapeamento** (se existirem)
4. **Download dos ficheiros CSV** separados por entidade
""")

# Sidebar - Ficheiro de mapeamento
st.sidebar.header("1️⃣ Ficheiro de Mapeamento")
st.sidebar.markdown("Formato esperado: `Empresa;Entidade`")

mapping_file = st.sidebar.file_uploader(
    "Carrega o ficheiro de mapeamento (CSV)",
    type=["csv"],
    key="mapping"
)

mapping_df = None
if mapping_file:
    try:
        mapping_df = load_empresa_mapping(mapping_file)
        st.sidebar.success(f"✅ {len(mapping_df)} mapeamentos carregados")
        with st.sidebar.expander("Ver mapeamentos"):
            st.dataframe(mapping_df, use_container_width=True)
    except Exception as e:
        st.sidebar.error(f"❌ Erro ao carregar mapeamento: {e}")

# Sidebar - Configurações
st.sidebar.header("2️⃣ Configurações")
tipo_nc_prefix = st.sidebar.text_input(
    "Prefixo das Observações",
    value="Nota de Crédito",
    help="Texto que aparece no início das observações do documento"
)

# Main - Upload de ficheiro NC
st.header("📤 Upload do Ficheiro de Notas de Crédito")

nc_file = st.file_uploader(
    "Carrega o ficheiro com as Notas de Crédito (CSV ou Excel)",
    type=["csv", "txt", "xlsx", "xls"],
    key="nc"
)

if nc_file and mapping_df is not None:
    try:
        with st.spinner("A processar ficheiro..."):
            df_nc = ler_notas_credito(nc_file)
        
        st.success(f"✅ {len(df_nc)} Notas de Crédito carregadas")
        
        # Mostrar informação do ficheiro
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total de registos", len(df_nc))
        with col2:
            total_valor = df_nc["ValorNum"].sum()
            st.metric("Valor total", f"{total_valor:,.2f} €")
        with col3:
            formato = df_nc.attrs.get('formato_detectado', 'N/A')
            st.metric("Formato detectado", formato)
        
        # Preview dos dados
        with st.expander("👁️ Preview dos dados carregados"):
            st.dataframe(df_nc.head(20), use_container_width=True)
        
        # Separar por entidade
        st.header("🗂️ Separação por Entidade")
        
        resultados = separar_por_entidade(df_nc, mapping_df)
        empresas_sem_mapa = resultados.pop('_empresas_sem_mapa', [])
        
        # Avisos de empresas sem mapeamento
        if empresas_sem_mapa:
            st.warning(f"⚠️ {len(empresas_sem_mapa)} empresa(s) sem mapeamento (usarão entidade padrão '{ENTIDADE_PADRAO}'):")
            for emp in sorted(set(empresas_sem_mapa)):
                st.text(f"  • {emp}")
        
        # Mostrar resumo por entidade
        st.subheader("📊 Resumo por Entidade")
        
        resumo_data = []
        for entidade, (df_ent, empresas) in sorted(resultados.items()):
            resumo_data.append({
                "Entidade": entidade,
                "Nº Registos": len(df_ent),
                "Valor Total": f"{df_ent['ValorNum'].sum():,.2f} €",
                "Nº Empresas": len(empresas)
            })
        
        st.dataframe(pd.DataFrame(resumo_data), use_container_width=True)
        
        # Gerar e disponibilizar downloads
        st.header("⬇️ Download dos Ficheiros CSV")
        
        for entidade, (df_ent, empresas) in sorted(resultados.items()):
            with st.expander(f"📁 Entidade {entidade} ({len(df_ent)} registos)"):
                st.markdown(f"**Empresas incluídas:** {', '.join(empresas)}")
                
                # Gerar DataFrame final
                df_final = gerar_dataframe_importacao(
                    df_ent,
                    entidade,
                    tipo_nc_prefix
                )
                
                # Preview
                st.dataframe(df_final.head(10), use_container_width=True)
                
                # Gerar CSV com to_csv do pandas
                csv_string = df_final.to_csv(index=False, sep=";", encoding="utf-8-sig")
                
                # Botão de download CSV
                filename_csv = f"NC_Entidade_{entidade}_{today_yyyymmdd()}.csv"
                st.download_button(
                    label=f"📥 Download CSV - Entidade {entidade}",
                    data=csv_string.encode('utf-8-sig'),
                    file_name=filename_csv,
                    mime="text/csv",
                    key=f"download_csv_{entidade}"
                )
        
        # Download completo (todas as entidades num só ficheiro CSV)
        st.header("📦 Download Completo CSV")
        
        todas_linhas = []
        for entidade, (df_ent, _) in sorted(resultados.items()):
            df_temp = gerar_dataframe_importacao(
                df_ent,
                entidade,
                tipo_nc_prefix
            )
            todas_linhas.append(df_temp)
        
        df_completo = pd.concat(todas_linhas, ignore_index=True)
        
        # CSV completo
        csv_completo_string = df_completo.to_csv(index=False, sep=";", encoding="utf-8-sig")
        
        st.download_button(
            label="📥 Download CSV COMPLETO (todas as entidades)",
            data=csv_completo_string.encode('utf-8-sig'),
            file_name=f"NC_COMPLETO_{today_yyyymmdd()}.csv",
            mime="text/csv",
            key="download_csv_completo"
        )
        
    except Exception as e:
        st.error(f"❌ Erro ao processar ficheiro: {e}")
        st.exception(e)

elif nc_file and mapping_df is None:
    st.warning("⚠️ Por favor, carrega primeiro o ficheiro de mapeamento no sidebar.")
