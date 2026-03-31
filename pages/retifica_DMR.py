import io
import re
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import List, Dict, Tuple, Optional

import pandas as pd
import streamlit as st


# ============================================================
# CONFIGURAÇÃO
# ============================================================
# Este ficheiro foi pensado para servir como base de um projeto GitHub
# em Streamlit. A parte mais sensível é o parser da DMR, porque o formato
# do ficheiro pode variar consoante a extração.
#
# O código já suporta dois modos:
# 1) DMR delimitada (CSV/TXT separado por ; , | ou TAB)
# 2) DMR em texto linha-a-linha com parser por expressões regulares
#
# Se a sua DMR tiver posições fixas próprias, basta adaptar a função:
#     parse_dmr_line_custom(...)
# e a função:
#     rebuild_dmr_line_custom(...)
#
# Regras implementadas:
# - procurar NIF do Excel na DMR
# - apenas rendimento base "A"
# - ignorar A21, A22, A23 e semelhantes
# - aplicar Valor e IRS do Excel por soma (como já vêm negativos)
# - nunca permitir resultado negativo
# - gerar:
#   * DMR corrigida
#   * Excel pendentes atualizado
#   * Excel resumo de alterações
# ============================================================

APP_TITLE = "Corretor DMR + Pendentes"
APP_VERSION = "1.0.0"

EXCEL_COL_NIF = "NIF"
EXCEL_COL_REND = "Rendimento"
EXCEL_COL_VALOR = "Valor"
EXCEL_COL_IRS = "IRS"

NEGATIVE_ZERO = Decimal("0.00")
TWOPLACES = Decimal("0.01")


# ============================================================
# UTILITÁRIOS DECIMAIS / TEXTO
# ============================================================
def d(value) -> Decimal:
    """Converte texto/número para Decimal, tolerando formato PT."""
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value
    if pd.isna(value):
        return Decimal("0.00")

    s = str(value).strip()
    if not s:
        return Decimal("0.00")

    s = s.replace("€", "").replace(" ", "")

    # Normalização de formatos: 1.234,56 | 1234,56 | 1234.56
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".")

    try:
        return Decimal(s).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError(f"Valor numérico inválido: {value}")



def fmt_decimal_pt(value: Decimal) -> str:
    value = value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    s = f"{value:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return s



def normalize_nif(v) -> str:
    s = re.sub(r"\D", "", str(v or ""))
    return s.zfill(9) if s else ""



def normalize_rendimento(v: str) -> str:
    return str(v or "").strip().upper()



def is_base_rendimento_a(code: str) -> bool:
    code = normalize_rendimento(code)
    return code == "A"



def is_any_a_variant(code: str) -> bool:
    code = normalize_rendimento(code)
    return code.startswith("A")


# ============================================================
# MODELO DMR
# ============================================================
@dataclass
class DMRRecord:
    line_no: int
    original_line: str
    record_type: str
    nif: str
    rendimento: str
    valor: Decimal
    irs: Decimal
    parsed_ok: bool = True
    source_mode: str = "delimited"
    delimiter: Optional[str] = None
    fields: Optional[List[str]] = None
    field_map: Optional[Dict[str, int]] = None


# ============================================================
# PARSERS DMR
# ============================================================
def detect_delimiter(sample: str) -> Optional[str]:
    candidates = [";", "|", "\t", ","]
    lines = [ln for ln in sample.splitlines()[:10] if ln.strip()]
    if not lines:
        return None

    scores = {}
    for delim in candidates:
        counts = [ln.count(delim) for ln in lines]
        if max(counts, default=0) > 0 and len(set(counts)) <= 2:
            scores[delim] = sum(counts)
    if not scores:
        return None
    return max(scores, key=scores.get)



def find_header_mapping(columns: List[str]) -> Dict[str, int]:
    mapping = {}
    normalized = [c.strip().lower() for c in columns]

    aliases = {
        "record_type": ["tiporegisto", "tipo_registo", "tipo", "record_type", "registo"],
        "nif": ["nif", "nifbeneficiario", "nif_beneficiario", "beneficiario_nif"],
        "rendimento": ["rendimento", "codigorendimento", "codigo_rendimento", "tipo_rendimento"],
        "valor": ["valor", "montante", "importe", "rendimento_valor"],
        "irs": ["irs", "retencao", "retencaoirs", "retencao_irs", "imposto"],
    }

    for key, names in aliases.items():
        for idx, col in enumerate(normalized):
            if col in names:
                mapping[key] = idx
                break

    return mapping



def parse_dmr_delimited(content: str) -> Tuple[List[DMRRecord], Dict[str, str]]:
    delimiter = detect_delimiter(content)
    if not delimiter:
        raise ValueError("Não foi possível detetar delimitador na DMR.")

    lines = content.splitlines()
    non_empty = [ln for ln in lines if ln.strip()]
    if not non_empty:
        raise ValueError("A DMR está vazia.")

    first_fields = [x.strip() for x in non_empty[0].split(delimiter)]
    header_map = find_header_mapping(first_fields)
    has_header = {"nif", "rendimento", "valor", "irs"}.issubset(set(header_map.keys()))

    records: List[DMRRecord] = []
    start_idx = 1 if has_header else 0

    if has_header:
        field_map = header_map
    else:
        # Tentativa de mapeamento posicional default. Ajustar se necessário.
        # Suposição: tipo ; nif ; rendimento ; valor ; irs ; ...
        field_map = {
            "record_type": 0,
            "nif": 1,
            "rendimento": 2,
            "valor": 3,
            "irs": 4,
        }

    for i, line in enumerate(lines, start=1):
        if not line.strip():
            records.append(
                DMRRecord(
                    line_no=i,
                    original_line=line,
                    record_type="",
                    nif="",
                    rendimento="",
                    valor=Decimal("0.00"),
                    irs=Decimal("0.00"),
                    parsed_ok=False,
                    source_mode="delimited",
                    delimiter=delimiter,
                    fields=[],
                    field_map=field_map,
                )
            )
            continue

        logical_idx = len([ln for ln in lines[:i] if ln.strip()]) - 1
        if has_header and logical_idx == 0:
            records.append(
                DMRRecord(
                    line_no=i,
                    original_line=line,
                    record_type="HEADER",
                    nif="",
                    rendimento="",
                    valor=Decimal("0.00"),
                    irs=Decimal("0.00"),
                    parsed_ok=False,
                    source_mode="delimited",
                    delimiter=delimiter,
                    fields=line.split(delimiter),
                    field_map=field_map,
                )
            )
            continue

        fields = [x.strip() for x in line.split(delimiter)]
        try:
            record_type = fields[field_map["record_type"]] if "record_type" in field_map and field_map["record_type"] < len(fields) else "006"
            nif = normalize_nif(fields[field_map["nif"]])
            rendimento = normalize_rendimento(fields[field_map["rendimento"]])
            valor = d(fields[field_map["valor"]])
            irs = d(fields[field_map["irs"]])
            parsed_ok = True
        except Exception:
            record_type = ""
            nif = ""
            rendimento = ""
            valor = Decimal("0.00")
            irs = Decimal("0.00")
            parsed_ok = False

        records.append(
            DMRRecord(
                line_no=i,
                original_line=line,
                record_type=record_type,
                nif=nif,
                rendimento=rendimento,
                valor=valor,
                irs=irs,
                parsed_ok=parsed_ok,
                source_mode="delimited",
                delimiter=delimiter,
                fields=fields,
                field_map=field_map,
            )
        )

    meta = {"mode": "delimited", "delimiter": delimiter}
    return records, meta


# -----------------------------------------------------------------
# PARSER CUSTOMIZÁVEL PARA DMR NÃO DELIMITADA
# -----------------------------------------------------------------
# Este regex é apenas um fallback. Deve ser ajustado à DMR real quando
# se souber a estrutura exata.
DMR_REGEX = re.compile(
    r"^(?P<record_type>\d{3})"
    r".*?(?P<nif>\d{9})"
    r".*?(?P<rendimento>A\d{0,2}[A-Z]?|A)"
    r".*?(?P<valor>-?\d+[\.,]\d{2})"
    r".*?(?P<irs>-?\d+[\.,]\d{2})"
    r".*$"
)



def parse_dmr_line_custom(line: str, line_no: int) -> DMRRecord:
    m = DMR_REGEX.match(line.strip())
    if not m:
        return DMRRecord(
            line_no=line_no,
            original_line=line,
            record_type="",
            nif="",
            rendimento="",
            valor=Decimal("0.00"),
            irs=Decimal("0.00"),
            parsed_ok=False,
            source_mode="custom",
        )

    return DMRRecord(
        line_no=line_no,
        original_line=line,
        record_type=m.group("record_type"),
        nif=normalize_nif(m.group("nif")),
        rendimento=normalize_rendimento(m.group("rendimento")),
        valor=d(m.group("valor")),
        irs=d(m.group("irs")),
        parsed_ok=True,
        source_mode="custom",
    )



def parse_dmr_custom(content: str) -> Tuple[List[DMRRecord], Dict[str, str]]:
    records = [parse_dmr_line_custom(line, idx) for idx, line in enumerate(content.splitlines(), start=1)]
    return records, {"mode": "custom"}



def parse_dmr(content: str) -> Tuple[List[DMRRecord], Dict[str, str]]:
    delimiter = detect_delimiter(content)
    if delimiter:
        try:
            return parse_dmr_delimited(content)
        except Exception:
            pass
    return parse_dmr_custom(content)


# ============================================================
# REBUILD DMR
# ============================================================
def decimal_to_storage_string(value: Decimal) -> str:
    return f"{value.quantize(TWOPLACES, rounding=ROUND_HALF_UP):.2f}"



def rebuild_dmr_line_delimited(record: DMRRecord) -> str:
    if not record.fields or not record.field_map or not record.delimiter:
        return record.original_line

    fields = list(record.fields)
    fmap = record.field_map

    if "valor" in fmap and fmap["valor"] < len(fields):
        fields[fmap["valor"]] = decimal_to_storage_string(record.valor)
    if "irs" in fmap and fmap["irs"] < len(fields):
        fields[fmap["irs"]] = decimal_to_storage_string(record.irs)

    return record.delimiter.join(fields)



def rebuild_dmr_line_custom(record: DMRRecord) -> str:
    # Este método é um fallback genérico.
    # Em DMR real de largura fixa, o ideal é substituir apenas as posições
    # corretas do valor e IRS na string original.
    if not record.parsed_ok:
        return record.original_line

    line = record.original_line

    original_numbers = re.findall(r"-?\d+[\.,]\d{2}", line)
    if len(original_numbers) >= 2:
        line = line.replace(original_numbers[-2], decimal_to_storage_string(record.valor), 1)
        line = line.replace(original_numbers[-1], decimal_to_storage_string(record.irs), 1)
        return line

    return record.original_line



def rebuild_dmr(records: List[DMRRecord], meta: Dict[str, str]) -> str:
    lines = []
    mode = meta.get("mode", "custom")
    for rec in records:
        if mode == "delimited" and rec.source_mode == "delimited":
            lines.append(rebuild_dmr_line_delimited(rec))
        else:
            lines.append(rebuild_dmr_line_custom(rec))
    return "\n".join(lines)


# ============================================================
# LEITURA EXCEL PENDENTES
# ============================================================
def read_excel_pendentes(file_bytes: bytes) -> pd.DataFrame:
    xls = pd.ExcelFile(io.BytesIO(file_bytes))
    df = pd.read_excel(xls, sheet_name=0)

    expected = {EXCEL_COL_NIF, EXCEL_COL_REND, EXCEL_COL_VALOR, EXCEL_COL_IRS}
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(f"Faltam colunas no Excel: {', '.join(sorted(missing))}")

    df = df.copy()
    df[EXCEL_COL_NIF] = df[EXCEL_COL_NIF].apply(normalize_nif)
    df[EXCEL_COL_REND] = df[EXCEL_COL_REND].astype(str).str.strip().str.upper()
    df[EXCEL_COL_VALOR_DEC] = df[EXCEL_COL_VALOR].apply(d)
    df[EXCEL_COL_IRS_DEC] = df[EXCEL_COL_IRS].apply(d)
    df["Estado"] = ""
    df["Linha_DMR"] = ""
    df["Rendimento_DMR"] = ""
    df["Valor_DMR_Original"] = ""
    df["IRS_DMR_Original"] = ""
    df["Valor_DMR_Novo"] = ""
    df["IRS_DMR_Novo"] = ""
    df["Observacoes"] = ""
    return df


# ============================================================
# MOTOR DE CORREÇÃO
# ============================================================
def candidate_dmr_lines(records: List[DMRRecord], nif: str) -> List[DMRRecord]:
    out = []
    for rec in records:
        if not rec.parsed_ok:
            continue
        if rec.record_type and rec.record_type not in {"006", ""}:
            continue
        if rec.nif != nif:
            continue
        out.append(rec)
    return out



def process_pendentes(df: pd.DataFrame, records: List[DMRRecord]) -> Tuple[pd.DataFrame, pd.DataFrame, List[DMRRecord]]:
    resumo_rows = []

    for idx, row in df.iterrows():
        nif = row[EXCEL_COL_NIF]
        rendimento_excel = normalize_rendimento(row[EXCEL_COL_REND])
        valor_excel = row[EXCEL_COL_VALOR_DEC]
        irs_excel = row[EXCEL_COL_IRS_DEC]

        if not nif:
            df.at[idx, "Estado"] = "NIF inválido"
            df.at[idx, "Observacoes"] = "NIF vazio ou inválido"
            continue

        if rendimento_excel != "A":
            df.at[idx, "Estado"] = "Ignorado"
            df.at[idx, "Observacoes"] = "No Excel apenas é tratado rendimento A"
            continue

        if valor_excel == Decimal("0.00") and irs_excel == Decimal("0.00"):
            df.at[idx, "Estado"] = "Ignorado"
            df.at[idx, "Observacoes"] = "Valor e IRS a zero"
            continue

        all_lines = candidate_dmr_lines(records, nif)
        only_a_variants = [r for r in all_lines if is_any_a_variant(r.rendimento)]
        base_a_lines = [r for r in only_a_variants if is_base_rendimento_a(r.rendimento)]

        if not all_lines:
            df.at[idx, "Estado"] = "Não encontrado"
            df.at[idx, "Observacoes"] = "NIF não existe na DMR"
            resumo_rows.append({
                "NIF": nif,
                "Estado": "Não encontrado",
                "Mensagem": "NIF não existe na DMR",
            })
            continue

        if not base_a_lines and only_a_variants:
            df.at[idx, "Estado"] = "Sem linha A base"
            df.at[idx, "Observacoes"] = "Existem variantes A, mas não existe linha A base"
            resumo_rows.append({
                "NIF": nif,
                "Estado": "Sem linha A base",
                "Mensagem": "Foram encontradas apenas linhas tipo A21/A22/A23 ou semelhantes",
            })
            continue

        if not base_a_lines:
            df.at[idx, "Estado"] = "Sem rendimento A"
            df.at[idx, "Observacoes"] = "NIF existe mas sem linha A elegível"
            resumo_rows.append({
                "NIF": nif,
                "Estado": "Sem rendimento A",
                "Mensagem": "NIF existe mas não tem rendimento A base",
            })
            continue

        if len(base_a_lines) > 1:
            df.at[idx, "Estado"] = "Múltiplas linhas A"
            df.at[idx, "Observacoes"] = "Existe mais do que uma linha A base; não alterado automaticamente"
            resumo_rows.append({
                "NIF": nif,
                "Estado": "Múltiplas linhas A",
                "Mensagem": "Mais do que uma linha A base encontrada na DMR",
                "Linhas_DMR": ", ".join(str(x.line_no) for x in base_a_lines),
            })
            continue

        rec = base_a_lines[0]
        novo_valor = rec.valor + valor_excel
        novo_irs = rec.irs + irs_excel

        if novo_valor < Decimal("0.00"):
            df.at[idx, "Estado"] = "Saldo insuficiente"
            df.at[idx, "Linha_DMR"] = rec.line_no
            df.at[idx, "Rendimento_DMR"] = rec.rendimento
            df.at[idx, "Valor_DMR_Original"] = fmt_decimal_pt(rec.valor)
            df.at[idx, "IRS_DMR_Original"] = fmt_decimal_pt(rec.irs)
            df.at[idx, "Observacoes"] = "Valor da DMR insuficiente para absorver a diminuição"
            resumo_rows.append({
                "NIF": nif,
                "Estado": "Saldo insuficiente",
                "Linha_DMR": rec.line_no,
                "Rendimento_DMR": rec.rendimento,
                "Valor_DMR_Original": float(rec.valor),
                "IRS_DMR_Original": float(rec.irs),
                "Valor_Excel": float(valor_excel),
                "IRS_Excel": float(irs_excel),
                "Mensagem": "O valor final do rendimento ficaria negativo",
            })
            continue

        if novo_irs < Decimal("0.00"):
            df.at[idx, "Estado"] = "Saldo insuficiente"
            df.at[idx, "Linha_DMR"] = rec.line_no
            df.at[idx, "Rendimento_DMR"] = rec.rendimento
            df.at[idx, "Valor_DMR_Original"] = fmt_decimal_pt(rec.valor)
            df.at[idx, "IRS_DMR_Original"] = fmt_decimal_pt(rec.irs)
            df.at[idx, "Observacoes"] = "IRS da DMR insuficiente para absorver a diminuição"
            resumo_rows.append({
                "NIF": nif,
                "Estado": "Saldo insuficiente",
                "Linha_DMR": rec.line_no,
                "Rendimento_DMR": rec.rendimento,
                "Valor_DMR_Original": float(rec.valor),
                "IRS_DMR_Original": float(rec.irs),
                "Valor_Excel": float(valor_excel),
                "IRS_Excel": float(irs_excel),
                "Mensagem": "O valor final do IRS ficaria negativo",
            })
            continue

        valor_original = rec.valor
        irs_original = rec.irs

        rec.valor = novo_valor
        rec.irs = novo_irs

        df.at[idx, "Estado"] = "Alterado"
        df.at[idx, "Linha_DMR"] = rec.line_no
        df.at[idx, "Rendimento_DMR"] = rec.rendimento
        df.at[idx, "Valor_DMR_Original"] = fmt_decimal_pt(valor_original)
        df.at[idx, "IRS_DMR_Original"] = fmt_decimal_pt(irs_original)
        df.at[idx, "Valor_DMR_Novo"] = fmt_decimal_pt(novo_valor)
        df.at[idx, "IRS_DMR_Novo"] = fmt_decimal_pt(novo_irs)
        df.at[idx, "Observacoes"] = "Correção aplicada com sucesso"

        resumo_rows.append({
            "NIF": nif,
            "Estado": "Alterado",
            "Linha_Excel": idx + 2,
            "Linha_DMR": rec.line_no,
            "Rendimento_DMR": rec.rendimento,
            "Valor_DMR_Original": float(valor_original),
            "IRS_DMR_Original": float(irs_original),
            "Valor_Excel": float(valor_excel),
            "IRS_Excel": float(irs_excel),
            "Valor_DMR_Novo": float(novo_valor),
            "IRS_DMR_Novo": float(novo_irs),
            "Mensagem": "Correção aplicada",
        })

    resumo_df = pd.DataFrame(resumo_rows)
    if resumo_df.empty:
        resumo_df = pd.DataFrame(columns=[
            "NIF", "Estado", "Linha_Excel", "Linha_DMR", "Rendimento_DMR",
            "Valor_DMR_Original", "IRS_DMR_Original", "Valor_Excel", "IRS_Excel",
            "Valor_DMR_Novo", "IRS_DMR_Novo", "Mensagem"
        ])

    return df, resumo_df, records


# ============================================================
# EXPORTAÇÕES
# ============================================================
def build_excel_bytes(sheets: Dict[str, pd.DataFrame]) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
    return output.getvalue()



def build_zip_package(dmr_text: str, pendentes_df: pd.DataFrame, resumo_df: pd.DataFrame) -> bytes:
    pendentes_bytes = build_excel_bytes({"Pendentes_Atualizado": pendentes_df})
    resumo_bytes = build_excel_bytes({"Resumo": resumo_df})

    mem = io.BytesIO()
    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("DMR_corrigida.txt", dmr_text.encode("utf-8"))
        zf.writestr("pendentes_atualizado.xlsx", pendentes_bytes)
        zf.writestr("resumo_alteracoes.xlsx", resumo_bytes)
    mem.seek(0)
    return mem.getvalue()


# ============================================================
# UI STREAMLIT
# ============================================================
def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)
    st.caption(f"Versão {APP_VERSION}")

    with st.expander("Regras implementadas", expanded=False):
        st.markdown(
            """
            - Procura o NIF do Excel na DMR.
            - Só altera linhas com rendimento exatamente **A**.
            - **A21, A22, A23 e semelhantes são ignorados**.
            - O Valor e o IRS do Excel já vêm negativos, por isso são **somados** à DMR.
            - Nunca deixa valor final ou IRS final negativos.
            - Se houver múltiplas linhas A para o mesmo NIF, o caso fica sinalizado e não é alterado.
            """
        )

    col1, col2 = st.columns(2)
    with col1:
        dmr_file = st.file_uploader("Submeter ficheiro DMR", type=["txt", "csv"])
    with col2:
        excel_file = st.file_uploader("Submeter Excel de pendentes", type=["xlsx", "xls"])

    if dmr_file and excel_file:
        try:
            dmr_bytes = dmr_file.read()
            dmr_text = dmr_bytes.decode("utf-8", errors="replace")
            excel_bytes = excel_file.read()

            records, meta = parse_dmr(dmr_text)
            pendentes_df = read_excel_pendentes(excel_bytes)
            pendentes_out, resumo_df, updated_records = process_pendentes(pendentes_df, records)
            dmr_corrigida = rebuild_dmr(updated_records, meta)
            zip_bytes = build_zip_package(dmr_corrigida, pendentes_out, resumo_df)

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("Total pendentes", len(pendentes_out))
            with c2:
                st.metric("Alterados", int((pendentes_out["Estado"] == "Alterado").sum()))
            with c3:
                st.metric("Não encontrados", int((pendentes_out["Estado"] == "Não encontrado").sum()))
            with c4:
                st.metric("Com erro / validação", int((~pendentes_out["Estado"].isin(["Alterado", "Não encontrado", "Ignorado", ""])) .sum()))

            st.subheader("Resumo das alterações")
            st.dataframe(resumo_df, use_container_width=True)

            st.subheader("Pendentes atualizados")
            st.dataframe(pendentes_out, use_container_width=True)

            st.download_button(
                "Descarregar pacote ZIP",
                data=zip_bytes,
                file_name="resultado_dmr.zip",
                mime="application/zip",
            )

            st.download_button(
                "Descarregar DMR corrigida",
                data=dmr_corrigida.encode("utf-8"),
                file_name="DMR_corrigida.txt",
                mime="text/plain",
            )

        except Exception as e:
            st.error(f"Erro ao processar ficheiros: {e}")

    with st.expander("Notas para GitHub / deploy", expanded=False):
        st.code(
            """
streamlit run dmr_streamlit_app.py
            """.strip(),
            language="bash",
        )
        st.markdown(
            """
            **requirements.txt** mínimo sugerido:

            ```txt
            streamlit
            pandas
            openpyxl
            ```
            """
        )


if __name__ == "__main__":
    main()
