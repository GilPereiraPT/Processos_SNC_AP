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
    try:
        df = pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")
        mapping = {}
        c_col, e_col = df.columns[0], df.columns[1]
        for _, row in df.iterrows():
            # Convenção com 6 dígitos (ex: 000407)
            c = re.sub(r"\D", "", str(row[c_col])).zfill(6)
            # Entidade limpa
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
    # Se for '0', vira espaço. O tamanho da linha mantém-se.
    if len(line) >= 12 and line[11] == "0":
        line = line[:11] + " " + line[12:]

    # 2. Corrigir CC "+93  " -> "+9197"
    line = re.sub(r"\+93\s{2,}", "+9197", line)

    # 3. Mapeamento de Entidades (Preservação Absoluta de Largura)
    # Procuramos o segundo bloco onde está a convenção/entidade
    m = re.search(r"^(\S+)(\s+)(\S+)", line)
    if m:
        token2 = m.group(3)
        start_token2 = m.start(3)
        
        # Identificar qual a convenção que está no token2
        matched_conv = None
        # Ordenamos para garantir que apanha o código mais longo primeiro
        sorted_convs = sorted(mapping.keys(), key=len, reverse=True)
        
        for c_code in sorted_convs:
            if c_code in token2:
                matched_conv = c_code
                break

        if matched_conv:
            ent_code = mapping[matched_conv]
            try:
                # Criamos a entidade de 7 dígitos
                ent7 = f"{int(ent_code):07d}"
                
                # A chave para o alinhamento:
                # Em vez de apenas substituir o texto, vamos reconstruir o campo
                # com base na posição. Se o token original tinha X caracteres,
                # o novo tem de ter exatamente os mesmos X caracteres.
                
                pos_in_token = token2.find(matched_conv)
                
                # Caso o código 407 venha com zeros à esquerda (ex: 0000407)
                # Ocupamos o espaço da convenção com a entidade de 7 dígitos.
                # Se a entidade for maior que a convenção, temos de "comer" um zero à esquerda
                # para que a data não se desloque.
                
                if matched_conv == "000407" and token2[pos_in_token-1:pos_in_token] == "0":
                    # Se houver um zero antes do 407, substituímos "0000407" (7 chars) por ent7 (7 chars)
                    new_token2 = (token2[:pos_in_token-1] + 
                                 ent7 + 
                                 token2[pos_in_token + len(matched_conv):])
                else:
                    # Substituição padrão
                    new_token2 = (token2[:pos_in_token] + 
                                 ent7 + 
                                 token2[pos_in_token + len(matched_conv):])
                
                # Ajuste final: Se o novo token for mais comprido que o original,
                # removemos a diferença nos espaços que o seguem para manter o alinhamento.
                diff = len(new_token2) - len(token2)
                
                if diff == 0:
                    # Alinhamento perfeito
                    line = line[:start_token2] + new_token2 + line[m.end(3):]
                else:
                    # Se cresceu, cortamos os espaços à frente
                    rest_of_line = line[m.end(3):]
                    line = line[:start_token2] + new_token2 + rest_of_line[diff:]
                    
            except ValueError:
                pass

    # 4. Remover NIF no fim
    line = re.sub(r"(\s)\d{9}$", r"\1", line)
    
    return line

# ==============================
# UI Streamlit
# ==============================

st.set_page_config(page_title="Conversor MCDT/Termas", layout="wide")
st.title("Conversor de ficheiros MCDT/Termas")

mapping_dict, _ = load_default_mapping("mapeamentos.csv")

if not mapping_dict:
    st.error("ERRO: Ficheiro 'mapeamentos.csv' não encontrado.")
else:
    st.success(f"Mapeamento carregado: {len(mapping_dict)} códigos.")
    
    files = st.file_uploader("Submeta ficheiros .txt", accept_multiple_files=True)

    if files:
        for f in files:
            content = f.read()
            try:
                text = content.decode("utf-8")
            except:
                text = content.decode("latin-1")
            
            # Processamento rigoroso
            processed = [transform_line(l, mapping_dict) for l in text.splitlines()]
            output = "\n".join(processed) + "\n"
            
            st.download_button(
                label=f"📥 Guardar {f.name}",
                data=output.encode("utf-8"),
                file_name=f"CORRIGIDO_{f.name}",
                mime="text/plain",
                key=f.name
            )
