def processar_pdf(nome_ficheiro: str, ficheiro_bytes: bytes) -> dict:
    doc = abrir_pdf_bytes(ficheiro_bytes)

    # texto completo
    texto = extrair_texto_doc(doc)

    origem = "texto"
    nif = ""
    data = ""
    total = ""
    num_fatura = ""
    tipo_doc = ""
    campo_c_qr = ""
    qr_raw = ""

    # 1) tentar obter string AT no texto (mais fiável se existir)
    qr_str = extrair_qr_string_do_texto(texto)
    campos_qr = {}
    if qr_str:
        campos_qr = parse_qr_at(qr_str)
        origem = "qr"
        qr_raw = qr_str
    else:
        # 2) fallback: QR por imagem
        qr_img = ler_qr_imagem(doc)
        if qr_img and "A:" in qr_img and "B:" in qr_img and "C:" in qr_img:
            campos_qr = parse_qr_at(qr_img)
            origem = "qr"
            qr_raw = qr_img

    # 3) Se houver QR AT, usar SEMPRE estes campos (como pediste)
    if campos_qr:
        nif = campos_qr.get("B", "") or ""
        data = formatar_data_ddmmaaaa(campos_qr.get("D", "") or "")
        total = normalizar_monetario(campos_qr.get("E", "") or "")
        campo_c_qr = campos_qr.get("C", "") or ""
        num_fatura = numero_fatura_de_c(campo_c_qr)

        # tipo de documento pode depender de C + texto
        tipo_doc = detetar_tipo_documento(campo_c_qr, texto, nome_ficheiro)
        # nota de encomenda continua a vir do texto
        nota_encomenda = extrair_nota_encomenda(texto)

        return {
            "ficheiro": nome_ficheiro,
            "origem_dados": origem,          # "qr"
            "qr_raw": qr_raw,               # para debug
            "tipo_documento": tipo_doc,
            "nif": nif,
            "data_fatura": data,
            "valor_total": total,
            "numero_fatura_digitos": num_fatura,
            "nota_encomenda": nota_encomenda,
        }

    # 4) Se NÃO houver QR AT, usar TEXTO para tudo (fallback)
    nif = extrair_nif_texto(texto, nome_ficheiro)
    data = extrair_data_texto(texto)
    total = extrair_total_texto(texto)
    num_fatura = extrair_numero_fatura_texto(texto, nif)
    tipo_doc = detetar_tipo_documento("", texto, nome_ficheiro)
    nota_encomenda = extrair_nota_encomenda(texto)

    return {
        "ficheiro": nome_ficheiro,
        "origem_dados": origem,          # "texto"
        "qr_raw": qr_raw,               # vazio neste caso
        "tipo_documento": tipo_doc,
        "nif": nif,
        "data_fatura": data,
        "valor_total": total,
        "numero_fatura_digitos": num_fatura,
        "nota_encomenda": nota_encomenda,
    }
