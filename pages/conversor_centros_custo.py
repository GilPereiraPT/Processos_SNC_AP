# -*- coding: utf-8 -*-
"""Página: Conversor de Centros de Custo 2024 ➔ 2025 (v2027.6 - bytes safe)"""

import streamlit as st
import zipfile
import io
from datetime import datetime

# =========================================================
# 📘 Tabela de Mapeamento Completa (2024 ➜ 2025)
# =========================================================
MAPEAMENTO_CC = {
    '10101': '11001',
    '11002': '11002',
    '102012': '1110101',
    '102013': '1110102',
    '102015': '11121',
    '102021': '11201',
    '102022': '1120801',
    '102023': '1120802',
    '102017': '11501',
    '102031': '11601',
    '102041': '12106',
    '102043': '12123',
    '102046': '12128',
    '102045': '12131',
    '102049': '12198',
    '10208': '1219901',
    '102044': '1219909',
    '1020511': '12201101',
    '1020512': '12201102',
    '1020513': '12201103',
    '1020514': '12201104',
    '1020521': '12201201',
    '1020524': '12201202',
    '1020522': '12201203',
    '1020523': '12201204',
    '1020601': '12302',
    '1020602': '12303',
    '1020603': '12306',
    '1020625': '1231201',
    '1020620': '1231202',
    '1020605': '12315',
    '1020606': '12316',
    '1020607': '12320',
    '1020608': '12321',
    '1020609': '12322',
    '1020626': '12327',
    '10206111': '1233001',
    '10206112': '1233002',
    '10206113': '1233003',
    '10206114': '1233004',
    '1020612': '12331',
    '1020613': '12332',
    '1020614': '1233301',
    '1020631': '1233302',
    '1020615': '12334',
    '1020616': '12335',
    '1020624': '123361',
    '1020627': '12339',
    '1020617': '12340',
    '1020618': '1234801',
    '1020628': '1234802',
    '1020629': '12398',
    '1020604': '1239901',
    '1020610': '1239902',
    '1020621': '1239903',
    '1020619': '1239904',
    '1020623': '1239905',
    '10206221': '123990601',
    '10206222': '123990602',
    '10206223': '123990603',
    '10206224': '123990604',
    '102073': '12505',
    '102074': '12515',
    '102071': '1252901',
    '102072': '1252902',
    '102076': '12531',
    '102075': '12532',
    '102077': '12537',
    '102079': '12598',
    '1030431': '1270102401',
    '1030111': '12702101',
    '1030112': '12702102',
    '1030113': '12702103',
    '1030115': '12702104',
    '1030117': '12702105',
    '1030118': '12702106',
    '1030211': '12702201',
    '1030212': '12702202',
    '1030213': '12702203',
    '1030214': '12702204',
    '1030215': '12702205',
    '1030219': '12702299',
    '1030311': '12702301',
    '1030312': '12702302',
    '1030313': '12702303',
    '1030314': '12702304',
    '1030315': '12702305',
    '1030316': '12702306',
    '1030317': '12702307',
    '1030319': '12702399',
    '1030411': '12702401',
    '1030412': '12702402',
    '10305101': '12702501',
    '10305102': '12702502',
    '10305103': '12702503',
    '10305104': '12702504',
    '10305105': '12702505',
    '10305106': '12702506',
    '10305107': '12702507',
    '10305108': '12702508',
    '10305109': '12702509',
    '10305110': '12702510',
    '10305111': '12702511',
    '10305112': '12702512',
    '10305113': '12702513',
    '10305119': '12702599',
    '1030121': '127030101',
    '1030221': '127030102',
    '1030222': '127030103',
    '1030321': '127030104',
    '1030322': '127030105',
    '1030421': '127030106',
    '1030521': '127030107',
    '1030522': '127030108',
    '9197': '9197',
    '103091': '1270501',
    '103092': '1270502',
    '103093': '1270503',
    '103094': '1270504',
    '103095': '1270505',
    '29902': '1270701',
    '29903': '1270702',
    '29904': '1270703',
    '103061': '12801',
    '103062': '12802',
    '103063': '12803',
    '103064': '12804',
    '103065': '12805',
    '103066': '12806',
    '103067': '12807',
    '103068': '12808',
    '103069': '12809',
    '20101': '201',
    '20201': '202',
    '20301': '20301',
    '20302': '20302',
    '20303': '20303',
    '20401': '20401',
    '20402': '20402',
    '20403': '20403',
    '20404': '20404',
    '20405': '20405',
    '20406': '20406',
    '20407': '20407',
    '20501': '205',
    '21001': '210',
    '21101': '211',
    '21501': '215',
    '21601': '216',
    '22001': '220',
    '24001': '24001',
    '25099': '25001',
    '25001': '25002',
    '25002': '25004',
    '25003': '2500801',
    '25007': '2500802',
    '25005': '25009',
    '25004': '25010',
    '26001': '29902',
    '26002': '29903',
    '26003': '299051',
    '260041': '29906',
    '28001': '29907',
    '29001': '29908',
    '29905': '2990901',
    '29906': '2990902',
    '102011': '29910',
    '29501': '2991101',
    '29502': '2991102',
    '29901': '29913',
    '30101': '301',
    '30201': '303',
    '30202': '304',
    '30203': '305',
    '30301': '306',
    '30302': '309',
    '30303': '310',
    '30204': '311',
    '30304': '312',
    '30305': '313',
    '40101': '4101',
    '40102': '4102',
    '40103': '4103',
    '40104': '4104',
    '40105': '4105',
    '40106': '4106',
    '40107': '4107',
    '40108': '4108',
    '40109': '4109',
    '40110': '4110',
    '40111': '4111',
    '40112': '4112',
    '40201': '4201',
    '402011': '4202',
    '40202': '4203',
    '402021': '4204',
    '40203': '4205',
    '40204': '4206',
    '40205': '4207',
    '40301': '420801',
    '40303': '420802',
    '40304': '420803',
    '40305': '420804',
    '40306': '420805',
    '40309': '420806',
    '40401': '420901',
    '40402': '420902',
    '405': '4210',
    '406': '4211',
    '407': '4212',
    '408': '4213',
    '98': '9101',
    '103071': '919401',
    '103072': '919402',
    '103073': '919403',
    '97': '9197',
    '92': '919901',
    '90403': '919902',
    '90106': '919004',
    '90104': '919909',
    '9194': '9197',
}

# =========================================================
# 🧩 Funções (bytes-safe)
# =========================================================
def corrigir_linha_bytes(linha_b: bytes):
    """
    Substitui o CC mantendo formato fixo (índices fixos) SEM perder bytes.
    Se não existir equivalência, usa sempre '919909'.
    """
    # Precisamos de pelo menos 121+1 bytes para ler sinal/código
    if len(linha_b) <= 121:
        return linha_b, None, None

    sinal = linha_b[120:121]  # 1 byte
    if sinal not in (b'+', b'-'):
        return linha_b, None, None

    inicio = 121
    fim = inicio
    # vai até ao próximo espaço
    while fim < len(linha_b) and linha_b[fim:fim+1] != b' ':
        fim += 1

    codigo_antigo_b = linha_b[inicio:fim].strip()
    if not codigo_antigo_b:
        return linha_b, None, None

    # códigos são dígitos => decode ASCII seguro
    codigo_antigo = codigo_antigo_b.decode("ascii", errors="ignore")
    codigo_novo = MAPEAMENTO_CC.get(codigo_antigo, "919909")

    tamanho_campo = fim - inicio
    codigo_novo_b = codigo_novo.encode("ascii", errors="strict")

    if len(codigo_novo_b) < tamanho_campo:
        codigo_novo_b = codigo_novo_b.ljust(tamanho_campo, b' ')
    elif len(codigo_novo_b) > tamanho_campo:
        codigo_novo_b = codigo_novo_b[:tamanho_campo]

    linha_corrigida = linha_b[:inicio] + codigo_novo_b + linha_b[fim:]

    # garantir comprimento EXACTO
    if len(linha_corrigida) != len(linha_b):
        if len(linha_corrigida) < len(linha_b):
            linha_corrigida = linha_corrigida.ljust(len(linha_b), b' ')
        else:
            linha_corrigida = linha_corrigida[:len(linha_b)]

    return linha_corrigida, codigo_antigo, codigo_novo


def processar_ficheiro(uploaded_file):
    data = uploaded_file.read()  # bytes puros
    linhas = data.splitlines(keepends=True)  # bytes lines, mantém \n/\r\n
    out = []
    total = 0
    fallback_count = 0

    for linha_b in linhas:
        nova_b, antigo, novo = corrigir_linha_bytes(linha_b)
        out.append(nova_b)
        total += 1
        if novo == "919909":
            fallback_count += 1

    # se o ficheiro original não terminava com EOL, alguns ERPs implicam:
    # aqui GARANTIMOS que termina com newline (usa \n se não houver)
    if out and not out[-1].endswith((b"\n", b"\r")):
        out[-1] = out[-1] + b"\n"

    return b"".join(out), total, fallback_count


# =========================================================
# 🖥️ Interface Streamlit
# =========================================================
st.set_page_config(page_title="Conversor de Centros de Custo 2024 ➔ 2025", layout="wide")
st.title("🛠️ Conversor de Centros de Custo 2024 ➔ 2025 — v2027.6")
st.caption("Mantém formato fixo (bytes-safe). Usa sempre '919909' quando não há equivalência.")

uploaded_files = st.sidebar.file_uploader("📂 Selecionar ficheiros TXT", type=["txt"], accept_multiple_files=True)

if uploaded_files:
    st.success(f"{len(uploaded_files)} ficheiro(s) carregado(s). Pronto para processar!")

    if st.button("🚀 Iniciar Conversão"):
        log = []
        progress_bar = st.progress(0)

        if len(uploaded_files) == 1:
            uploaded_file = uploaded_files[0]
            ficheiro_corrigido_b, total, fallback_count = processar_ficheiro(uploaded_file)

            buffer_txt = io.BytesIO(ficheiro_corrigido_b)
            novo_nome = uploaded_file.name.replace(".txt", "_CORRIGIDO.txt")

            st.sidebar.download_button(
                "📥 Descarregar TXT Corrigido",
                data=buffer_txt,
                file_name=novo_nome,
                mime="text/plain",
            )

            log.append(f"✅ {uploaded_file.name} corrigido.")
            progress_bar.progress(1.0)

            st.info(f"📊 Total de linhas: {total:,}")
            st.warning(f"⚠️ Linhas sem equivalência substituídas por '919909': {fallback_count:,}")

        else:
            buffer_zip = io.BytesIO()
            total_fallback = 0
            total_linhas = 0

            with zipfile.ZipFile(buffer_zip, "w") as zipf:
                for idx, uploaded_file in enumerate(uploaded_files):
                    ficheiro_corrigido_b, total, fallback_count = processar_ficheiro(uploaded_file)
                    novo_nome = uploaded_file.name.replace(".txt", "_CORRIGIDO.txt")
                    zipf.writestr(novo_nome, ficheiro_corrigido_b)
                    total_fallback += fallback_count
                    total_linhas += total
                    log.append(f"✅ {uploaded_file.name} corrigido ({fallback_count} substituições '919909').")
                    progress_bar.progress((idx + 1) / len(uploaded_files))

            buffer_zip.seek(0)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            nome_zip = f"ficheiros_corrigidos_{timestamp}.zip"

            st.sidebar.download_button(
                "📦 Descarregar ZIP Corrigido",
                data=buffer_zip,
                file_name=nome_zip,
                mime="application/zip",
            )

            st.info(f"📊 Total de linhas processadas: {total_linhas:,}")
            st.warning(f"⚠️ Linhas sem equivalência substituídas por '919909': {total_fallback:,}")

        st.subheader("📋 Relatório de Operações:")
        for linha in log:
            st.write(linha)
else:
    st.info("👈 Seleciona ficheiros .TXT para iniciar a conversão.")
