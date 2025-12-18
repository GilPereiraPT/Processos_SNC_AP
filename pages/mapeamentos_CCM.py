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
        # Deteta automaticamente ; ou , (essencial para o ficheiro no GitHub)
        df = pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")
        mapping = {}
        c_col, e_col = df.columns[0], df.columns[1]
        for _, row in df.iterrows():
            c = re.sub(r"\D", "", str(row[c_col])).zfill(6)
            e = str(row[e_col]).strip().replace(".0", "").replace(" ", "")
            if c and e and e.lower() != "nan":
                mapping[c] = e
        return mapping, df
    except Exception:
        return {}, None

# ==============================
# Lógica de Transformação Rígida
# ==============================

def transform_line(line: str, mapping: Dict[str, str]) -> str:
    # 1. Ajuste Coluna 12 (Posição 11) - Substituição direta
    if len(line) >= 12 and line[11] == "0":
        line = line[:11] + " " + line[12:]

    # 2. Corrigir CC "+93  " -> "+9197" (mantendo o tamanho se possível)
    line = re.sub(r"\+93\s\s", "+9197", line)

    # 3. Substituição de Entidade mantendo Alinhamento de Colunas
    # Procuramos o segundo bloco (onde reside a convenção/entidade)
    m = re.search(r"^(\S+)(\s+)(\S+)", line)
    if m:
        token2 = m.group(3)
        start_pos = m.start(3)
        end_pos = m.end(3)
        
        # Identificar qual a convenção do mapeamento está presente no token
        matched_conv = None
        sorted_convs = sorted(mapping.keys(), key=len, reverse=True)
        for c_code in sorted_convs:
            if c_code in token2:
                matched_conv = c_code
                break

        if matched_conv:
            ent_code = mapping[matched_conv]
            try:
                ent7 = f"{int(ent_code):07d}"
                
                # Para não desalinhara a linha, a substituição tem de ser cirúrgica.
                # Se a entidade (7) é maior que a convenção (6), temos de verificar 
                # se há um zero à esquerda para absorver a diferença.
                idx = token2.find(matched_conv)
                
                if idx > 0 and token2[idx-1] == '0':
                    # Substituímos "0" + "convenção" (7 caracteres) por "entidade" (7 caracteres)
                    new_token2 = token2[:idx-1] + ent7 + token2[idx+len(matched_conv):]
                else:
                    # Se não houver zero para absorver, substituímos a convenção e 
                    # removemos um espaço do separador seguinte para compensar o aumento
                    new_token2 = token2[:idx] + ent7 + token2[idx+len(matched_conv):]
                
                # Reconstrução da linha com verificação de comprimento
                diff = len(new_token2) - len(token2)
                if diff > 0:
                    # Se o token cresceu, cortamos o excesso nos espaços que o seguem
                    post_content = line[end_pos:]
                    line = line[:start_pos] + new_token2 + post_content[diff:]
                else:
                    line = line[:start_pos] + new_token2 + line[end_pos:]
                    
            except ValueError:
                pass

    # 4. Remover NIF (9 dígitos) no fim mantendo os espaços anteriores
    line = re.sub(r"(\s)\d{9}$", r"\1", line)
    
    return line

# ==============================
# UI Streamlit
# ==============================

st.set_page_config(page_title="Conversor MCDT (Formato Rígido)", layout="wide")
st.title("Conversor de ficheiros MCDT/Termas")

mapping_dict, _ = load_default_mapping("mapeamentos.csv")

if not mapping_dict:
    st.error("ERRO: Ficheiro 'mapeamentos.csv' não detetado.")
else:
    st.success(f"Mapeamento carregado: {len(mapping_dict)} códigos.")
    
    uploaded_files = st.file_uploader("Submeta ficheiros para conversão individual", accept_multiple_files=True)

    if uploaded_files:
        for f in uploaded_files:
            content = f.read()
            try:
                text = content.decode("utf-8")
            except:
                text = content.decode("latin-1")
            
            # Processamento que garante que o comprimento da linha é respeitado
            lines = text.splitlines()
            processed = [transform_line(l, mapping_dict) for l in lines]
            output = "\n".join(processed) + "\n"
            
            st.download_button(
                label=f"📥 Guardar {f.name}",
                data=output.encode("utf-8"),
                file_name=f"CORRIGIDO_{f.name}",
                mime="text/plain",
                key=f.name
            )
