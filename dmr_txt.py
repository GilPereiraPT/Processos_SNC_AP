from __future__ import annotations

from io import BytesIO
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import pandas as pd


# =========================
# CONFIGURAÇÃO DO LAYOUT DMR
# =========================
# Posições 1-based inclusive
POS_REGISTO = (1, 3)
POS_SEQ = (4, 10)
POS_NIF = (11, 19)
POS_RENDIMENTO = (39, 53)
POS_TIPO = (54, 56)
POS_INDICADOR = (57, 57)
POS_IRS = (59, 72)

TIPOS_EXCLUIDOS = {"A21"}
TIPO_VALIDO_PREFIX = "A"


# =========================
# FUNÇÕES BASE
# =========================
def slice_field(line: str, pos: tuple[int, int]) -> str:
    a, b = pos
    return line[a - 1:b]


def replace_field(line: str, pos: tuple[int, int], value: str) -> str:
    a, b = pos
    width = b - a + 1
    if len(value) != width:
        raise ValueError(
            f"O valor '{value}' não tem a largura certa para a posição {pos}. "
            f"Esperado: {width}, obtido: {len(value)}"
        )
    return line[: a - 1] + value + line[b:]


def decimal_2(v) -> Decimal:
    if isinstance(v, Decimal):
        return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def parse_excel_decimal_pt(v) -> Decimal:
    if pd.isna(v):
        return Decimal("0.00")

    s = str(v).strip()
    if not s:
        return Decimal("0.00")

    s = s.replace(" ", "")

    # Formato PT: 1.234,56
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    # Se vier já como 1234.56, mantém-se

    try:
        return decimal_2(Decimal(s))
    except InvalidOperation:
        raise ValueError(f"Valor numérico inválido no Excel: {v}")


def parse_signed_cents(field: str) -> Decimal:
    """
    Exemplo:
    +00000000759239 -> 7592.39
    -00000000010000 -> -100.00
    """
    s = field.strip()
    if not s:
        return Decimal("0.00")

    sign = 1
    if s[0] == "-":
        sign = -1
        digits = s[1:]
    elif s[0] == "+":
        digits = s[1:]
    else:
        digits = s

    if not digits.isdigit():
        raise ValueError(f"Campo monetário inválido: '{field}'")

    cents = Decimal(int(digits))
    value = (cents / Decimal("100")) * sign
    return decimal_2(value)


def format_signed_cents(value: Decimal, width: int) -> str:
    """
    Converte Decimal para formato DMR:
    width inclui sinal.
    Ex.: width 15 => +00000000759239
    """
    value = decimal_2(value)
    sign = "+" if value >= 0 else "-"
    cents = int((abs(value) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    digits_width = width - 1
    digits = str(cents).rjust(digits_width, "0")
    return sign + digits


def normalizar_nif(v) -> str:
    s = "".join(ch for ch in str(v) if ch.isdigit())
    return s


# =========================
# LEITURA DO EXCEL
# =========================
def ler_pendentes_excel(excel_file, sheet_name=None) -> pd.DataFrame:
    df = pd.read_excel(excel_file, sheet_name=sheet_name)

    # Assume:
    # Col A = NIF
    # Col C = Valor
    # Col D = IRS
    # Se existirem nomes explícitos, tenta usá-los
    cols = list(df.columns)

    col_nif = None
    col_valor = None
    col_irs = None

    nomes = {str(c).strip().lower(): c for c in cols}

    for k, c in nomes.items():
        if col_nif is None and "nif" in k:
            col_nif = c
        if col_valor is None and "valor" in k:
            col_valor = c
        if col_irs is None and k in {"irs", "i.r.s."}:
            col_irs = c

    if col_nif is None and len(cols) >= 1:
        col_nif = cols[0]
    if col_valor is None and len(cols) >= 3:
        col_valor = cols[2]
    if col_irs is None and len(cols) >= 4:
        col_irs = cols[3]

    if col_nif is None or col_valor is None or col_irs is None:
        raise ValueError(
            "Não foi possível identificar as colunas de NIF, Valor e IRS no Excel."
        )

    out = pd.DataFrame()
    out["NIF"] = df[col_nif].map(normalizar_nif)
    out["Valor"] = df[col_valor].map(parse_excel_decimal_pt)
    out["IRS"] = df[col_irs].map(parse_excel_decimal_pt)

    # Remover linhas vazias
    out = out[out["NIF"].astype(str).str.len() > 0].copy()

    # Inicialização de controlo
    out["Estado"] = "Pendente"
    out["Linha_DMR"] = ""
    out["Tipo_Rendimento"] = ""
    out["Rendimento_Anterior"] = ""
    out["Rendimento_Novo"] = ""
    out["IRS_Anterior"] = ""
    out["IRS_Novo"] = ""
    out["Observacoes"] = ""

    return out.reset_index(drop=True)


# =========================
# PROCESSAMENTO DA DMR
# =========================
def processar_dmr_txt(
    dmr_bytes: bytes,
    pendentes_df: pd.DataFrame,
    encoding: str = "latin1",
) -> dict:
    text = dmr_bytes.decode(encoding)
    lines = text.splitlines(keepends=True)

    pendentes_out = pendentes_df.copy()
    log_rows = []
    alteradas = 0

    # Mapear pendentes por NIF, preservando índice
    pendentes_por_nif: dict[str, list[int]] = {}
    for idx, row in pendentes_out.iterrows():
        nif = row["NIF"]
        pendentes_por_nif.setdefault(nif, []).append(idx)

    novas_linhas = []

    for nr_linha, original_line in enumerate(lines, start=1):
        line = original_line.rstrip("\r\n")
        newline = original_line[len(line):]

        if len(line) < 87:
            novas_linhas.append(original_line)
            continue

        reg = slice_field(line, POS_REGISTO)
        if reg != "006":
            novas_linhas.append(original_line)
            continue

        nif = slice_field(line, POS_NIF).strip()
        tipo = slice_field(line, POS_TIPO).strip()

        if not nif or nif not in pendentes_por_nif:
            novas_linhas.append(original_line)
            continue

        if not tipo.startswith(TIPO_VALIDO_PREFIX):
            novas_linhas.append(original_line)
            continue

        if tipo in TIPOS_EXCLUIDOS:
            novas_linhas.append(original_line)
            continue

        # Procurar o primeiro pendente ainda não resolvido deste NIF
        idx_pendente = None
        for idx in pendentes_por_nif[nif]:
            if pendentes_out.at[idx, "Estado"] == "Pendente":
                idx_pendente = idx
                break

        if idx_pendente is None:
            novas_linhas.append(original_line)
            continue

        rendimento_atual = parse_signed_cents(slice_field(line, POS_RENDIMENTO))
        irs_atual = parse_signed_cents(slice_field(line, POS_IRS))

        valor_excel = decimal_2(pendentes_out.at[idx_pendente, "Valor"])
        irs_excel = decimal_2(pendentes_out.at[idx_pendente, "IRS"])

        # No Excel vêm negativos e devem ser somados à DMR para diminuir
        novo_rendimento = decimal_2(rendimento_atual + valor_excel)
        novo_irs = decimal_2(irs_atual + irs_excel)

        if novo_rendimento < 0:
            pendentes_out.at[idx_pendente, "Estado"] = "Erro"
            pendentes_out.at[idx_pendente, "Observacoes"] = (
                f"Rendimento insuficiente na linha {nr_linha}. "
                f"Atual={rendimento_atual}, ajuste={valor_excel}, novo={novo_rendimento}"
            )

            log_rows.append({
                "Linha_DMR": nr_linha,
                "NIF": nif,
                "Tipo_Rendimento": tipo,
                "Estado": "Erro",
                "Motivo": "Rendimento ficaria negativo",
                "Rendimento_Anterior": float(rendimento_atual),
                "Ajuste_Rendimento": float(valor_excel),
                "Rendimento_Novo": float(novo_rendimento),
                "IRS_Anterior": float(irs_atual),
                "Ajuste_IRS": float(irs_excel),
                "IRS_Novo": float(novo_irs),
            })
            novas_linhas.append(original_line)
            continue

        if novo_irs < 0:
            pendentes_out.at[idx_pendente, "Estado"] = "Erro"
            pendentes_out.at[idx_pendente, "Observacoes"] = (
                f"IRS insuficiente na linha {nr_linha}. "
                f"Atual={irs_atual}, ajuste={irs_excel}, novo={novo_irs}"
            )

            log_rows.append({
                "Linha_DMR": nr_linha,
                "NIF": nif,
                "Tipo_Rendimento": tipo,
                "Estado": "Erro",
                "Motivo": "IRS ficaria negativo",
                "Rendimento_Anterior": float(rendimento_atual),
                "Ajuste_Rendimento": float(valor_excel),
                "Rendimento_Novo": float(novo_rendimento),
                "IRS_Anterior": float(irs_atual),
                "Ajuste_IRS": float(irs_excel),
                "IRS_Novo": float(novo_irs),
            })
            novas_linhas.append(original_line)
            continue

        # Reescrever apenas rendimento e IRS
        width_rendimento = POS_RENDIMENTO[1] - POS_RENDIMENTO[0] + 1
        width_irs = POS_IRS[1] - POS_IRS[0] + 1

        line = replace_field(
            line,
            POS_RENDIMENTO,
            format_signed_cents(novo_rendimento, width_rendimento),
        )
        line = replace_field(
            line,
            POS_IRS,
            format_signed_cents(novo_irs, width_irs),
        )

        novas_linhas.append(line + newline)
        alteradas += 1

        pendentes_out.at[idx_pendente, "Estado"] = "Resolvido"
        pendentes_out.at[idx_pendente, "Linha_DMR"] = nr_linha
        pendentes_out.at[idx_pendente, "Tipo_Rendimento"] = tipo
        pendentes_out.at[idx_pendente, "Rendimento_Anterior"] = float(rendimento_atual)
        pendentes_out.at[idx_pendente, "Rendimento_Novo"] = float(novo_rendimento)
        pendentes_out.at[idx_pendente, "IRS_Anterior"] = float(irs_atual)
        pendentes_out.at[idx_pendente, "IRS_Novo"] = float(novo_irs)
        pendentes_out.at[idx_pendente, "Observacoes"] = "Linha alterada com sucesso"

        log_rows.append({
            "Linha_DMR": nr_linha,
            "NIF": nif,
            "Tipo_Rendimento": tipo,
            "Estado": "Alterado",
            "Motivo": "",
            "Rendimento_Anterior": float(rendimento_atual),
            "Ajuste_Rendimento": float(valor_excel),
            "Rendimento_Novo": float(novo_rendimento),
            "IRS_Anterior": float(irs_atual),
            "Ajuste_IRS": float(irs_excel),
            "IRS_Novo": float(novo_irs),
        })

    # Pendentes que ficaram por resolver
    pendentes_mask = pendentes_out["Estado"].eq("Pendente")
    pendentes_out.loc[pendentes_mask, "Observacoes"] = (
        "Sem linha elegível encontrada na DMR para este NIF "
        "(categoria A, excluindo A21, e ainda não usada)."
    )

    log_df = pd.DataFrame(log_rows)

    resumo = {
        "pendentes_lidos": int(len(pendentes_out)),
        "linhas_alteradas": int(alteradas),
        "pendentes_resolvidos": int((pendentes_out["Estado"] == "Resolvido").sum()),
        "pendentes_por_resolver": int((pendentes_out["Estado"] == "Pendente").sum()),
        "pendentes_com_erro": int((pendentes_out["Estado"] == "Erro").sum()),
    }

    dmr_corrigida_text = "".join(novas_linhas)
    dmr_corrigida_bytes = dmr_corrigida_text.encode(encoding)

    return {
        "dmr_corrigida_bytes": dmr_corrigida_bytes,
        "pendentes_out": pendentes_out,
        "log_df": log_df,
        "resumo": resumo,
    }


# =========================
# EXCEL DE SAÍDA
# =========================
def criar_excel_saida(
    pendentes_out: pd.DataFrame,
    log_df: pd.DataFrame,
    resumo: dict,
) -> bytes:
    bio = BytesIO()

    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        pendentes_out.to_excel(writer, index=False, sheet_name="Pendentes_Atualizados")
        log_df.to_excel(writer, index=False, sheet_name="Log_Alteracoes")

        resumo_df = pd.DataFrame(
            [{"Indicador": k, "Valor": v} for k, v in resumo.items()]
        )
        resumo_df.to_excel(writer, index=False, sheet_name="Resumo")

    bio.seek(0)
    return bio.getvalue()
