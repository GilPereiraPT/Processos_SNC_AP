import streamlit as st
from datetime import datetime

# =========================
# CONFIGURAÇÃO DE COLUNAS (1-BASED)
# =========================
DATE_START_OLD = 52
SHIFT = 3
DATE_START_NEW = 55 

COL_CONTA_CREDITO = 90
# O valor acaba na 119. Se ele for alinhado à esquerda, 
# precisamos de definir onde ele COMEÇA. 
# Assumindo que o campo de valor tem uma largura razoável (ex: 15 chars):
COL_VALOR_START = 105 
COL_VALOR_END = 119

COL_CENTRO_CUSTO = 122

A_EXPECT_1B = 62 
A_PREFIX = "2"
WINDOW = 4

def write_at(chars_list, col_1b, text, fixed_len=None):
    """
    Escreve o texto na lista de caracteres.
    Se fixed_len for definido, limpa essa zona antes de escrever (alinhado à esquerda).
    """
    start_0b = col_1b - 1
    
    # Se tivermos um tamanho fixo, limpamos a zona primeiro
    if fixed_len:
        for i in range(fixed_len):
            if start_0b + i < len(chars_list):
                chars_list[start_0b + i] = " "

    # Escreve o texto
    for i, char in enumerate(text):
        if start_0b + i < len(chars_list):
            if fixed_len and i >= fixed_len: break # Não ultrapassa o limite
            chars_list[start_0b + i] = char

def read_digits(text, start_idx):
    if start_idx >= len(text) or not text[start_idx].isdigit():
        return "", start_idx
    i = start_idx
    while i < len(text) and text[i].isdigit():
        i += 1
    return text[start_idx:i], i

def find_account_pos_simple(core, expect_1b, prefix):
    expect0 = expect_1b - 1
    for delta in range(-WINDOW, WINDOW + 1):
        pos0 = expect0 + delta
        if pos0 < 0: continue
        digits, end = read_digits(core, pos0)
        if digits.startswith(prefix):
            return pos0 + 1, digits, end
    return None, "", 0

def process_line(line: str):
    has_nl = line.endswith("\n")
    original_core = line.rstrip('\n\r')
    
    if len(original_core) < 80:
        return line, {"OK": False, "Info": "Linha Curta"}

    # 1. EXTRAÇÃO
    data_content = original_core[DATE_START_OLD-1 : DATE_START_OLD-1+8]
    a_pos, a_digits, a_end = find_account_pos_simple(original_core, A_EXPECT_1B, A_PREFIX)
    b_digits, _ = read_digits(original_core, COL_CONTA_CREDITO - 1)
    
    # Extraímos o valor (ajusta as colunas de leitura se o valor no original estiver noutro sítio)
    # Aqui leio da 105 à 119 do original como exemplo
    valor_original = original_core[COL_VALOR_START-1 : COL_VALOR_END].strip()
    cc_original = original_core[COL_CENTRO_CUSTO-1 :].strip()

    # 2. RECONSTRUÇÃO
    chars = list(" " * 200)
    
    # Parte inicial
    for i in range(min(DATE_START_OLD - 1, len(original_core))):
        chars[i] = original_core[i]

    # Data na 55
    write_at(chars, DATE_START_NEW, data_content)
    
    if a_pos:
        # Troca: Conta A -> Col 90
        write_at(chars, COL_CONTA_CREDITO, a_digits)
        # Conta B -> Col 65 (A_EXPECT + SHIFT)
        write_at(chars, A_EXPECT_1B + SHIFT, b_digits)
    
    # VALOR: Alinhado à esquerda, terminando na 119
    # Se o campo começa na 105 e termina na 119, tem 15 caracteres
    largura_valor = (COL_VALOR_END - COL_VALOR_START) + 1
    write_at(chars, COL_VALOR_START, valor_original, fixed_len=largura_valor)
    
    # Centro de Custo na 122
    write_at(chars, COL_CENTRO_CUSTO, cc_original)

    final_line = "".join(chars).rstrip()
    return final_line + ("\n" if has_nl else ""), {"OK": a_pos is not None}

# O resto da UI Streamlit permanece igual
