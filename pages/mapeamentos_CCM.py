import io
import re
import zipfile
from typing import Dict, List, Tuple, Optional

import pandas as pd
import streamlit as st


# ==============================
# Funções de mapeamento
# ==============================

def df_to_mapping(df: pd.DataFrame) -> Dict[str, str]:
    """
    Converte um DataFrame (pelo menos 2 colunas: convenção / entidade)
    num dicionário {Cod_Convencao_6digitos: Cod_Entidade_str}.

    Correção importante:
    - Normaliza o código de convenção para 6 dígitos (preserva zeros à esquerda),
      cobrindo casos de Excel tipo 30400 / 30400.0 -> 030400
    """
    if df.shape[1] < 2:
        raise ValueError("O ficheiro de mapeamento tem de ter pelo menos duas colunas.")

    conv_col = df.columns[0]
    ent_col = df.columns[1]

    mapping: Dict[str, str] = {}
    for _, row in df.iterrows():
        conv_raw = str(row[conv_col]).strip()
        ent_raw = str(row[ent_col]).strip()

        if not conv_raw or conv_raw.lower() in ("nan", "none"):
            continue
        if not ent_raw or ent_raw.lower() in ("nan", "none"):
            continue

        # ---- NORMALIZAÇÃO DA CONVENÇÃO (6 dígitos) ----
        conv_digits = re.sub(r"\D", "", conv_raw)  # remove tudo o que não é dígito
        if conv_digits:
            conv_code = conv_digits.zfill(6)  # 30400 -> 030400
        else:
            conv_code = conv_raw

        # ---- NORMALIZAÇÃO DA ENTIDADE ----
        try:
            ent_int = int(str(ent_raw).replace(" ", ""))
            ent_code = str(ent_int)
        except ValueError:
            ent_code = ent_raw.replace(" ", "")

        mapping[conv_code] = ent_code

    return mapping


def load_default_mapping(path: str = "mapeamentos.csv") -> Tuple[Dict[str, str], Optional[pd.DataFrame]]:
    """
    Tenta carregar o mapeamento 'de base' a partir de um CSV do repositório.
    Devolve (mapping_dict, dataframe) ou ({}, None) se não existir.
    """
    try:
        df = pd.read_csv(path, sep=None, engine="python")
        mapping = df_to_mapping(df)
        return mapping, df
    except FileNotFoundError:
        return {}, None


def load_mapping_file(file) -> Tuple[Dict[str, str], pd.DataFrame]:
    """
    Lê um ficheiro de mapeamento enviado pelo utilizador (CSV/TXT/XLSX)
    e devolve (mapping_dict, dataframe).
    """
    filename = file.name.lower()

    if filename.endswith((".xlsx", ".xls")):
        df = pd.read_excel(file)
    else:
        df = pd.read_csv(file, sep=None, engine="python")

    mapping = df_to_mapping(df)
    return mapping, df


# ==============================
# Funções de transformação
# ==============================

def transform_line(line: str, mapping: Dict[str, str]) -> Tuple[str, bool, bool]:
    """
    Aplica a lógica de conversão a uma linha:
      - corrige CC mal formatado: "+93  " (ou +93 com >=2 espaços) → "+9197"
      - altera o 2.º campo (15 dígitos) com base no mapeamento
      - remove o último bloco de 9 dígitos no fim da linha

    Devolve:
      (linha_convertida, houve_substituicao_bool, mapping_em_falta_bool)
    """
    original_line = line.rstrip("\n")
    changed = False
    mapping_missing = False

    # 1) Corrigir CC mal formatado: "+93  " (ou +93 seguido de ≥2 espaços) → "+9197"
    fixed_line = re.sub(r"\+93\s{2,}", "+9197", original_line)
    if fixed_line != original_line:
        changed = True
        original_line = fixed_line

    # 2) Atualizar o 2.º campo (posições fixas 13–27 se contarmos a partir de 1)
    if len(original_line) >= 27:
        second_field = original_line[12:27]  # index 12 inclusive, 27 exclusive
        if second_field.isdigit() and len(second_field) == 15:
            # Estrutura: 0 + convenção(6) + '91' + sufixo(6)
            conv_code = second_field[1:7]  # 6 dígitos da convenção
            ent_code = mapping.get(conv_code)

            if ent_code is not None:
                try:
                    ent7 = f"{int(ent_code):07d}"
                except ValueError:
                    ent7 = ent_code

                suffix = second_field[9:]  # últimos 6
                new_second = ent7 + "91" + suffix

                new_line = original_line[:12] + new_second + original_line[27:]
                original_line = new_line
                changed = True
            else:
                # Não existe mapeamento para este código de convenção
                mapping_missing = True

    # 3) Remover o último bloco de 9 dígitos no fim da linha (mantendo espaços antes)
    new_line = re.sub(r"(\s)\d{9}$", r"\1", original_line)
    if new_line != original_line:
        changed = True

    return new_line, changed, mapping_missing


def transform_file_bytes(
    file_bytes: bytes, mapping: Dict[str, str], encoding: str = "utf-8"
) -> Tuple[bytes, bytes, int, int, int]:
    """
    Aplica a transformação a um ficheiro completo (em bytes).

    Devolve:
      - bytes_resultantes (ficheiro convertido)
      - bytes_erros (linhas com códigos sem mapeamento, se existirem)
      - num_linhas_alteradas
      - num_linhas_totais
      - num_linhas_com_erro_mapeamento
    """
    try:
        text = file_bytes.decode(encoding)
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1")

    lines = text.splitlines(keepends=False)

    out_lines: List[str] = []
    error_lines: List[str] = []
    changed_count = 0
    mapping_error_count = 0

    for line in lines:
        if not line.strip():
            out_lines.append(line)
            continue

        new_line, changed, mapping_missing = transform_line(line, mapping)
        out_lines.append(new_line)

        if changed:
            changed_count += 1
        if mapping_missing:
            mapping_error_count += 1
            # guardar a linha original no ficheiro de erros
            error_lines.append(line)

    out_text = "\n".join(out_lines) + "\n"
    error_text = ""
    if error_lines:
        error_text = "\n".join(error_lines) + "\n"

    return (
        out_text.encode(encoding),
        error_text.encode(encoding),
        changed_count,
        len(lines),
        mapping_error_count,
    )


# ==============================
# Interface Streamlit
# ==============================

st.set_page_config(page_title="Conversor de Ficheiros MCDT/Termas", layout="wide")

st.title("Conversor de ficheiros MCDT/Termas")

st.write(
    """
    Esta aplicação:
    1. Usa um **mapeamento Cod. Convenção → Cod. Entidade** (CSV no repositório ou ficheiro carregado);  
    2. Corrige CC com `+93` mal formatado para `+9197`;  
    3. Atualiza o **2.º campo (15 dígitos)** dos ficheiros;  
    4. Remove o último código de 9 dígitos no fim de cada linha;  
    5. Gera, por ficheiro:
       - apenas *_CONVERTIDO.txt* se estiver tudo mapeado;
       - apenas *_ERROS.txt* se existirem códigos sem mapeamento.
    """
)

# ---- carregar mapeamento "base de dados" do repositório ----
default_mapping, default_df = load_default_mapping()

st.sidebar.header("Fonte do mapeamento")

mapping_source: Optional[str] = None
mapping: Dict[str, str] = {}
mapping_df: Optional[pd.DataFrame] = None

if default_mapping:
    mapping_source = st.sidebar.radio(
        "Escolher fonte do mapeamento",
        ["CSV do repositório (mapeamentos.csv)", "Carregar outro ficheiro"],
        index=0,
    )
else:
    st.sidebar.info("Nenhum 'mapeamentos.csv' encontrado no repositório.")
    mapping_source = st.sidebar.radio(
        "Escolher fonte do mapeamento",
        ["Carregar outro ficheiro"],
        index=0,
    )

# ---- caso 1: usar CSV do repositório ----
if mapping_source == "CSV do repositório (mapeamentos.csv)" and default_mapping:
    mapping = default_mapping
    mapping_df = default_df
    st.success(f"Mapeamento carregado de 'mapeamentos.csv' ({len(mapping)} entradas).")

# ---- caso 2: carregar ficheiro de mapeamento ----
if mapping_source == "Carregar outro ficheiro":
    st.header("1️⃣ Carregar ficheiro de mapeamento")
    mapping_file = st.file_uploader(
        "Ficheiro de mapeamento (CSV, TXT, XLSX, ...)",
        type=["csv", "txt", "tsv", "xlsx", "xls"],
        key="mapping_uploader",
    )
    if mapping_file is not None:
        try:
            mapping, mapping_df = load_mapping_file(mapping_file)
            st.success(f"Mapeamento carregado com {len(mapping)} códigos de convenção.")
        except Exception as e:
            st.error(f"Erro ao ler ficheiro de mapeamento: {e}")

# ---- secção de “base de dados” / edição do mapeamento ----
if mapping_df is not None:
    st.header("📚 Base de dados de mapeamentos")
    st.write("Podes editar a tabela abaixo e descarregar um CSV atualizado.")

    edited_df = st.data_editor(
        mapping_df,
        num_rows="dynamic",
        use_container_width=True,
        key="mapping_editor",
    )

    csv_bytes = edited_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="⬇️ Descarregar CSV atualizado (para substituir o mapeamentos.csv no GitHub)",
        data=csv_bytes,
        file_name="mapeamentos_atualizado.csv",
        mime="text/csv",
    )
else:
    st.info("Ainda não há mapeamento carregado/selecionado.")

# ---- carregamento de ficheiros de dados ----
st.header("2️⃣ Carregar ficheiros a converter")
data_files = st.file_uploader(
    "Ficheiros de texto a converter",
    type=["txt"],
    accept_multiple_files=True,
    key="data_files_uploader",
)

if data_files and not mapping:
    st.warning("Carrega/seleciona primeiro um mapeamento válido (CSV/Excel).")

if data_files and mapping:
    st.subheader("Resultados da conversão")

    all_results = []
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for uploaded_file in data_files:
            file_bytes = uploaded_file.read()
            (
                converted_bytes,
                error_bytes,
                changed_count,
                total_lines,
                mapping_error_count,
            ) = transform_file_bytes(file_bytes, mapping)

            base_name = uploaded_file.name.rsplit(".", 1)[0]
            out_name = f"{base_name}_CONVERTIDO.txt"
            err_name = f"{base_name}_ERROS.txt"

            st.markdown(f"### {uploaded_file.name}")

            # ---- CASO 1: existem erros de mapeamento -> só ficheiro de ERROS ----
            if mapping_error_count > 0:
                zipf.writestr(err_name, error_bytes)

                all_results.append(
                    {
                        "Ficheiro original": uploaded_file.name,
                        "Ficheiro convertido": "",
                        "Linhas alteradas": changed_count,
                        "Total de linhas": total_lines,
                        "Linhas com código sem mapeamento": mapping_error_count,
                    }
                )

                st.markdown(f"**Erros de mapeamento → {err_name}**")
                st.download_button(
                    label=f"⬇️ Descarregar {err_name}",
                    data=error_bytes,
                    file_name=err_name,
                    mime="text/plain",
                )
                st.warning(
                    f"{mapping_error_count} linha(s) sem mapeamento para o código de convenção. "
                    f"Apenas foi gerado o ficheiro de erros ({err_name})."
                )

            # ---- CASO 2: sem erros -> só ficheiro CONVERTIDO ----
            else:
                zipf.writestr(out_name, converted_bytes)

                all_results.append(
                    {
                        "Ficheiro original": uploaded_file.name,
                        "Ficheiro convertido": out_name,
                        "Linhas alteradas": changed_count,
                        "Total de linhas": total_lines,
                        "Linhas com código sem mapeamento": mapping_error_count,
                    }
                )

                st.markdown(f"**Convertido → {out_name}**")
                st.download_button(
                    label=f"⬇️ Descarregar {out_name}",
                    data=converted_bytes,
                    file_name=out_name,
                    mime="text/plain",
                )
                st.success("Nenhuma linha com código de convenção em falta no mapeamento.")

            st.write(f"- Linhas alteradas: {changed_count} / {total_lines}")
            st.divider()

    if all_results:
        st.subheader("Resumo da conversão")
        st.dataframe(pd.DataFrame(all_results))

        zip_buffer.seek(0)
        st.download_button(
            label="⬇️ Descarregar todos (convertidos + erros) em ZIP",
            data=zip_buffer,
            file_name="ficheiros_convertidos_e_erros.zip",
            mime="application/zip",
        )
