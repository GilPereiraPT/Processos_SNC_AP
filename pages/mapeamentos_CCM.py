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
        # sep=None deteta ; ou , automaticamente
        df = pd.read_csv(path, sep=None, engine="python", encoding="utf-8-sig")
        
        mapping = {}
        # Usamos as duas primeiras colunas independentemente do nome
        c_col, e_col = df.columns[0], df.columns[1]
        
        for _, row in df.iterrows():
            # Normaliza convenção para 6 dígitos
            c = re.sub(r"\D", "", str(row[c_col])).zfill(6)
            # Limpa entidade
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
    # 1. Ajuste Coluna 12 (Obrigatório: posição 11)
    if len(line) >= 12 and line[11] == "0":
        line = line[:11] + " " + line[12:]

    s = line.rstrip("\n\r")
    
    # 2. Corrigir CC "+93  " -> "+9197"
    s = re.sub(r"\+93\s{2,}", "+9197", s)

    # 3. Mapeamento de campos (Lógica de Tokens)
    # Procuramos o 2º bloco de texto (token2)
    parts = s.split(maxsplit=2)
    if len(parts) >= 2:
        token1, token2 = parts[0], parts[1]
        rest = s[s.find(token2) + len(token2):]
        sep = s[len(token1):s.find(token2)]

        # --- CORREÇÃO PARA O CÓDIGO 407 ---
        # Em vez de ler os primeiros 6, verificamos qual código do CSV está contido no token
        matched_conv = None
        # Ordenamos por tamanho descendente para evitar que '00040' apanhe '000407'
        sorted_keys = sorted(mapping.keys(), key=len, reverse=True)
        
        for conv_code in sorted_keys:
            if conv_code in token2:
                matched_conv = conv_code
                break
        
        if matched_conv:
            ent_code = mapping[matched_conv]
            try:
                ent7 = f"{int(ent_code):07d}"
                # Substituímos a convenção detetada pela entidade de 7 dígitos
                # Mantemos o resto do token2 (o sufixo/cauda)
                # No caso do 0000407..., ele identifica o 000407 e substitui
                new_token2 = token2.replace(matched_conv, ent7, 1)
                s = token1 + sep + new_token2 + rest
            except ValueError:
                pass

    # 4. Remover NIF no fim (9 dígitos precedidos de espaço)
    s = re.sub(r"(\s)\d{9}$", r"\1", s)
    
    return s

# ==============================
# UI Streamlit
# ==============================

st.set_page_config(page_title="Conversor de ficheiros MCDT/Termas", layout="wide")
st.title("Conversor de ficheiros MCDT/Termas")

mapping_dict, _ = load_default_mapping("mapeamentos.csv")

if not mapping_dict:
    st.error("Erro: Ficheiro 'mapeamentos.csv' não encontrado ou inválido.")
else:
    st.success(f"Mapeamento ativo: {len(mapping_dict)} códigos carregados.")
    
    files = st.file_uploader("Submeter ficheiros .txt", accept_multiple_files=True)

    if files:
        for f in files:
            content = f.read()
            try:
                text = content.decode("utf-8")
            except:
                text = content.decode("latin-1")
            
            lines = text.splitlines()
            processed = [transform_line(l, mapping_dict) for l in lines]
            output = "\n".join(processed) + "\n"
            
            st.download_button(
                label=f"📥 Descarregar {f.name}",
                data=output.encode("utf-8"),
                file_name=f"CORRIGIDO_{f.name}",
                mime="text/plain",
                key=f.name
            )
