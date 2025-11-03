import io
from datetime import datetime
import streamlit as st

st.set_page_config(page_title="Converter Rubricas (col. 80 → 720121)", layout="centered")
st.title("🧾 Conversor de Rubricas (coluna 80) → 720121")

# ==========================
# Parâmetros base
# ==========================
NEW_CODE = "720121"
DEFAULT_FIELD_COL_1BASED = 80

with st.sidebar:
    st.header("⚙️ Opções")
    # Rubrica
    col_1based = st.number_input("Coluna (1-based) onde começa a rubrica", min_value=1, value=DEFAULT_FIELD_COL_1BASED, step=1)
    apenas_prefixo = st.checkbox("Apenas se rubrica começar por '72'", value=False)
    prefixo = "72"

    # Validação de Entidade
    st.subheader("Validação de Entidade (obrigatório)")
    entidade_required = st.checkbox("Validar Entidade = 971010 (coluna 14)", value=True)
    entidade_col_1based = st.number_input("Coluna da Entidade (1-based)", min_value=1, value=14, step=1)
    entidade_val = st.text_input("Valor esperado da Entidade", value="971010")
    entidade_len = st.number_input("Largura do campo da Entidade", min_value=1, value=max(6, len("971010")), step=1)
    entidade_strip = st.checkbox("Ignorar espaços na comparação", value=True)

    # Encodings
    st.subheader("Encodings")
    encoding_in = st.selectbox("Encoding do ficheiro (entrada)", options=["utf-8", "latin-1", "cp1252"], index=0)
    encoding_out = st.selectbox("Encoding de saída", options=["utf-8", "latin-1", "cp1252"], index=0)

st.write(
    "Este utilitário substitui a rubrica que se inicia na **coluna 80 (1-based por omissão)** pelo código **720121** "
    "e **mantém as colunas** (preenchendo com **espaços à direita** se a rubrica antiga tiver mais caracteres). "
    "Só altera linhas cuja **Entidade = 971010 na coluna 14**."
)

uploaded = st.file_uploader("Carrega o ficheiro de texto a converter (.txt)", type=["txt"])
processar = st.button("🔄 Converter")

def get_token_len(line: str, start: int) -> int:
    """Tamanho do bloco contínuo de dígitos a partir de 'start' (0-based)."""
    if start >= len(line) or not line[start].isdigit():
        return 0
    i = start
    n = len(line)
    while i < n and line[i].isdigit():
        i += 1
    return i - start

def entidade_matches(line: str, start_1based: int, length: int, expected: str, ignore_spaces: bool) -> bool:
    """Valida a Entidade numa janela fixa (start_1based, length)."""
    start0 = start_1based - 1
    end0 = start0 + length
    if len(line) < end0:
        return False
    window = line[start0:end0]
    if ignore_spaces:
        window = window.strip()
    return window == expected

def convert_content(
    text: str,
    rubrica_start_col_1based: int,
    only_prefix_72: bool,
    ent_required: bool,
    ent_col_1based: int,
    ent_len: int,
    ent_value: str,
    ent_strip: bool
) -> tuple[str, dict]:
    START = rubrica_start_col_1based - 1  # 0-based
    total = 0
    alteradas = 0
    sem_token = 0
    entidade_ok = 0
    entidade_ko = 0
    exemplos = []

    out_lines = []
    for line in text.splitlines(keepends=True):
        total += 1

        # Validação prévia da Entidade
        if ent_required:
            if entidade_matches(line, ent_col_1based, ent_len, ent_value, ent_strip):
                entidade_ok += 1
            else:
                entidade_ko += 1
                out_lines.append(line)  # não mexe nesta linha
                continue

        # Se a linha não chega à coluna da rubrica, deixa ficar.
        if len(line) <= START:
            out_lines.append(line)
            continue

        # Determinar o token de rubrica (apenas dígitos contíguos)
        tok_len = get_token_len(line, START)
        if tok_len == 0:
            sem_token += 1
            out_lines.append(line)
            continue

        token = line[START : START + tok_len]

        # Se for para exigir prefixo '72'
        if only_prefix_72 and not token.startswith("72"):
            out_lines.append(line)
            continue

        # Contar espaços imediatamente a seguir ao token (parte do mesmo campo)
        i = START + tok_len
        n = len(line)
        spaces_after = 0
        while i < n and line[i] == " ":
            spaces_after += 1
            i += 1

        field_width = tok_len + spaces_after  # largura total do campo (dígitos + espaços do campo)

        # Construir novo conteúdo com o novo código e padding à direita
        needed = len(NEW_CODE)
        width_to_use = max(needed, tok_len)         # nunca menos que o que já lá estava em dígitos
        width_to_use = min(width_to_use, field_width)  # não invadir o campo seguinte

        new_field = NEW_CODE
        if len(new_field) > width_to_use:
            new_field = new_field[:width_to_use]     # truncagem defensiva (improvável)
        elif len(new_field) < width_to_use:
            new_field = new_field + (" " * (width_to_use - len(new_field)))

        old_field = line[START : START + width_to_use]
        new_line = line[:START] + new_field + line[START + width_to_use:]
        out_lines.append(new_line)
        alteradas += 1

        if len(exemplos) < 5:
            exemplos.append((old_field.replace("\n","\\n"), new_field.replace("\n","\\n"), width_to_use))

    summary = {
        "linhas_processadas": total,
        "rubricas_alteradas": alteradas,
        "linhas_sem_rubrica_na_coluna": sem_token,
        "linhas_entidade_ok": entidade_ok,
        "linhas_entidade_nao_ok": entidade_ko,
        "exemplos": exemplos,
    }
    return "".join(out_lines), summary

if processar:
    if not uploaded:
        st.error("Carrega primeiro um ficheiro .txt.")
    else:
        try:
            raw_text = uploaded.read().decode(encoding_in, errors="ignore")
        except Exception as e:
            st.error(f"Não foi possível ler o ficheiro com encoding '{encoding_in}': {e}")
            st.stop()

        with st.spinner("A converter…"):
            new_text, info = convert_content(
                raw_text,
                rubrica_start_col_1based=col_1based,
                only_prefix_72=apenas_prefixo,
                ent_required=entidade_required,
                ent_col_1based=entidade_col_1based,
                ent_len=int(entidade_len),
                ent_value=entidade_val,
                ent_strip=entidade_strip,
            )

        # Resumo
        st.success("Conversão concluída.")
        c1, c2, c3 = st.columns(3)
        c1.metric("Linhas processadas", info["linhas_processadas"])
        c2.metric("Rubricas alteradas", info["rubricas_alteradas"])
        c3.metric("Sem rubrica na coluna", info["linhas_sem_rubrica_na_coluna"])

        d1, d2 = st.columns(2)
        d1.metric("Entidade OK (linha alterável)", info["linhas_entidade_ok"])
        d2.metric("Entidade NÃO OK (linha intacta)", info["linhas_entidade_nao_ok"])

        if info["linhas_entidade_nao_ok"] > 0:
            st.warning(
                "Existem linhas cuja Entidade na coluna indicada **não é** "
                f"'{entidade_val}'. Essas linhas **não foram alteradas**."
            )

        if info["exemplos"]:
            st.subheader("Exemplos (antes → depois)")
            for old_field, new_field, w in info["exemplos"]:
                st.code(f"[{old_field}]  →  [{new_field}]   (largura {w})")

        # Preparar ficheiro para download
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = uploaded.name.rsplit(".", 1)[0]
        out_name = f"{base_name}_720121_{ts}.txt"
        st.download_button(
            "💾 Descarregar ficheiro alterado",
            data=new_text.encode(encoding_out, errors="ignore"),
            file_name=out_name,
            mime="text/plain",
        )

st.caption(
    "Notas: a app respeita a largura do campo da rubrica (preenchendo com espaços à direita). "
    "A alteração só ocorre quando a Entidade (janela fixa) coincide com o valor esperado."
)
