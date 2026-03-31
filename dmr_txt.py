from __future__ import annotations

import io
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional

import pandas as pd

CENTS = Decimal("0.01")


def decimal_2(v: Any) -> Decimal:
    if isinstance(v, Decimal):
        return v.quantize(CENTS, rounding=ROUND_HALF_UP)

    if v is None:
        return Decimal("0.00")

    s = str(v).strip()
    if not s or s.lower() == "nan":
        return Decimal("0.00")

    s = s.replace("€", "").replace("\xa0", "").replace(" ", "")

    if "," in s:
        s = s.replace(".", "").replace(",", ".")

    try:
        return Decimal(s).quantize(CENTS, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return Decimal("0.00")


def decimal_to_cents(value: Decimal) -> int:
    v = decimal_2(value)
    return int((v * 100).to_integral_value(rounding=ROUND_HALF_UP))


def cents_to_decimal(cents: int) -> Decimal:
    return (Decimal(cents) / Decimal(100)).quantize(CENTS, rounding=ROUND_HALF_UP)


def parse_signed_cents(txt: str) -> int:
    s = txt.strip()
    if not s:
        return 0
    sign = -1 if s.startswith("-") else 1
    digits = re.sub(r"[^\d]", "", s)
    if not digits:
        return 0
    return sign * int(digits)


def format_signed_cents(cents: int, width_digits: int = 13) -> str:
    sign = "+" if cents >= 0 else "-"
    return f"{sign}{abs(cents):0{width_digits}d}"


def detectar_coluna(df: pd.DataFrame, nomes_possiveis: list[str]) -> Optional[str]:
    cols_norm = {str(c).strip().lower(): c for c in df.columns}

    for nome in nomes_possiveis:
        chave = nome.strip().lower()
        if chave in cols_norm:
            return cols_norm[chave]

    for real_lower, real_col in cols_norm.items():
        for nome in nomes_possiveis:
            if nome.strip().lower() in real_lower:
                return real_col

    return None


def ler_pendentes_excel(excel_file, sheet_name=None) -> pd.DataFrame:
    xls = pd.ExcelFile(excel_file)
    folhas = xls.sheet_names

    folha = sheet_name if sheet_name and sheet_name in folhas else folhas[0]
    df = pd.read_excel(excel_file, sheet_name=folha)

    if isinstance(df, dict):
        primeira = list(df.keys())[0]
        df = df[primeira]

    col_nif = detectar_coluna(df, ["NIF"])
    col_rendimento = detectar_coluna(df, ["Rendimento", "Tipo de rendimento", "Categoria"])
    col_valor = detectar_coluna(df, ["Valor", "Montante", "Rendimento valor"])
    col_irs = detectar_coluna(df, ["IRS", "Retenção", "Imposto"])

    if not col_nif:
        raise ValueError("Não foi encontrada a coluna NIF no Excel.")
    if not col_rendimento:
        raise ValueError("Não foi encontrada a coluna Rendimento no Excel.")
    if not col_valor:
        raise ValueError("Não foi encontrada a coluna Valor no Excel.")
    if not col_irs:
        raise ValueError("Não foi encontrada a coluna IRS no Excel.")

    out = df[[col_nif, col_rendimento, col_valor, col_irs]].copy()
    out.columns = ["NIF", "Rendimento", "Valor", "IRS"]

    out["NIF"] = (
        out["NIF"]
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.replace(r"\s+", "", regex=True)
        .str.strip()
    )

    out["Rendimento"] = out["Rendimento"].astype(str).str.strip().str.upper()
    out["Valor"] = out["Valor"].apply(decimal_2)
    out["IRS"] = out["IRS"].apply(decimal_2)

    out = out[out["NIF"].str.fullmatch(r"\d{9}", na=False)].copy()
    out = out[out["Rendimento"].eq("A")].copy()

    out.reset_index(drop=True, inplace=True)
    return out


def parse_linha_006(linha: str) -> Optional[dict]:
    if not linha.startswith("006"):
        return None

    raw = linha.rstrip("\n")

    m = re.match(
        r"^(006\d{7})(\d{9})(.*?)([+-]\d{13})(A21|A22|A)\s*([A-Z])\s*(.*)$",
        raw
    )
    if not m:
        return None

    prefixo = m.group(1)
    nif = m.group(2)
    meio_antes_rendimento = m.group(3)
    rendimento_str = m.group(4)
    tipo = m.group(5)
    natureza = m.group(6)
    resto = m.group(7)

    monetarios = list(re.finditer(r"[+-]\d{13}", resto))
    if len(monetarios) < 2:
        return None

    irs_match = monetarios[0]
    ss_match = monetarios[1]

    irs_str = irs_match.group(0)
    ss_str = ss_match.group(0)

    rendimento_cents = parse_signed_cents(rendimento_str)
    irs_cents = parse_signed_cents(irs_str)
    ss_cents = parse_signed_cents(ss_str)

    rendimento_start = raw.find(rendimento_str)
    rendimento_end = rendimento_start + len(rendimento_str)

    tipo_start = rendimento_end
    tipo_end = tipo_start + len(tipo)

    natureza_pos = raw.find(natureza, tipo_end)
    resto_start = raw.find(resto, natureza_pos + 1)

    irs_start = resto_start + irs_match.start()
    irs_end = resto_start + irs_match.end()

    ss_start = resto_start + ss_match.start()
    ss_end = resto_start + ss_match.end()

    return {
        "linha_original": raw,
        "prefixo": prefixo,
        "nif": nif,
        "meio_antes_rendimento": meio_antes_rendimento,
        "rendimento_str": rendimento_str,
        "rendimento_cents": rendimento_cents,
        "tipo_rendimento": tipo,
        "natureza": natureza,
        "resto": resto,
        "irs_str": irs_str,
        "irs_cents": irs_cents,
        "ss_str": ss_str,
        "ss_cents": ss_cents,
        "pos_rendimento": (rendimento_start, rendimento_end),
        "pos_tipo": (tipo_start, tipo_end),
        "pos_irs": (irs_start, irs_end),
        "pos_ss": (ss_start, ss_end),
    }


def reconstruir_linha_006(parsed: dict, novo_rendimento_cents: int, novo_irs_cents: int) -> str:
    linha = parsed["linha_original"]

    rend_ini, rend_fim = parsed["pos_rendimento"]
    irs_ini, irs_fim = parsed["pos_irs"]

    novo_rendimento_txt = format_signed_cents(novo_rendimento_cents, 13)
    novo_irs_txt = format_signed_cents(novo_irs_cents, 13)

    linha = linha[:irs_ini] + novo_irs_txt + linha[irs_fim:]
    linha = linha[:rend_ini] + novo_rendimento_txt + linha[rend_fim:]

    return linha


def processar_dmr_txt(dmr_text: str, pendentes_df: pd.DataFrame):
    linhas = dmr_text.splitlines()
    linhas_out = list(linhas)

    pend = pendentes_df.copy()
    pend["Valor_cents"] = pend["Valor"].apply(decimal_to_cents)
    pend["IRS_cents"] = pend["IRS"].apply(decimal_to_cents)

    resultados = []

    for idx_excel, row in pend.iterrows():
        nif = str(row["NIF"]).strip()
        delta_valor = int(row["Valor_cents"])
        delta_irs = int(row["IRS_cents"])

        encontrado = False
        alterado = False
        motivo = ""

        for i, linha in enumerate(linhas):
            if not linha.startswith("006"):
                continue

            parsed = parse_linha_006(linha)
            if not parsed:
                continue

            if parsed["nif"] != nif:
                continue

            if parsed["tipo_rendimento"] != "A":
                continue

            encontrado = True

            valor_original = parsed["rendimento_cents"]
            irs_original = parsed["irs_cents"]

            novo_valor = valor_original + delta_valor
            novo_irs = irs_original + delta_irs

            if novo_valor < 0:
                motivo = (
                    f"Redução inválida: rendimento ficaria negativo "
                    f"({cents_to_decimal(valor_original)} + {cents_to_decimal(delta_valor)})."
                )
                break

            if novo_irs < 0:
                motivo = (
                    f"Redução inválida: IRS ficaria negativo "
                    f"({cents_to_decimal(irs_original)} + {cents_to_decimal(delta_irs)})."
                )
                break

            nova_linha = reconstruir_linha_006(parsed, novo_valor, novo_irs)
            linhas_out[i] = nova_linha
            alterado = True
            motivo = "Corrigido com sucesso."

            resultados.append({
                "Linha Excel": idx_excel + 2,
                "NIF": nif,
                "Tipo rendimento DMR": parsed["tipo_rendimento"],
                "Linha DMR": i + 1,
                "Rendimento original": float(cents_to_decimal(valor_original)),
                "Ajuste rendimento": float(cents_to_decimal(delta_valor)),
                "Rendimento novo": float(cents_to_decimal(novo_valor)),
                "IRS original": float(cents_to_decimal(irs_original)),
                "Ajuste IRS": float(cents_to_decimal(delta_irs)),
                "IRS novo": float(cents_to_decimal(novo_irs)),
                "Seg. Social DMR": float(cents_to_decimal(parsed["ss_cents"])),
                "Estado": "Corrigido",
                "Observações": motivo,
            })
            break

        if not encontrado:
            resultados.append({
                "Linha Excel": idx_excel + 2,
                "NIF": nif,
                "Tipo rendimento DMR": "",
                "Linha DMR": "",
                "Rendimento original": "",
                "Ajuste rendimento": float(cents_to_decimal(delta_valor)),
                "Rendimento novo": "",
                "IRS original": "",
                "Ajuste IRS": float(cents_to_decimal(delta_irs)),
                "IRS novo": "",
                "Seg. Social DMR": "",
                "Estado": "Não encontrado",
                "Observações": "Não foi encontrada linha 006 com esse NIF e rendimento do tipo A.",
            })
        elif encontrado and not alterado:
            resultados.append({
                "Linha Excel": idx_excel + 2,
                "NIF": nif,
                "Tipo rendimento DMR": "A",
                "Linha DMR": "",
                "Rendimento original": "",
                "Ajuste rendimento": float(cents_to_decimal(delta_valor)),
                "Rendimento novo": "",
                "IRS original": "",
                "Ajuste IRS": float(cents_to_decimal(delta_irs)),
                "IRS novo": "",
                "Seg. Social DMR": "",
                "Estado": "Erro validação",
                "Observações": motivo or "Não foi possível corrigir.",
            })

    dmr_corrigida = "\n".join(linhas_out)
    resumo_df = pd.DataFrame(resultados)

    return dmr_corrigida, resumo_df


def criar_excel_resumo(resumo_df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        resumo_df.to_excel(writer, index=False, sheet_name="Resumo")
    output.seek(0)
    return output.getvalue()
