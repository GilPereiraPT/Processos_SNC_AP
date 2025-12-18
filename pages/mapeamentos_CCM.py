import io
import re
from typing import Dict, List, Tuple, Optional
import pandas as pd
import streamlit as st

# ==============================
# Funções de mapeamento
# ==============================

@st.cache_data
def load_default_mapping(path: str = "mapeamentos.csv") -> Tuple[Dict[str, str], Optional[pd.DataFrame]]:
    """Carrega o ficheiro mapeamentos.csv automaticamente da raiz do projeto."""
    try:
        # O motor 'python' com sep=None deteta automaticamente ; ou ,
        df = pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")
        
        mapping = {}
        # Assume-se que a Coluna 0 é Convenção e Coluna 1 é Entidade
        c_col, e_col = df.columns[0], df.columns[1]
        
        for _, row in df.iterrows():
            # Limpa e normaliza a convenção para 6 dígitos (ex: 407 -> 000407)
            c = re.sub(r"\D", "", str(row[c_col])).zfill(6)
            # Limpa a entidade (remove espaços e .0 de decimais)
            e = str(row[e_col]).strip().replace(".0", "").replace(" ", "")
            if c and e and e.lower() != "nan":
                mapping[c] = e
        return mapping, df
    except Exception:
        return {}, None

# ==============================
# Lógica de Transformação
# ==============================

def transform_line(line: str, mapping: Dict[str, str]) -> str:
    # 1. Ajuste Coluna 12 (Posição 11)
    # Se for '0', substitui por espaço mantendo o alinhamento
    if len(line) >= 12 and line[11] == "0":
        line = line[:11] + " " + line[12:]

    # 2. Corrigir CC "+93  " -> "+9197"
    line = re.sub(r"\+93\s{2,}", "+9197", line)

    # 3. Mapeamento de Entidades (Preservando a largura fixa)
    # Procuramos o segundo bloco (token2) sem partir o resto da linha com .split()
    m = re.search(r"^(\S+)(\s+)(\S+)", line)
    if m:
        token1, sep, token2 = m.group(1), m.group(2), m.group(3)
        start_token2 = m.start(3)
        end_token2 = m.end(3)
        
        # Lógica de deteção flexível (para casos como o 407 deslocado)
        matched_conv = None
        # Ordenamos as chaves por tamanho para evitar falsos positivos
        sorted_convs = sorted(mapping.keys(), key=len, reverse=True)
        
        # Verificamos se alguma convenção do CSV existe dentro do token2
        for c_code in sorted_convs:
            if c_code in token2:
                matched_conv = c_code
                break

        if matched_conv:
            ent_code = mapping[matched_conv]
            try:
                # Garante que a entidade tem 7 dígitos
                ent7 = f"{int(ent_code):07d}"
                
                # Substitui a convenção pela entidade dentro do token2
                # O .replace(..., 1) garante que só muda a primeira ocorrência
                new_token2 = token2.replace(matched_conv, ent7, 1)
                
                # Reconstroi a linha mantendo os espaços originais e o resto do conteúdo
                line = line[:start_token2] + new_token2 + line[end_token2:]
            except ValueError:
                pass

    # 4. Remover NIF (9 dígitos) no fim da linha precedidos de espaço
    line = re.sub(r"(\s)\d{9}$", r"\1", line)
    
    return line

# ==============================
# Interface Streamlit
# ==============================

st.set_page_config(page_title="Conversor MCDT/Termas", layout="wide")
st.title("Conversor de ficheiros MCDT/Termas")

# Carregamento automático do CSV
mapping_dict, _ = load_default_mapping("mapeamentos.csv")

if not mapping_dict:
    st.error("ERRO: O ficheiro 'mapeamentos.csv' não foi encontrado ou está mal formatado.")
else:
    st.success(f"Mapeamento carregado com sucesso: {len(mapping_dict)} códigos ativos.")
    
    # Upload de múltiplos ficheiros
    uploaded_files = st.file_uploader("Submeta os ficheiros para converter (.txt)", accept_multiple_files=True)

    if uploaded_files:
        st.write("### Ficheiros Prontos:")
        
        for f in uploaded_files:
            # Ler conteúdo com suporte a diferentes encodings
            raw_content = f.read()
            try:
                text = raw_content.decode("utf-8")
            except UnicodeDecodeError:
                text = raw_content.decode("latin-1")
            
            # Processar cada linha individualmente
            lines = text.splitlines()
            processed_lines = [transform_line(l, mapping_dict) for l in lines]
            
            # Gerar o texto final (adicionando a quebra de linha no fim)
            final_txt = "\n".join(processed_lines) + "\n"
            
            # Criar botão de download individual para cada ficheiro
            st.download_button(
                label=f"📥 Guardar {f.name}",
                data=final_txt.encode("utf-8"),
                file_name=f"CORRIGIDO_{f.name}",
                mime="text/plain",
                key=f.name
            )

st.divider()
st.caption("Versão: Coluna 12 corrigida | Busca de Convenção Flexível | Download Individual.")
