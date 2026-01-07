# -*- coding: utf-8 -*-
"""Página: Conversor de Centros de Custo 2024 ➔ 2025 (v2027.9 - comprimento fixo garantido)"""

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

# ✅ Regra específica pedida:
# +1030111 tem de ser substituído por +12702301
MAPEAMENTO_CC["1030111"] = "12702301"


# =========================================================
# 🧩 Funções (bytes-safe e comprimento fixo)
# =========================================================
def _split_eol(line_b: bytes):
    if line_b.endswith(b"\r\n"):
        return line_b[:-2], b"\r\n"
    if line_b.endswith(b"\n"):
        return line_b[:-1], b"\n"
    if line_b.endswith(b"\r"):
        return line_b[:-1], b"\r"
    return line_b, b""


def _find_last_sign_pos(body: bytes) -> int:
    # Ignorar NIF final (espaço + 9 dígitos) para não “enganar” a procura
    core = body
    if len(core) >= 10 and core[-10:-9] == b" " and core[-9:].isdigit():
        core = core[:-10] + b" "
    return max(core.rfind(b"+"), core.rfind(b"-"))


def corrigir_linha_bytes(line_b: bytes):
    """
    Encontra o CC após o último +/− e substitui por mapeamento.
    Se o novo CC tiver mais dígitos, consome espaços imediatamente a seguir ao CC.
    Mantém o comprimento final igual ao original.
    """
    body, eol = _split_eol(line_b)
    orig_len = len(body)

    sign_pos = _find_last_sign_pos(body)
    if sign_pos < 0 or sign_pos + 1 >= len(body):
        return line_b, None, None, "SEM_SINAL"

    # CC começa logo após o sinal e vai até ao próximo espaço
    start = sign_pos + 1
    end = start
    while end < len(body) and body[end:end+1] != b" ":
        end += 1

    cc_old_b = body[start:end]
    if not cc_old_b or not cc_old_b.isdigit():
        return line_b, None, None, "CC_INVALIDO"

    cc_old = cc_old_b.decode("ascii")
    cc_new = MAPEAMENTO_CC.get(cc_old, "919909")
    cc_new_b = cc_new.encode("ascii")

    field_len = end - start  # comprimento original do CC (ex.: 7)

    # ✅ Se o CC novo for maior, tenta expandir para a direita consumindo espaços
    if len(cc_new_b) > field_len:
        extra = len(cc_new_b) - field_len
        if end + extra <= len(body) and body[end:end+extra] == (b" " * extra):
            end += extra
            field_len += extra
        else:
            # se não houver espaços, truncar para manter comprimento
            cc_new_b = cc_new_b[:field_len]

    # ajustar CC ao tamanho do campo (agora pode ser maior do que o original)
    if len(cc_new_b) < field_len:
        cc_new_b = cc_new_b.ljust(field_len, b" ")
    elif len(cc_new_b) > field_len:
        cc_new_b = cc_new_b[:field_len]

    new_body = body[:start] + cc_new_b + body[end:]

    # 🔒 Garantir comprimento EXACTO do body
    if len(new_body) != orig_len:
        if len(new_body) < orig_len:
            new_body = new_body.ljust(orig_len, b" ")
        else:
            new_body = new_body[:orig_len]

    status = "OK" if cc_new != "919909" else "FALLBACK"
    return new_body + eol, cc_old, cc_new, status


def processar_ficheiro(uploaded_file):
    data = uploaded_file.read()  # bytes
    linhas = data.splitlines(keepends=True)

    out = []
    total = 0
    ok = 0
    fallback = 0
    sem_sinal = 0
    cc_invalido = 0

    # amostras para debug
    samples = []

    for line_b in linhas:
        new_b, old, new, status = corrigir_linha_bytes(line_b)
        out.append(new_b)
        total += 1

        if status == "OK":
            ok += 1
        elif status == "FALLBACK":
            fallback += 1
        elif status == "SEM_SINAL":
            sem_sinal += 1
            if len(samples) < 5:
                samples.append((status, line_b[:180]))
        elif status == "CC_INVALIDO":
            cc_invalido += 1
            if len(samples) < 5:
                samples.append((status, line_b[:180]))

    # ✅ Garantir newline no fim (ERP)
    if out and not out[-1].endswith((b"\n", b"\r")):
        out[-1] = out[-1] + b"\n"

    return b"".join(out), total, ok, fallback, sem_sinal, cc_invalido, samples


# =========================================================
# 🖥️ Interface Streamlit
# =========================================================
st.set_page_config(page_title="Conversor de Centros de Custo 2024 ➔ 2025", layout="wide")
st.title("🛠️ Conversor de Centros de Custo 2024 ➔ 2025 — v2027.9")
st.caption("Mantém comprimento fixo. Substitui CC após o último +/−. Se o novo CC for maior, consome espaços a seguir. Fallback: '919909'.")

uploaded_files = st.sidebar.file_uploader(
    "📂 Selecionar ficheiros TXT", type=["txt"], accept_multiple_files=True
)

if uploaded_files:
    st.success(f"{len(uploaded_files)} ficheiro(s) carregado(s). Pronto para processar!")

    if st.button("🚀 Iniciar Conversão"):
        log = []
        progress_bar = st.progress(0.0)

        if len(uploaded_files) == 1:
            uf = uploaded_files[0]
            out_b, total, ok, fallback, sem_sinal, cc_invalido, samples = processar_ficheiro(uf)

            novo_nome = uf.name.replace(".txt", "_CORRIGIDO.txt")
            st.sidebar.download_button(
                "📥 Descarregar TXT Corrigido",
                data=io.BytesIO(out_b),
                file_name=novo_nome,
                mime="text/plain",
            )
            progress_bar.progress(1.0)

            st.info(f"📊 Total de linhas: {total:,}")
            st.success(f"✅ Linhas com mapeamento: {ok:,}")
            st.warning(f"⚠️ Fallback '919909': {fallback:,}")
            st.error(f"❌ Sem sinal +/− encontrado: {sem_sinal:,}")
            st.error(f"❌ CC inválido após sinal: {cc_invalido:,}")

            if samples:
                with st.expander("🔎 Amostras de linhas problemáticas (primeiros 180 bytes)"):
                    for status, chunk in samples:
                        st.write(status, chunk)

        else:
            buffer_zip = io.BytesIO()
            total_all = ok_all = fallback_all = sem_sinal_all = cc_inv_all = 0

            with zipfile.ZipFile(buffer_zip, "w") as zipf:
                for idx, uf in enumerate(uploaded_files):
                    out_b, total, ok, fallback, sem_sinal, cc_invalido, _ = processar_ficheiro(uf)
                    novo_nome = uf.name.replace(".txt", "_CORRIGIDO.txt")
                    zipf.writestr(novo_nome, out_b)

                    total_all += total
                    ok_all += ok
                    fallback_all += fallback
                    sem_sinal_all += sem_sinal
                    cc_inv_all += cc_invalido

                    progress_bar.progress((idx + 1) / len(uploaded_files))
                    log.append(
                        f"✅ {uf.name} — ok:{ok} fallback:{fallback} sem_sinal:{sem_sinal} cc_invalido:{cc_invalido}"
                    )

            buffer_zip.seek(0)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            nome_zip = f"ficheiros_corrigidos_{timestamp}.zip"

            st.sidebar.download_button(
                "📦 Descarregar ZIP Corrigido",
                data=buffer_zip,
                file_name=nome_zip,
                mime="application/zip",
            )

            st.info(f"📊 Total de linhas: {total_all:,}")
            st.success(f"✅ Linhas com mapeamento: {ok_all:,}")
            st.warning(f"⚠️ Fallback '919909': {fallback_all:,}")
            st.error(f"❌ Sem sinal +/−: {sem_sinal_all:,}")
            st.error(f"❌ CC inválido: {cc_inv_all:,}")

            st.subheader("📋 Relatório por ficheiro:")
            for l in log:
                st.write(l)

else:
    st.info("👈 Seleciona ficheiros .TXT para iniciar a conversão.")
