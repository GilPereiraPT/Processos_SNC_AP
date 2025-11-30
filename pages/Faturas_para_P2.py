import io
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List

import numpy as np
import pandas as pd
import streamlit as st
import fitz  # PyMuPDF
import cv2
from PIL import Image

# ============================================================
# Funções auxiliares de formatação
# ============================================================

def formatar_data_ddmmaaaa(valor: str) -> str:
    """Converte várias formas de data para DD/MM/AAAA."""
    if not valor:
        return ""
    valor = valor.strip()
    # Adicionada validação básica de comprimento para evitar processamento inútil
    if len(valor) < 8: 
        return valor
        
    formatos = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y%m%d"]
    for fmt in formatos:
        try:
            dt = datetime.strptime(valor, fmt)
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            continue
            
    # Tentar regex se o parse direto falhar
    m = re.search(r"(\d{2})[./-](\d{2})[./-](\d{4})", valor)
    if m:
        try:
            dt = datetime.strptime(f"{m.group(1)}/{m.group(2)}/{m.group(3)}", "%d/%m/%Y")
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            pass
            
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", valor)
    if m:
        try:
            dt = datetime.strptime(f"{m.group(1)}-{m.group(2)}-{m.group(3)}", "%Y-%m-%d")
            return dt.strftime("%d/%m/%Y")
        except ValueError:
            pass
            
    return valor


def normalizar_monetario(valor: str) -> str:
    """Devolve sempre formato PT: 1234,56."""
    if not valor:
        return ""
    # Remove símbolos de moeda e espaços
    v = re.sub(r"[^\d.,]", "", valor)
    
    # Se já estiver no formato PT simples (ex: 10,50 ou 100)
    if "," in v and "." not in v:
        return v
    
    # Se tiver pontos e virgulas, assumimos que o último separador é o decimal
    if "." in v or "," in v:
        last_sep_index = max(v.rfind('.'), v.rfind(','))
        inteiro = v[:last_sep_index].replace(".", "").replace(",", "")
        decimal = v[last_sep_index+1:]
        return f"{inteiro},{decimal}"
        
    return v


# ============================================================
# PDF / QR (Melhorado)
# ============================================================

def abrir_pdf_bytes(file_bytes: bytes):
    return fitz.open(stream=file_bytes, filetype="pdf")


def primeira_pagina_para_cv2(doc) -> np.ndarray:
    """
    Renderiza a primeira página com ZOOM (2x ou 3x) para melhorar a leitura do QR.
    """
    page = doc.load_page(0)
    # AUMENTO DE RESOLUÇÃO: zoom de 2.0 (200%) é crucial para QRs densos
    matriz = fitz.Matrix(2.0, 2.0) 
    pix = page.get_pixmap(matrix=matriz)
    
    mode = "RGBA" if pix.alpha else "RGB"
    img_pil = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
    
    if img_pil.mode == "RGBA":
        img_pil = img_pil.convert("RGB")
        
    img_cv2 = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
    return img_cv2


def ler_qr_imagem(doc) -> Optional[str]:
    """Tenta ler QR a partir da 1ª página como imagem com pré-processamento."""
    try:
        img_cv2 = primeira_pagina_para_cv2(doc)
    except Exception:
        return None

    detector = cv2.QRCodeDetector()
    
    # 1. Tentativa normal
    data, points, _ = detector.detectAndDecode(img_cv2)
    if data: return data.strip()
    
    # 2. Tentativa com escala de cinzentos (ajuda o algoritmo)
    gray = cv2.cvtColor(img_cv2, cv2.COLOR_BGR2GRAY)
    data, points, _ = detector.detectAndDecode(gray)
    if data: return data.strip()
    
    # 3. Tentativa com binarização (alto contraste)
    _, thresh = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY)
    data, points, _ = detector.detectAndDecode(thresh)
    if data: return data.strip()

    return None


def extrair_qr_string_do_texto(texto: str) -> Optional[str]:
    """Procura string AT (A:PT*B:...) diretamente no texto do PDF."""
    # O padrão foi ligeiramente ajustado para ser mais flexível com espaços
    pattern = r"A:(PT)?\s*[\|*]\s*B:[^\r\n]+"
    m = re.search(pattern, texto)
    if m:
        return m.group(0).strip()
    return None


def parse_qr_at(data: str) -> dict:
    """Divide a string AT do QR em campos A:, B:, C:, D:, E:, ..."""
    if not data:
        return {}
    # Deteta o separador automaticamente (* ou |)
    sep = "*" if "*" in data else "|"
    
    # Remove "A:" inicial se estiver colado
    if data.startswith("A:") and sep not in data[0:5]:
        # Caso raro de formatação incorreta, mas tenta seguir
        pass

    partes = data.split(sep)
    res: dict[str, str] = {}
    for parte in partes:
        parte = parte.strip()
        if ":" not in parte:
            continue
        k, v = parte.split(":", 1)
        k = k.strip().upper() # Garante que a chave é maiúscula
        v = v.strip()
        if k:
            res[k] = v
    return res


def numero_fatura_de_c(campo_c: str) -> str:
    """Extrai número da fatura limpo do campo C."""
    if not campo_c:
        return ""
    # Remove prefixos comuns como FT, FS, FR, espaço
    limpo = re.sub(r"^[A-Z]{2}\s*", "", campo_c) 
    
    # Tenta padrão SÉRIE/NUMERO
    m = re.search(r"(\d+)[/\-](\d+)", limpo)
    if m:
        return m.group(1) + m.group(2)
        
    # Fallback: apenas dígitos
    digitos = re.findall(r"(\d+)", limpo)
    return "".join(digitos) if digitos else limpo


def detetar_tipo_documento(campo_c: str, texto: str, filename: str) -> str:
    tipo_map = {
        "FT": "Fatura",
        "FS": "Fatura Simplificada",
        "FR": "Fatura-Recibo",
        "NC": "Nota de Crédito",
        "ND": "Nota de Débito",
        "VD": "Venda a Dinheiro",
        "RC": "Recibo",
    }

    # 1) Pelo QR (campo C) - Os primeiros caracteres do campo C costumam ser o tipo
    if campo_c:
        # Tenta apanhar as duas primeiras letras (ex: "FT 2024/1")
        m = re.match(r"\s*([A-Z]{2})", campo_c)
        if m:
            cod = m.group(1)
            if cod in tipo_map:
                return tipo_map[cod]

    # 2) Pelo texto
    txt = texto.lower()
    if "nota de crédito" in txt or "nota de credito" in txt: return "Nota de Crédito"
    if "fatura-recibo" in txt or "fatura recibo" in txt: return "Fatura-Recibo"
    if "venda a dinheiro" in txt: return "Venda a Dinheiro"
    if "fatura simplificada" in txt: return "Fatura Simplificada"
    if "nota de débito" in txt or "nota de debito" in txt: return "Nota de Débito"
    if "recibo" in txt and "fatura" not in txt: return "Recibo"
    if "fatura" in txt or "factura" in txt: return "Fatura" # Genérico, no fim

    # 3) Pelo nome do ficheiro (fallback)
    nome = filename.lower()
    if "credito" in nome: return "Nota de Crédito"
    if "recibo" in nome: return "Recibo"
    return "Fatura" # Default seguro


# ============================================================
# Extração por texto
# ============================================================

def extrair_texto_doc(doc) -> str:
    texto_total: List[str] = []
    for page in doc:
        texto_total.append(page.get_text("text")) # text simples preserva alguma ordem
    return "\n".join(texto_total)


def extrair_nif_texto(texto: str, filename: str) -> str:
    # 1. Tentar filename primeiro (geralmente mais limpo se o user o nomeou)
    base = Path(filename).stem
    m = re.search(r"(?:NIF)?\s*([1235689][0-9]{8})", base, flags=re.IGNORECASE)
    if m: return m.group(1)

    texto_norm = texto.replace("\n", " ")
    
    # 2. Padrões específicos com label
    padroes = [
        r"Contribuinte:?\s*([1235689][0-9]{8})",
        r"NIF:?\s*PT\s*([1235689][0-9]{8})",
        r"NIF:?\s*([1235689][0-9]{8})",
        r"Fiscal:?\s*([1235689][0-9]{8})",
    ]
    for p in padroes:
        m = re.search(p, texto_norm, flags=re.IGNORECASE)
        if m: return m.group(1)

    # 3. Procura "selvagem" de 9 dígitos, excluindo casos óbvios de telefone (iniciados por 91, 92, 93, 96, 21, 22)
    # Nota: NIFs de empresas começam por 5, pessoas por 1, 2, 3 (raro), ENIs por 1 ou 2.
    # Esta regex tenta filtrar telemóveis comuns
    todos = re.findall(r"\b([1256][0-9]{8})\b", texto_norm)
    if todos:
        # Retorna o primeiro que encontrar (geralmente o do emissor vem no cabeçalho)
        return todos[0]
        
    return ""


def extrair_data_texto(texto: str) -> str:
    texto_norm = texto.replace("\n", " ")

    # Padrão mais forte primeiro: Data de Emissão
    m = re.search(r"Data\s+(?:de\s+)?Emiss[aã]o[:\s]*(\d{2}[./-]\d{2}[./-]\d{4})", texto_norm, flags=re.IGNORECASE)
    if m: return formatar_data_ddmmaaaa(m.group(1))
    
    m = re.search(r"(\d{4}-\d{2}-\d{2})", texto_norm) # Formato ISO costuma ser data
    if m: return formatar_data_ddmmaaaa(m.group(1))

    # Procura datas genéricas
    datas = re.findall(r"\b(\d{2}[./-]\d{2}[./-]\d{4})\b", texto_norm)
    if datas:
        # Se houver várias, normalmente a data da fatura é a primeira ou a mais recente
        return formatar_data_ddmmaaaa(datas[0])

    return ""


def extrair_total_texto(texto: str) -> str:
    texto_norm = texto.replace("\n", " ")
    
    padroes = [
        r"Total\s+a\s+Pagar.*?(\d{1,3}(?:\.\d{3})*,\d{2})", # Formato PT com ponto milhar
        r"Total\s+Geral.*?(\d+,\d{2})",
        r"Total\s+\(EUR\).*?(\d+,\d{2})",
        r"Total.*?(\d+,\d{2})\s*€", # Total seguido de euro
    ]
    
    for p in padroes:
        m = re.search(p, texto_norm, flags=re.IGNORECASE)
        if m: return normalizar_monetario(m.group(1))
        
    return ""


def extrair_numero_fatura_texto(texto: str, nif: str) -> str:
    # Lógica mantida, mas refinada para evitar anos isolados
    def validar_candidato(num):
        num = num.strip()
        if len(num) < 3 or len(num) > 20: return False
        if nif and num == nif: return False
        if re.match(r"^(202[3-6])$", num): return False # É apenas o ano
        return True

    linhas = texto.splitlines()
    candidatos = []

    for linha in linhas:
        if re.search(r"fatura|factura|invoice|FT|FS|FR", linha, flags=re.IGNORECASE):
            # Procura padrão Serie/Num
            m = re.search(r"([a-zA-Z0-9]+)\s*[/\-]\s*(\d+)", linha)
            if m:
                cand = m.group(1) + m.group(2)
                # Remove letras se o utilizador quiser apenas digitos, mas aqui guardamos série
                # Para limpar só digitos:
                cand_dig = "".join(filter(str.isdigit, cand))
                if validar_candidato(cand_dig):
                    candidatos.append(cand_dig)

    if candidatos:
        # Escolhe o mais longo (assumindo que num faturas > num sequenciais curtos)
        return max(candidatos, key=len)
    return ""


def extrair_nota_encomenda(texto: str) -> str:
    texto_norm = texto.replace("\n", " ")
    # Busca por "Vossa encomenda", "Requisição", "Pedido"
    padroes = [
        r"(?:Vossa\s+)?Encomenda[:\s\.]*(\d{3,15})",
        r"(?:Vossa\s+)?Requisi[cç][aã]o[:\s\.]*(\d{3,15})",
        r"O\/Ref[:\s\.]*(\d{3,15})", # O/Ref (Our Reference / Vossa Referência)
    ]
    for p in padroes:
        m = re.search(p, texto_norm, flags=re.IGNORECASE)
        if m: return m.group(1)
    return ""


# ============================================================
# Processamento de um PDF
# ============================================================

def processar_pdf(nome_ficheiro: str, ficheiro_bytes: bytes) -> dict:
    doc = abrir_pdf_bytes(ficheiro_bytes)
    texto = extrair_texto_doc(doc)

    origem = "Texto (Regex)"
    campos_qr = {}
    qr_raw = ""

    # 1. Tentar QR String no texto (MUITO rápido e preciso se existir)
    qr_str = extrair_qr_string_do_texto(texto)
    if qr_str:
        campos_qr = parse_qr_at(qr_str)
        origem = "QR (Texto Oculto)"
        qr_raw = qr_str
    
    # 2. Se falhar, tentar QR via Imagem (CV2)
    if not campos_qr:
        qr_img = ler_qr_imagem(doc)
        if qr_img:
            # Validação simples se parece um QR da AT
            if "A:" in qr_img and ("B:" in qr_img or "H:" in qr_img):
                campos_qr = parse_qr_at(qr_img)
                origem = "QR (Imagem)"
                qr_raw = qr_img

    # Inicializar dados
    nif = ""
    data = ""
    total = ""
    num_fatura = ""
    tipo_doc = ""
    nota_enc = ""

    # 3. Preencher dados
    if campos_qr:
        # Dados via QR são autoritativos
        nif = campos_qr.get("B", "")
        if not nif: nif = campos_qr.get("A", "").replace("PT","") # As vezes vem no A
        
        data = formatar_data_ddmmaaaa(campos_qr.get("F", "") or campos_qr.get("D", "")) # F costuma ser data documento
        total = normalizar_monetario(campos_qr.get("O", "") or campos_qr.get("E", "") or campos_qr.get("M", "")) # O: Total Bruto
        
        # Tipo documento e numero
        campo_c = campos_qr.get("C", "")
        num_fatura = numero_fatura_de_c(campo_c)
        tipo_doc = detetar_tipo_documento(campo_c, texto, nome_ficheiro)
        
        # Nota de encomenda não vem no QR, tentar extrair do texto
        nota_enc = extrair_nota_encomenda(texto)

    else:
        # Fallback Texto
        nif = extrair_nif_texto(texto, nome_ficheiro)
        data = extrair_data_texto(texto)
        total = extrair_total_texto(texto)
        num_fatura = extrair_numero_fatura_texto(texto, nif)
        tipo_doc = detetar_tipo_documento("", texto, nome_ficheiro)
        nota_enc = extrair_nota_encomenda(texto)

    return {
        "Ficheiro": nome_ficheiro,
        "Origem": origem,
        "Tipo": tipo_doc,
        "NIF Emissor": nif,
        "Data": data,
        "Total": total,
        "Num. Fatura": num_fatura,
        "Encomenda": nota_enc,
        "Debug QR": qr_raw
    }


# ============================================================
# UI Streamlit
# ============================================================

st.set_page_config(page_title="Processar Faturas P2", layout="wide")

st.title("📄 Processador de Faturas (AT Portugal)")
st.markdown("""
Esta ferramenta extrai dados de faturas PDF para contabilidade.  
Prioridade de leitura: **QR Code (AT)** > **Texto do PDF**.
""")

col1, col2 = st.columns([2, 1])

with col1:
    uploaded_files = st.file_uploader(
        "Arraste as faturas para aqui (PDF)",
        type=["pdf"],
        accept_multiple_files=True,
    )

if uploaded_files:
    if st.button("🚀 Iniciar Processamento", type="primary"):
        progress_bar = st.progress(0)
        registos = []
        
        for i, f in enumerate(uploaded_files):
            try:
                # O read() move o cursor, importante resetar se usarmos várias vezes, 
                # mas aqui passamos bytes diretos
                reg = processar_pdf(f.name, f.read())
                registos.append(reg)
            except Exception as e:
                st.error(f"Erro ao processar {f.name}: {e}")
            
            # Atualizar barra
            progress_bar.progress((i + 1) / len(uploaded_files))
            
        progress_bar.empty()

        if registos:
            df = pd.DataFrame(registos)
            
            # Reordenar colunas
            cols = ["Ficheiro", "NIF Emissor", "Data", "Total", "Num. Fatura", "Tipo", "Encomenda", "Origem", "Debug QR"]
            # Garante que só usa colunas que existem
            cols = [c for c in cols if c in df.columns]
            df = df[cols]

            st.success(f"{len(registos)} documentos processados com sucesso.")
            
            # Métricas rápidas
            c1, c2, c3 = st.columns(3)
            com_qr = df[df["Origem"].str.contains("QR")].shape[0]
            c1.metric("Lidos via QR", com_qr)
            c2.metric("Lidos via Texto", len(registos) - com_qr)
            
            st.dataframe(df, use_container_width=True)

            # --- Downloads ---
            col_d1, col_d2 = st.columns(2)
            
            buffer_xlsx = io.BytesIO()
            with pd.ExcelWriter(buffer_xlsx, engine="openpyxl") as writer:
                df.to_excel(writer, index=False)
            buffer_xlsx.seek(0)
            
            col_d1.download_button(
                label="📥 Download Excel",
                data=buffer_xlsx,
                file_name=f"faturas_export_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

            csv_data = df.to_csv(index=False, sep=";").encode("utf-8-sig")
            col_d2.download_button(
                label="📥 Download CSV",
                data=csv_data,
                file_name=f"faturas_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                use_container_width=True
            )
else:
    st.info("Aguardando ficheiros...")
