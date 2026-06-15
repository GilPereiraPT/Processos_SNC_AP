# -*- coding: utf-8 -*-
import re
from typing import Dict, Tuple, Optional

import pandas as pd
import streamlit as st

# =========================================================
# ⚙️ Configuração
# =========================================================
MAPPING_PATH = "mapeamentos.csv"
MAPPING_SEPARATOR = ";"
MAPPING_HEADER_CONV = "Cod. Convencao"
MAPPING_HEADER_ENTITY = "Cod. Entidade"

FINAL_LINE_LENGTH = 140

# =========================================================
# ⚙️ Estado global
# =========================================================
if "mapping_dict" not in st.session_state:
    st.session_state.mapping_dict = {}

if "mapping_df" not in st.session_state:
    st.session_state.mapping_df = None

if "missing_codes" not in st.session_state or not isinstance(st.session_state.missing_codes, dict):
    st.session_state.missing_codes = {}


# =========================================================
# ⚙️ Funções auxiliares
# =========================================================
def normalize_mapping_key(value: str) -> str:
    """
    Normaliza a convenção para uso interno.

    Exemplos:
        30100  -> 30100
        030100 -> 30100
        000401 -> 401
    """
    digits = re.sub(r"\D", "", str(value))

    if not digits:
        return ""

    return str(int(digits))


def normalize_entity_value(value: str) -> str:
    """
    Limpa o código de entidade, mantendo apenas dígitos.
    """
    return re.sub(r"\D", "", str(value))


def convention_for_csv(value: str) -> str:
    """
    Valor a guardar no CSV, sem zeros artificiais à esquerda.
    """
    digits = re.sub(r"\D", "", str(value))

    if not digits:
        return ""

    return str(int(digits))


# =========================================================
# ⚙️ Carregar mapeamentos
# =========================================================
@st.cache_data(ttl=3600)
def load_default_mapping(
    path: str = MAPPING_PATH
) -> Tuple[Dict[str, str], Optional[pd.DataFrame]]:
    try:
        df = pd.read_csv(
            path,
            sep=MAPPING_SEPARATOR,
            encoding="utf-8-sig",
            dtype=str,
            keep_default_na=False
        )

        required_columns = [MAPPING_HEADER_CONV, MAPPING_HEADER_ENTITY]

        if list(df.columns[:2]) != required_columns:
            raise ValueError(
                "O CSV de mapeamentos não tem o formato esperado. "
                f"Esperado: {MAPPING_HEADER_CONV};{MAPPING_HEADER_ENTITY}"
            )

        df = df[[MAPPING_HEADER_CONV, MAPPING_HEADER_ENTITY]].copy()

        df[MAPPING_HEADER_CONV] = df[MAPPING_HEADER_CONV].astype(str).str.strip()
        df[MAPPING_HEADER_ENTITY] = df[MAPPING_HEADER_ENTITY].astype(str).str.strip()

        mapping = {}

        for _, row in df.iterrows():
            conv_csv = str(row[MAPPING_HEADER_CONV]).strip()
            entity = normalize_entity_value(row[MAPPING_HEADER_ENTITY])
            conv_internal = normalize_mapping_key(conv_csv)

            if conv_internal and entity:
                mapping[conv_internal] = entity

        return mapping, df

    except Exception as e:
        st.error(f"❌ Erro ao carregar mapeamento: {e}")
        return {}, None


# =========================================================
# 🔍 Procurar código de convenção no token
# =========================================================
def mapping_candidates(code: str):
    """
    Gera formas possíveis do código no token.

    A ordem é importante:
    - primeiro com 6 dígitos, para preservar o comprimento do token;
    - depois a forma simples.
    """
    code = normalize_mapping_key(code)

    if not code:
        return []

    z6 = code.zfill(6)

    candidates = [
        z6,
        "0" + z6,
        code,
        "0" + code,
    ]

    out = []
    for c in candidates:
        if c and c not in out:
            out.append(c)

    return out


def find_mapping_for_token2(token2: str, mapping: Dict[str, str]) -> Optional[str]:
    """
    Procura o código de convenção dentro do segundo token.

    Mantém a lógica do script funcional:
    - percorre o mapa pela ordem do CSV;
    - procura a convenção dentro do token;
    - evita depender de ordenações artificiais por tamanho.

    Isto permite que códigos específicos que aparecem antes no CSV sejam
    apanhados antes de códigos mais genéricos que também possam existir
    dentro da mesma sequência.
    """
    token_digits = re.sub(r"\D", "", str(token2))

    for conv_code in mapping.keys():
        for candidate in mapping_candidates(conv_code):
            if candidate in token_digits:
                return conv_code

    return None


# =========================================================
# 🔍 Detetar convenção em falta
# =========================================================
def extract_missing_convention_from_token2(token2: str) -> Optional[str]:
    """
    Só considera convenção em falta quando o segundo token começa
    exatamente pelo padrão:
        0 + 6 algarismos
    """
    token_digits = re.sub(r"\D", "", str(token2))

    match = re.match(r"^0(\d{6})", token_digits)

    if match:
        return normalize_mapping_key(match.group(1))

    return None


# =========================================================
# 🧩 Transformação da linha
# =========================================================
def transform_line(
    line: str,
    mapping: Dict[str, str],
    expected_len: int = FINAL_LINE_LENGTH
):
    missing_code = None

    # -----------------------------------------------------
    # 1️⃣ Corrigir coluna 12
    # -----------------------------------------------------
    # Bruto:
    # 902920205590003010092020559...
    #
    # Intermédio:
    # 90292020559 003010092020559...
    #
    # Este espaço é apenas para separar o token e permitir conversão.
    if len(line) >= 12 and line[11] == "0":
        line = line[:11] + " " + line[12:]

    # -----------------------------------------------------
    # 2️⃣ Corrigir CC
    # -----------------------------------------------------
    line = re.sub(r"\+93\s\s", "+9197", line)

    # -----------------------------------------------------
    # 3️⃣ Processar segundo token
    # -----------------------------------------------------
    parts = line.split(maxsplit=2)

    if len(parts) >= 2:
        token2 = parts[1]

        matched_conv = find_mapping_for_token2(token2, mapping)

        if matched_conv:
            ent_code = mapping[matched_conv]

            try:
                ent7 = f"{int(ent_code):07d}"

                new_token2 = token2
                replaced = False

                # Primeiro tenta substituir a forma com 6 dígitos.
                # Isto preserva melhor o comprimento do segundo token.
                for candidate in mapping_candidates(matched_conv):
                    if candidate in new_token2:
                        new_token2 = new_token2.replace(candidate, ent7, 1)
                        replaced = True
                        break

                if not replaced:
                    pass

                # Linhas especiais 903 / 904 / 906
                if line.lstrip().startswith(("903", "904", "906")) and new_token2.startswith("0"):
                    new_token2 = new_token2[1:]

                # Mantém pelo menos o comprimento original do token
                if len(new_token2) < len(token2):
                    new_token2 = new_token2.ljust(len(token2))

                prefix = line[:line.find(token2)]
                suffix = line[line.find(token2) + len(token2):]

                # -------------------------------------------------
                # Regra crítica de alinhamento:
                # Nas linhas 902, o ficheiro final fica sem espaço
                # entre o primeiro campo e o segundo token convertido.
                #
                # Exemplo:
                # 902920205590030100998035039
                #
                # e não:
                # 90292020559 0030100998035039
                # -------------------------------------------------
                if line.lstrip().startswith("902"):
                    line = prefix.rstrip() + new_token2 + suffix
                else:
                    line = prefix.rstrip() + " " + new_token2 + suffix

            except Exception:
                pass

        else:
            candidate = extract_missing_convention_from_token2(token2)

            if candidate:
                candidate_internal = normalize_mapping_key(candidate)

                if candidate_internal not in mapping:
                    missing_code = candidate_internal

    # -----------------------------------------------------
    # 4️⃣ Remover NIF final
    # -----------------------------------------------------
    line = re.sub(r"\s+\d{9}\s*$", "", line)

    # -----------------------------------------------------
    # 5️⃣ Ajustar comprimento final
    # -----------------------------------------------------
    if len(line) > expected_len:
        line = line[:expected_len]
    elif len(line) < expected_len:
        line = line.ljust(expected_len)

    return line, missing_code


# =========================================================
# 📄 Utilitários de texto
# =========================================================
def split_keep_eol(text: str):
    parts = text.splitlines(keepends=True)
    out = []

    for p in parts:
        if p.endswith("\r\n"):
            out.append((p[:-2], "\r\n"))
        elif p.endswith("\n"):
            out.append((p[:-1], "\n"))
        elif p.endswith("\r"):
            out.append((p[:-1], "\r"))
        else:
            out.append((p, ""))

    return out


def guess_default_eol(text: str) -> str:
    if "\r\n" in text:
        return "\r\n"
    if "\n" in text:
        return "\n"
    if "\r" in text:
        return "\r"
    return "\n"


def register_missing_code(
    code: str,
    filename: str,
    line_number: int,
    original_line: str
):
    if code not in st.session_state.missing_codes:
        st.session_state.missing_codes[code] = {}

    occurrence_key = f"{filename}|{line_number}|{original_line}"

    st.session_state.missing_codes[code][occurrence_key] = {
        "Convencao": convention_for_csv(code),
        "Ficheiro": filename,
        "Linha": line_number,
        "Conteudo da linha": original_line
    }


# =========================================================
# 📤 Construir CSV atualizado
# =========================================================
def build_updated_mapping_dataframe() -> pd.DataFrame:
    if st.session_state.mapping_df is None:
        return pd.DataFrame(
            columns=[MAPPING_HEADER_CONV, MAPPING_HEADER_ENTITY]
        )

    df = st.session_state.mapping_df.copy()

    existing_internal_codes = set(
        df[MAPPING_HEADER_CONV]
        .astype(str)
        .apply(normalize_mapping_key)
        .tolist()
    )

    rows_to_add = []

    for conv_internal, entity_code in st.session_state.mapping_dict.items():
        if conv_internal not in existing_internal_codes:
            rows_to_add.append({
                MAPPING_HEADER_CONV: convention_for_csv(conv_internal),
                MAPPING_HEADER_ENTITY: normalize_entity_value(entity_code)
            })

    if rows_to_add:
        df_new = pd.DataFrame(rows_to_add)
        df = pd.concat([df, df_new], ignore_index=True)

    return df


def build_mapping_csv_bytes() -> bytes:
    df = build_updated_mapping_dataframe()

    csv_text = df.to_csv(
        index=False,
        sep=MAPPING_SEPARATOR,
        encoding="utf-8-sig",
        lineterminator="\n"
    )

    return csv_text.encode("utf-8-sig")


# =========================================================
# 🎨 Interface
# =========================================================
st.set_page_config(page_title="Conversor MCDT", layout="wide")
st.title("🏥 Conversor MCDT / Termas — com deteção de convenções em falta")

# ---------------------------------------------------------
# Carregar mapping inicial
# ---------------------------------------------------------
if not st.session_state.mapping_dict:
    mapping_dict, mapping_df = load_default_mapping(MAPPING_PATH)
    st.session_state.mapping_dict = mapping_dict
    st.session_state.mapping_df = mapping_df

mapping_dict = st.session_state.mapping_dict

st.success(f"✅ Mapeamentos ativos: {len(mapping_dict)}")

# ---------------------------------------------------------
# Botões de controlo
# ---------------------------------------------------------
col_a, col_b = st.columns([1, 2])

with col_a:
    if st.button("🔄 Recarregar mapeamento original"):
        st.cache_data.clear()

        mapping_dict, mapping_df = load_default_mapping(MAPPING_PATH)

        st.session_state.mapping_dict = mapping_dict
        st.session_state.mapping_df = mapping_df
        st.session_state.missing_codes = {}

        st.rerun()

with col_b:
    if st.button("🧹 Limpar lista de convenções em falta"):
        st.session_state.missing_codes = {}
        st.rerun()

# ---------------------------------------------------------
# Upload ficheiros
# ---------------------------------------------------------
uploaded_files = st.file_uploader(
    "📂 Submeter ficheiros",
    accept_multiple_files=True
)

# =========================================================
# 🚀 PROCESSAMENTO
# =========================================================
if uploaded_files:
    for f in uploaded_files:
        content = f.read()

        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                text = content.decode("latin-1")

        default_eol = guess_default_eol(text)
        lines = split_keep_eol(text)

        total = len(lines)
        progress = st.progress(0)

        processed = []
        missing_found_in_file = set()
        invalid_lengths = []

        for i, (line_body, eol) in enumerate(lines):

            if not line_body.strip():
                processed.append(line_body + eol)
                continue

            new_line, missing_code = transform_line(
                line_body,
                mapping_dict,
                expected_len=FINAL_LINE_LENGTH
            )

            if len(new_line) != FINAL_LINE_LENGTH:
                invalid_lengths.append((i + 1, len(new_line), repr(new_line)))

            if missing_code:
                missing_found_in_file.add(missing_code)

                register_missing_code(
                    code=missing_code,
                    filename=f.name,
                    line_number=i + 1,
                    original_line=line_body
                )

            processed.append(new_line + eol)

            if i % 500 == 0 or i == total - 1:
                progress.progress((i + 1) / total)

        progress.progress(1.0)

        output = "".join(processed)

        if not output.endswith(("\n", "\r\n", "\r")):
            output += default_eol

        st.success(f"✅ {f.name} convertido")

        if invalid_lengths:
            st.error(
                f"⚠️ Foram encontradas {len(invalid_lengths)} linhas "
                f"com comprimento diferente de {FINAL_LINE_LENGTH} caracteres."
            )

            for erro in invalid_lengths[:10]:
                st.code(str(erro))
        else:
            st.caption(
                f"Todas as linhas úteis foram ajustadas para "
                f"{FINAL_LINE_LENGTH} caracteres."
            )

        if missing_found_in_file:
            st.warning(
                f"⚠️ Neste ficheiro foram encontradas "
                f"{len(missing_found_in_file)} convenções sem mapeamento."
            )

        st.download_button(
            f"📥 Download {f.name}",
            output.encode("latin-1"),
            f"CORRIGIDO_{f.name}",
            "text/plain",
            key=f"download_{f.name}"
        )

# =========================================================
# 🧠 UI de atualização dos mapeamentos
# =========================================================
if st.session_state.missing_codes:

    st.divider()
    st.warning("⚠️ Convenções detetadas sem mapeamento")

    total_missing_codes = len(st.session_state.missing_codes)
    total_occurrences = sum(
        len(occurrences)
        for occurrences in st.session_state.missing_codes.values()
    )

    st.write(
        f"Foram identificadas **{total_missing_codes} convenções distintas** "
        f"sem mapeamento, em **{total_occurrences} ocorrências**."
    )

    all_missing_rows = []

    for code, occurrences in st.session_state.missing_codes.items():
        for record in occurrences.values():
            all_missing_rows.append(record)

    if all_missing_rows:
        df_missing = pd.DataFrame(all_missing_rows)
        df_missing = df_missing.sort_values(
            by=["Convencao", "Ficheiro", "Linha"],
            ascending=[True, True, True]
        )

        st.subheader("📋 Linhas onde foram encontradas convenções sem mapeamento")

        st.dataframe(
            df_missing,
            use_container_width=True,
            hide_index=True
        )

    st.subheader("✍️ Atualizar mapeamentos em falta")

    new_entries = {}

    for code_internal in sorted(st.session_state.missing_codes.keys()):
        occurrences_count = len(st.session_state.missing_codes[code_internal])
        code_display = convention_for_csv(code_internal)

        col1, col2, col3 = st.columns([1.2, 2, 1.2])

        with col1:
            st.markdown(f"**Convenção:** `{code_display}`")

        with col2:
            val = st.text_input(
                f"Entidade para {code_display}",
                key=f"input_entity_{code_internal}",
                placeholder="Introduzir código da entidade",
                label_visibility="collapsed"
            )

            if val:
                val_clean = normalize_entity_value(val)

                if val_clean:
                    new_entries[code_internal] = val_clean

        with col3:
            st.caption(f"{occurrences_count} ocorrência(s)")

    if st.button("💾 Guardar novos mapeamentos na sessão"):
        if not new_entries:
            st.warning("⚠️ Não foi preenchido qualquer código de entidade.")
        else:
            for conv_code_internal, entity_code in new_entries.items():
                st.session_state.mapping_dict[conv_code_internal] = entity_code

                if conv_code_internal in st.session_state.missing_codes:
                    del st.session_state.missing_codes[conv_code_internal]

            st.success(
                f"✅ Foram adicionados {len(new_entries)} mapeamentos à sessão. "
                f"Já podem ser usados ao voltar a processar os ficheiros."
            )
            st.rerun()

# =========================================================
# 📤 Exportação SEGURA do CSV atualizado
# =========================================================
st.divider()
st.subheader("📤 Exportar mapeamentos atualizados")

st.info(
    "O ficheiro exportado mantém o formato correto: "
    "`Cod. Convencao;Cod. Entidade`. "
    "É construído a partir do CSV original e apenas acrescenta os novos mapeamentos introduzidos nesta sessão."
)

csv_export = build_mapping_csv_bytes()

st.download_button(
    "📥 Download mapeamentos_atualizado.csv",
    csv_export,
    "mapeamentos_atualizado.csv",
    "text/csv"
)
