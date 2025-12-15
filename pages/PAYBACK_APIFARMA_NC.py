def escrever_csv_bytes(linhas: List[List[str]]) -> bytes:
    """
    Escreve CSV em bytes.
    ⚠️ Usa ="valor" para forçar texto e manter zeros à esquerda.
    """
    buffer_text = StringIO()
    writer = csv.writer(buffer_text, delimiter=";", quoting=csv.QUOTE_NONE, escapechar='\\')
    
    writer.writerow(HEADER)
    
    # APENAS estas 4 colunas mantêm zeros à esquerda
    colunas_com_zeros = {
        "Classificador funcional ",
        "Fonte de financiamento ",
        "Programa ",
        "Medida"
    }
    
    for linha in linhas:
        linha_processada = []
        for i, valor in enumerate(linha):
            col_name = HEADER[i]
            
            if col_name in colunas_com_zeros and valor:
                # Usar ="valor" para forçar como texto
                linha_processada.append(f'="{valor}"')
            else:
                linha_processada.append(valor)
        
        writer.writerow(linha_processada)
    
    text_value = buffer_text.getvalue()
    buffer_bytes = BytesIO()
    buffer_bytes.write(text_value.encode("latin-1"))
    buffer_bytes.seek(0)
    return buffer_bytes.read()
