# -*- coding: utf-8 -*-
"""
Conversor MCDT / Termas + Centros de Custo
Fluxo:
1) Recebe 1 ZIP principal protegido por password.
2) Abre automaticamente ZIPs interiores.
3) Converte todos os TXT com as regras MCDT/Termas.
4) Se o TXT começar por INF_, aplica depois a conversão de Centros de Custo.
5) Devolve cada TXT individualmente, sem criar ZIP final.
"""

import io
import re
import zipfile
from typing import Dict, Tuple, Optional, List

import pandas as pd
import streamlit as st


# =========================================================
# ⚙️ Configuração
# =========================================================
ZIP_PASSWORD = b"r9hG72LGG9Kf"

MAPPING_PATH = "mapeamentos.csv"
MAPPING_SEPARATOR = ";"
MAPPING_HEADER_CONV = "Cod. Convencao"
MAPPING_HEADER_ENTITY = "Cod. Entidade"


# =========================================================
# 📘 Mapeamento Centros de Custo
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

# Regra específica validada
MAPEAMENTO_CC["1030111"] = "12702301"


# =========================================================
# ⚙️ Estado global
# =========================================================
if "mapping_dict" not in st.session_state:
    st.session_state.mapping_dict = {}

if "mapping_df" not in st.session_state:
    st.session_state.mapping_df = None

if "missing_codes" not in st.session_state or not isinstance(
    st.session_state.missing_codes, dict
):
    st.session_state.missing_codes = {}

if "processed_outputs" not in st.session_state:
    st.session_state.processed_outputs = []

if "processing_report" not in st.session_state:
    st.session_state.processing_report = []


# =========================================================
# ⚙️ Funções auxiliares de normalização
# =========================================================
def normalize_mapping_key(value: str) -> str:
    digits = re.sub(r"\D", "", str(value))
    return digits.zfill(6) if digits else ""


def normalize_entity_value(value: str) -> str:
    return re.sub(r"\D", "", str(value))


def convention_for_csv(value: str) -> str:
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return ""
    return str(int(digits))


# =========================================================
# ⚙️ Carregar mapeamentos
# =========================================================
@st.cache_data(ttl=3600)
def load_default_mapping(
    path: str = MAPPING_PATH
) -> Tuple[Dict[str, str], Optional[pd.DataFrame]]:
    try:
        df = pd.read_csv(
            path,
            sep=MAPPING_SEPARATOR,
            encoding="utf-8-sig",
            dtype=str,
            keep_default_na=False,
        )

        required_columns = [MAPPING_HEADER_CONV, MAPPING_HEADER_ENTITY]

        if list(df.columns[:2]) != required_columns:
            raise ValueError(
                "O CSV de mapeamentos não tem o formato esperado. "
                f"Esperado: {MAPPING_HEADER_CONV};{MAPPING_HEADER_ENTITY}"
            )

        df = df[[MAPPING_HEADER_CONV, MAPPING_HEADER_ENTITY]].copy()
        df[MAPPING_HEADER_CONV] = (
            df[MAPPING_HEADER_CONV].astype(str).str.strip()
        )
        df[MAPPING_HEADER_ENTITY] = (
            df[MAPPING_HEADER_ENTITY].astype(str).str.strip()
        )

        mapping = {}

        for _, row in df.iterrows():
            conv_csv = str(row[MAPPING_HEADER_CONV]).strip()
            entity = normalize_entity_value(row[MAPPING_HEADER_ENTITY])
            conv_internal = normalize_mapping_key(conv_csv)

            if conv_internal and entity:
                mapping[conv_internal] = entity

        return mapping, df

    except Exception as e:
        st.error(f"❌ Erro ao carregar mapeamento: {e}")
        return {}, None


# =========================================================
# 🔍 Regras de layout por código de ficheiro
# =========================================================
def get_file_code(line: str) -> str:
    return line[:3] if len(line) >= 3 else ""


def get_token2_rule(file_code: str, token2: str) -> dict:
    if file_code == "702":
        return {
            "name": "medicamentos",
            "convert_len": 6,
            "has_leading_zero": False,
        }

    if file_code in {"902", "903", "904", "906"}:
        return {
            "name": "mcdt_termas",
            "convert_len": 7,
            "has_leading_zero": True,
        }

    if re.match(r"^0\d{6}", token2):
        return {
            "name": "auto_0_6",
            "convert_len": 7,
            "has_leading_zero": True,
        }

    return {
        "name": "auto_6",
        "convert_len": 6,
        "has_leading_zero": False,
    }


def extract_missing_convention_from_token2(
    token2: str,
    file_code: str
) -> Optional[str]:
    rule = get_token2_rule(file_code, token2)
    convert_len = rule["convert_len"]

    if len(token2) < convert_len:
        return None

    parte_convertivel = token2[:convert_len]

    if rule["has_leading_zero"]:
        match = re.match(r"^0(\d{6})$", parte_convertivel)
        if match:
            return match.group(1)
        return None

    match = re.match(r"^(\d{6})$", parte_convertivel)
    if match:
        return match.group(1)

    return None


def find_mapping_for_token2(
    token2: str,
    mapping: Dict[str, str],
    file_code: str
) -> Optional[str]:
    candidate = extract_missing_convention_from_token2(
        token2,
        file_code
    )

    if not candidate:
        return None

    candidate_internal = normalize_mapping_key(candidate)

    if candidate_internal in mapping:
        return candidate_internal

    return None


# =========================================================
# 🧩 Transformação MCDT / Termas
# =========================================================
def transform_line(
    line: str,
    mapping: Dict[str, str],
    expected_len: int = None
):
    original_len = len(line)

    if expected_len is None:
        expected_len = original_len

    missing_code = None

    # 1) Corrigir coluna 12
    if len(line) >= 12 and line[11] == "0":
        line = line[:11] + " " + line[12:]

    # 2) Corrigir CC técnico existente nesta etapa
    line = re.sub(r"\+93\s\s", "+9197", line)

    # 3) Processar token 2
    file_code = get_file_code(line)
    parts = line.split(maxsplit=2)

    if len(parts) >= 2:
        token2 = parts[1]
        rule = get_token2_rule(file_code, token2)
        convert_len = rule["convert_len"]

        matched_conv = find_mapping_for_token2(
            token2,
            mapping,
            file_code
        )

        if matched_conv:
            ent_code = mapping[matched_conv]

            try:
                ent7 = f"{int(ent_code):07d}"
                parte_fixa = token2[convert_len:]
                new_token2 = ent7 + parte_fixa

                if (
                    file_code in {"903", "904", "906"}
                    and new_token2.startswith("0")
                ):
                    new_token2 = new_token2[1:]

                if len(new_token2) < len(token2):
                    new_token2 = new_token2.ljust(len(token2))

                pos = line.find(token2)
                prefix = line[:pos]
                suffix = line[pos + len(token2):]

                line = prefix.rstrip() + " " + new_token2 + suffix

            except Exception:
                pass

        else:
            candidate = extract_missing_convention_from_token2(
                token2,
                file_code
            )

            if candidate:
                candidate_internal = normalize_mapping_key(candidate)

                if candidate_internal not in mapping:
                    missing_code = candidate_internal

    # 4) Remover NIF final
    line = re.sub(r"\s\d{9}\s*$", " ", line)

    # 5) Manter comprimento final
    if len(line) > expected_len:
        line = line[:expected_len]
    elif len(line) < expected_len:
        line = line.ljust(expected_len)

    return line, missing_code


# =========================================================
# 📄 Utilitários de texto
# =========================================================
def split_keep_eol(text: str):
    parts = text.splitlines(keepends=True)
    out = []

    for p in parts:
        if p.endswith("\r\n"):
            out.append((p[:-2], "\r\n"))
        elif p.endswith("\n"):
            out.append((p[:-1], "\n"))
        elif p.endswith("\r"):
            out.append((p[:-1], "\r"))
        else:
            out.append((p, ""))

    return out


def guess_default_eol(text: str) -> str:
    if "\r\n" in text:
        return "\r\n"
    if "\n" in text:
        return "\n"
    if "\r" in text:
        return "\r"
    return "\n"


def decode_text_bytes(content: bytes):
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError:
            pass

    return content.decode("latin-1"), "latin-1"


def register_missing_code(
    code: str,
    filename: str,
    line_number: int,
    original_line: str
):
    if code not in st.session_state.missing_codes:
        st.session_state.missing_codes[code] = {}

    occurrence_key = (
        f"{filename}|{line_number}|{original_line}"
    )

    st.session_state.missing_codes[code][occurrence_key] = {
        "Convencao": convention_for_csv(code),
        "Ficheiro": filename,
        "Linha": line_number,
        "Conteudo da linha": original_line,
    }


# =========================================================
# 🛠️ Processar MCDT em bytes
# =========================================================
def processar_mcdt_bytes(
    content: bytes,
    filename: str,
    mapping: Dict[str, str]
):
    text, encoding = decode_text_bytes(content)

    default_eol = guess_default_eol(text)
    lines = split_keep_eol(text)

    processed = []
    missing_found = set()

    for i, (line_body, eol) in enumerate(lines):
        if not line_body.strip():
            processed.append(line_body + eol)
            continue

        new_line, missing_code = transform_line(
            line_body,
            mapping
        )

        if missing_code:
            missing_found.add(missing_code)

            register_missing_code(
                code=missing_code,
                filename=filename,
                line_number=i + 1,
                original_line=line_body,
            )

        processed.append(new_line + eol)

    output = "".join(processed)

    if output and not output.endswith(
        ("\n", "\r\n", "\r")
    ):
        output += default_eol

    # IMPORTANTE:
    # Nunca devolver BOM UTF-8 nos TXT finais.
    # Alguns sistemas interpretam os bytes EF BB BF como "Ï»¿"
    # no início da primeira referência e rejeitam o ficheiro.
    if encoding == "utf-8-sig":
        output_bytes = output.encode(
            "utf-8",
            errors="replace"
        )
    else:
        output_bytes = output.encode(
            encoding,
            errors="replace"
        )

    # Segurança adicional: remover BOM caso ainda exista
    if output_bytes.startswith(b"\xef\xbb\xbf"):
        output_bytes = output_bytes[3:]

    return output_bytes, missing_found


# =========================================================
# 🧩 Conversão Centros de Custo
# =========================================================
def _split_eol_bytes(line_b: bytes):
    if line_b.endswith(b"\r\n"):
        return line_b[:-2], b"\r\n"
    if line_b.endswith(b"\n"):
        return line_b[:-1], b"\n"
    if line_b.endswith(b"\r"):
        return line_b[:-1], b"\r"
    return line_b, b""


def _find_last_sign_pos(body: bytes) -> int:
    core = body

    # Ignorar NIF final, se existir
    if (
        len(core) >= 10
        and core[-10:-9] == b" "
        and core[-9:].isdigit()
    ):
        core = core[:-10] + b" "

    return max(
        core.rfind(b"+"),
        core.rfind(b"-")
    )


def corrigir_linha_cc_bytes(line_b: bytes):
    body, eol = _split_eol_bytes(line_b)
    orig_len = len(body)

    sign_pos = _find_last_sign_pos(body)

    if sign_pos < 0 or sign_pos + 1 >= len(body):
        return line_b, None, None, "SEM_SINAL"

    start = sign_pos + 1
    end = start

    while (
        end < len(body)
        and body[end:end + 1] != b" "
    ):
        end += 1

    cc_old_b = body[start:end]

    if not cc_old_b or not cc_old_b.isdigit():
        return line_b, None, None, "CC_INVALIDO"

    cc_old = cc_old_b.decode("ascii")
    cc_new = MAPEAMENTO_CC.get(cc_old, "9197")
    cc_new_b = cc_new.encode("ascii")

    field_len = end - start

    if len(cc_new_b) > field_len:
        extra = len(cc_new_b) - field_len

        if (
            end + extra <= len(body)
            and body[end:end + extra]
            == (b" " * extra)
        ):
            end += extra
            field_len += extra
        else:
            cc_new_b = cc_new_b[:field_len]

    if len(cc_new_b) < field_len:
        cc_new_b = cc_new_b.ljust(
            field_len,
            b" "
        )
    elif len(cc_new_b) > field_len:
        cc_new_b = cc_new_b[:field_len]

    new_body = (
        body[:start]
        + cc_new_b
        + body[end:]
    )

    if len(new_body) != orig_len:
        if len(new_body) < orig_len:
            new_body = new_body.ljust(
                orig_len,
                b" "
            )
        else:
            new_body = new_body[:orig_len]

    status = (
        "OK"
        if cc_old in MAPEAMENTO_CC
        else "FALLBACK"
    )

    return (
        new_body + eol,
        cc_old,
        cc_new,
        status
    )


def processar_centros_custo_bytes(data: bytes):
    linhas = data.splitlines(keepends=True)

    out = []

    stats = {
        "total": 0,
        "ok": 0,
        "fallback": 0,
        "sem_sinal": 0,
        "cc_invalido": 0,
    }

    for line_b in linhas:
        new_b, old, new, status = (
            corrigir_linha_cc_bytes(line_b)
        )

        out.append(new_b)
        stats["total"] += 1

        if status == "OK":
            stats["ok"] += 1
        elif status == "FALLBACK":
            stats["fallback"] += 1
        elif status == "SEM_SINAL":
            stats["sem_sinal"] += 1
        elif status == "CC_INVALIDO":
            stats["cc_invalido"] += 1

    if (
        out
        and not out[-1].endswith(
            (b"\n", b"\r")
        )
    ):
        out[-1] += b"\n"

    final_data = b"".join(out)

    # Segurança: o ficheiro final nunca deve conter BOM UTF-8
    if final_data.startswith(b"\xef\xbb\xbf"):
        final_data = final_data[3:]

    return final_data, stats


# =========================================================
# 📦 Leitura segura de ZIPs
# =========================================================
def read_zip_member(
    zf: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    password: Optional[bytes] = None
) -> bytes:
    """
    Tenta ler primeiro sem password e,
    se necessário, usa a password fixa.
    """
    try:
        return zf.read(info)
    except RuntimeError:
        if password:
            return zf.read(
                info,
                pwd=password
            )
        raise


def extrair_txts_de_zip_bytes(
    zip_bytes: bytes,
    origem: str,
    password: Optional[bytes] = None
) -> List[Tuple[str, bytes, str]]:
    """
    Extrai TXT de um ZIP.
    Se encontrar ZIPs dentro dele, entra recursivamente.

    Retorna:
        [(nome_txt, bytes_txt, caminho_origem), ...]
    """
    encontrados = []

    with zipfile.ZipFile(
        io.BytesIO(zip_bytes),
        "r"
    ) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue

            nome = info.filename
            nome_lower = nome.lower()

            data = read_zip_member(
                zf,
                info,
                password
            )

            if nome_lower.endswith(".txt"):
                encontrados.append(
                    (
                        nome.split("/")[-1],
                        data,
                        origem,
                    )
                )

            elif nome_lower.endswith(".zip"):
                encontrados.extend(
                    extrair_txts_de_zip_bytes(
                        data,
                        origem=f"{origem} > {nome}",
                        password=password,
                    )
                )

    return encontrados


# =========================================================
# 📤 Construir CSV atualizado
# =========================================================
def build_updated_mapping_dataframe() -> pd.DataFrame:
    if st.session_state.mapping_df is None:
        return pd.DataFrame(
            columns=[
                MAPPING_HEADER_CONV,
                MAPPING_HEADER_ENTITY,
            ]
        )

    df = st.session_state.mapping_df.copy()

    existing_internal_codes = set(
        df[MAPPING_HEADER_CONV]
        .astype(str)
        .apply(normalize_mapping_key)
        .tolist()
    )

    rows_to_add = []

    for (
        conv_internal,
        entity_code
    ) in st.session_state.mapping_dict.items():

        if conv_internal not in existing_internal_codes:
            rows_to_add.append(
                {
                    MAPPING_HEADER_CONV:
                        convention_for_csv(
                            conv_internal
                        ),
                    MAPPING_HEADER_ENTITY:
                        normalize_entity_value(
                            entity_code
                        ),
                }
            )

    if rows_to_add:
        df_new = pd.DataFrame(
            rows_to_add
        )

        df = pd.concat(
            [df, df_new],
            ignore_index=True
        )

    return df


def build_mapping_csv_bytes() -> bytes:
    df = build_updated_mapping_dataframe()

    csv_text = df.to_csv(
        index=False,
        sep=MAPPING_SEPARATOR,
        lineterminator="\n",
    )

    return csv_text.encode("utf-8-sig")


# =========================================================
# 🚀 Processar ZIP principal
# =========================================================
def processar_zip_principal(
    uploaded_zip,
    mapping_dict
):
    outer_bytes = uploaded_zip.read()

    txts = extrair_txts_de_zip_bytes(
        outer_bytes,
        origem=uploaded_zip.name,
        password=ZIP_PASSWORD,
    )

    outputs = []
    report = []

    if not txts:
        return outputs, report

    total = len(txts)
    progress = st.progress(0.0)

    for idx, (
        filename,
        content,
        origem
    ) in enumerate(txts):

        # 1) Conversão MCDT / Termas
        mcdt_bytes, missing_found = (
            processar_mcdt_bytes(
                content,
                filename,
                mapping_dict
            )
        )

        final_bytes = mcdt_bytes
        cc_stats = None

        # 2) Apenas INF_ passa por Centros de Custo
        if filename.upper().startswith("INF_"):
            final_bytes, cc_stats = (
                processar_centros_custo_bytes(
                    mcdt_bytes
                )
            )

        outputs.append(
            {
                "filename": filename,
                "data": final_bytes,
                "origem": origem,
                "is_inf": filename.upper().startswith("INF_"),
            }
        )

        report.append(
            {
                "filename": filename,
                "origem": origem,
                "missing": len(missing_found),
                "cc_stats": cc_stats,
            }
        )

        progress.progress(
            (idx + 1) / total
        )

    progress.progress(1.0)

    return outputs, report


# =========================================================
# 🎨 Interface Streamlit
# =========================================================
st.set_page_config(
    page_title="Conversor MCDT / Termas",
    layout="wide"
)

st.title("🏥 Conversor MCDT / Termas")
st.caption(
    "Carregar 1 ZIP protegido → converter TXT automaticamente → "
    "descarregar ficheiro a ficheiro. "
    "Os ficheiros INF_ passam também pela correção de Centros de Custo."
)


# ---------------------------------------------------------
# Carregar mapping inicial
# ---------------------------------------------------------
if not st.session_state.mapping_dict:
    mapping_dict, mapping_df = (
        load_default_mapping(
            MAPPING_PATH
        )
    )

    st.session_state.mapping_dict = (
        mapping_dict
    )

    st.session_state.mapping_df = (
        mapping_df
    )

mapping_dict = st.session_state.mapping_dict

st.success(
    f"✅ Mapeamentos ativos: "
    f"{len(mapping_dict)}"
)


# ---------------------------------------------------------
# Controlos
# ---------------------------------------------------------
col_a, col_b = st.columns([1, 2])

with col_a:
    if st.button(
        "🔄 Recarregar mapeamento original"
    ):
        st.cache_data.clear()

        mapping_dict, mapping_df = (
            load_default_mapping(
                MAPPING_PATH
            )
        )

        st.session_state.mapping_dict = (
            mapping_dict
        )

        st.session_state.mapping_df = (
            mapping_df
        )

        st.session_state.missing_codes = {}
        st.session_state.processed_outputs = []
        st.session_state.processing_report = []

        st.rerun()

with col_b:
    if st.button(
        "🧹 Limpar convenções em falta"
    ):
        st.session_state.missing_codes = {}
        st.rerun()


# ---------------------------------------------------------
# Upload único
# ---------------------------------------------------------
uploaded_zip = st.file_uploader(
    "📦 Selecionar ZIP recebido",
    type=["zip"],
    accept_multiple_files=False,
)


# ---------------------------------------------------------
# Processamento
# ---------------------------------------------------------
if uploaded_zip:
    if st.button(
        "🚀 Converter ficheiros",
        type="primary"
    ):
        st.session_state.processed_outputs = []
        st.session_state.processing_report = []
        st.session_state.missing_codes = {}

        try:
            outputs, report = (
                processar_zip_principal(
                    uploaded_zip,
                    st.session_state.mapping_dict
                )
            )

            st.session_state.processed_outputs = (
                outputs
            )

            st.session_state.processing_report = (
                report
            )

            if not outputs:
                st.warning(
                    "⚠️ Não foram encontrados ficheiros TXT "
                    "no ZIP nem nos ZIPs interiores."
                )

        except zipfile.BadZipFile:
            st.error(
                "❌ O ficheiro submetido ou um ZIP interior "
                "não é um ZIP válido."
            )

        except RuntimeError as e:
            st.error(
                "❌ Não foi possível abrir o ZIP. "
                "Confirme se corresponde ao formato esperado "
                "e se a password continua a ser válida."
            )
            st.exception(e)

        except Exception as e:
            st.error(
                f"❌ Erro no processamento: {e}"
            )
            st.exception(e)


# ---------------------------------------------------------
# Downloads individuais
# ---------------------------------------------------------
if st.session_state.processed_outputs:

    st.divider()
    st.subheader(
        "📥 Ficheiros convertidos"
    )

    st.success(
        f"✅ Foram preparados "
        f"{len(st.session_state.processed_outputs)} "
        f"ficheiro(s) TXT."
    )

    for idx, item in enumerate(
        st.session_state.processed_outputs
    ):
        filename = item["filename"]
        is_inf = item["is_inf"]

        col1, col2 = st.columns(
            [3, 1]
        )

        with col1:
            if is_inf:
                st.markdown(
                    f"**✅ {filename}**  \n"
                    f"MCDT/Termas + Centros de Custo"
                )
            else:
                st.markdown(
                    f"**✅ {filename}**  \n"
                    f"MCDT/Termas"
                )

        with col2:
            st.download_button(
                "📥 Descarregar",
                data=item["data"],
                file_name=filename,
                mime="text/plain",
                key=f"download_txt_{idx}_{filename}",
            )


# ---------------------------------------------------------
# Relatório
# ---------------------------------------------------------
if st.session_state.processing_report:

    st.divider()
    st.subheader(
        "📊 Relatório de processamento"
    )

    for item in (
        st.session_state.processing_report
    ):
        filename = item["filename"]
        missing = item["missing"]
        cc_stats = item["cc_stats"]

        with st.expander(filename):

            if missing:
                st.warning(
                    f"⚠️ {missing} convenção(ões) "
                    f"sem mapeamento."
                )
            else:
                st.success(
                    "✅ Sem convenções em falta."
                )

            if cc_stats:
                st.write(
                    f"**Centros de custo:** "
                    f"{cc_stats['total']:,} linhas"
                )

                st.write(
                    f"✅ Mapeadas: "
                    f"{cc_stats['ok']:,}"
                )

                st.write(
                    f"⚠️ Fallback 9197: "
                    f"{cc_stats['fallback']:,}"
                )

                st.write(
                    f"Sem sinal +/−: "
                    f"{cc_stats['sem_sinal']:,}"
                )

                st.write(
                    f"CC inválido: "
                    f"{cc_stats['cc_invalido']:,}"
                )


# =========================================================
# 🧠 UI de atualização dos mapeamentos
# =========================================================
if st.session_state.missing_codes:

    st.divider()

    st.warning(
        "⚠️ Convenções detetadas sem mapeamento"
    )

    total_missing_codes = len(
        st.session_state.missing_codes
    )

    total_occurrences = sum(
        len(occurrences)
        for occurrences
        in st.session_state.missing_codes.values()
    )

    st.write(
        f"Foram identificadas "
        f"**{total_missing_codes} convenções distintas** "
        f"sem mapeamento, em "
        f"**{total_occurrences} ocorrências**."
    )

    all_missing_rows = []

    for code, occurrences in (
        st.session_state.missing_codes.items()
    ):
        for record in occurrences.values():
            all_missing_rows.append(record)

    if all_missing_rows:
        df_missing = pd.DataFrame(
            all_missing_rows
        )

        df_missing = df_missing.sort_values(
            by=[
                "Convencao",
                "Ficheiro",
                "Linha",
            ],
            ascending=[
                True,
                True,
                True,
            ]
        )

        st.subheader(
            "📋 Linhas com convenções sem mapeamento"
        )

        st.dataframe(
            df_missing,
            use_container_width=True,
            hide_index=True,
        )

    st.subheader(
        "✍️ Atualizar mapeamentos em falta"
    )

    new_entries = {}

    for code_internal in sorted(
        st.session_state.missing_codes.keys()
    ):
        occurrences_count = len(
            st.session_state.missing_codes[
                code_internal
            ]
        )

        code_display = convention_for_csv(
            code_internal
        )

        col1, col2, col3 = st.columns(
            [1.2, 2, 1.2]
        )

        with col1:
            st.markdown(
                f"**Convenção:** "
                f"`{code_display}`"
            )

        with col2:
            val = st.text_input(
                f"Entidade para {code_display}",
                key=(
                    f"input_entity_"
                    f"{code_internal}"
                ),
                placeholder=(
                    "Introduzir código da entidade"
                ),
                label_visibility="collapsed",
            )

            if val:
                val_clean = (
                    normalize_entity_value(
                        val
                    )
                )

                if val_clean:
                    new_entries[
                        code_internal
                    ] = val_clean

        with col3:
            st.caption(
                f"{occurrences_count} "
                f"ocorrência(s)"
            )

    if st.button(
        "💾 Guardar novos mapeamentos na sessão"
    ):
        if not new_entries:
            st.warning(
                "⚠️ Não foi preenchido "
                "qualquer código de entidade."
            )

        else:
            for (
                conv_code_internal,
                entity_code
            ) in new_entries.items():

                st.session_state.mapping_dict[
                    conv_code_internal
                ] = entity_code

                if (
                    conv_code_internal
                    in st.session_state.missing_codes
                ):
                    del (
                        st.session_state.missing_codes[
                            conv_code_internal
                        ]
                    )

            # Forçar novo processamento do ZIP
            st.session_state.processed_outputs = []
            st.session_state.processing_report = []

            st.success(
                f"✅ Foram adicionados "
                f"{len(new_entries)} mapeamentos. "
                f"Volte a clicar em "
                f"'Converter ficheiros'."
            )

            st.rerun()


# =========================================================
# 📤 Exportação do CSV atualizado
# =========================================================
st.divider()
st.subheader(
    "📤 Exportar mapeamentos atualizados"
)

st.info(
    "O ficheiro exportado mantém o formato "
    "`Cod. Convencao;Cod. Entidade`."
)

csv_export = build_mapping_csv_bytes()

st.download_button(
    "📥 Download mapeamentos_atualizado.csv",
    csv_export,
    "mapeamentos_atualizado.csv",
    "text/csv",
)
