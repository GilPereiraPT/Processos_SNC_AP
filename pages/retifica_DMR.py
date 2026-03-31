import io
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import List, Dict, Tuple, Optional

import pandas as pd


DEC2 = Decimal("0.01")


def dec(v) -> Decimal:
    if isinstance(v, Decimal):
        return v
    if v is None or v == "":
        return Decimal("0.00")
    try:
        return Decimal(str(v)).quantize(DEC2, rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal("0.00")


def normalizar_nif(v) -> str:
    if pd.isna(v):
        return ""
    s = str(v).strip()
    s = re.sub(r"\D", "", s)
    return s


def parse_excel_decimal_pt(v) -> Decimal:
    if pd.isna(v) or v is None or str(v).strip() == "":
        return Decimal("0.00")

    if isinstance(v, (int, float)):
        return Decimal(str(v)).quantize(DEC2, rounding=ROUND_HALF_UP)

    s = str(v).strip()
    s = s.replace("\xa0", "")
    s = s.replace(" ", "")

    # formato PT: 1.234,56
    # ou simples: 100,05
    if "," in s:
        s = s.replace(".", "")
        s = s.replace(",", ".")

    try:
        return Decimal(s).quantize(DEC2, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def decimal_to_txt_amount(value: Decimal, width: int = 13) -> str:
    """
    Converte Decimal em formato DMR:
    +0000000206400  -> 206,40
    largura total com sinal = 14
    """
    value = dec(value)
    sign = "+" if value >= 0 else "-"
    cents = int((abs(value) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return f"{sign}{cents:0{width}d}"


def txt_amount_to_decimal(s: str) -> Decimal:
    """
    Converte do formato DMR:
    +0000000206400 -> 206,40
    """
    s = (s or "").strip()
    if not s:
        return Decimal("0.00")
    sign = -1 if s.startswith("-") else 1
    digits = re.sub(r"[^\d]", "", s)
    if digits == "":
        return Decimal("0.00")
    return (Decimal(int(digits)) / Decimal("100")) * sign


def ler_pendentes_excel(excel_file, sheet_name=None) -> pd.DataFrame:
    """
    Lê Excel dos pendentes.
    Se sheet_name=None, lê a primeira folha.
    Tenta identificar colunas por nome; se não conseguir usa:
    A = NIF, C = Valor, D = IRS
    """
    df = pd.read_excel(excel_file, sheet_name=0 if sheet_name is None else sheet_name)

    cols = list(df.columns)
    nomes = {str(c).strip().lower(): c for c in cols}

    col_nif = None
    col_valor = None
    col_irs = None

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

    out = out[out["NIF"].astype(str).str.len() > 0].copy()

    out["Estado"] = "Pendente"
    out["Linha_DMR"] = ""
    out["Tipo_Rendimento"] = ""
    out["Rendimento_Anterior"] = ""
    out["Rendimento_Novo"] = ""
    out["IRS_Anterior"] = ""
    out["IRS_Novo"] = ""
    out["Observacoes"] = ""

    return out.reset_index(drop=True)


def parse_dmr_txt(text: str) -> List[Dict]:
    """
    Faz parse das linhas 006 da DMR TXT.

    Assunção prática, baseada no exemplo:
    - linha começa por 006
    - pos 3:10 -> nº linha
    - pos 10:19 -> NIF
    - tipo rendimento aparece a seguir ao bloco numérico antes do 'C'
      ex: A  C  / A21C / A22C
    - existem 5 campos monetários no fim em grupos com sinal:
        1) rendimento
        2) IRS
        3) outro1
        4) outro2
        5) outro3
    """
    regs = []
    lines = text.splitlines()

    money_pattern = re.compile(r"([+-]\d{13})")

    for idx, line in enumerate(lines):
        if not line.startswith("006"):
            continue

        moneys = list(money_pattern.finditer(line))
        if len(moneys) < 5:
            continue

        rendimento_m = moneys[0]
        irs_m = moneys[1]

        nif = line[10:19].strip()

        middle = line[19:rendimento_m.start()]
        mt = re.search(r"(A\d{0,2})\s*C\s*$", middle)
        if not mt:
            mt = re.search(r"(A\d{0,2})C\s*$", middle)

        tipo = mt.group(1).strip() if mt else ""

        regs.append(
            {
                "line_index": idx,
                "line_no": line[3:10].strip(),
                "nif": nif,
                "tipo_rendimento": tipo,
                "rendimento": txt_amount_to_decimal(rendimento_m.group(1)),
                "irs": txt_amount_to_decimal(irs_m.group(1)),
                "rendimento_span": (rendimento_m.start(), rendimento_m.end()),
                "irs_span": (irs_m.start(), irs_m.end()),
                "raw": line,
            }
        )

    return regs


def rebuild_line_with_values(
    line: str,
    rendimento_span: Tuple[int, int],
    novo_rendimento: Decimal,
    irs_span: Tuple[int, int],
    novo_irs: Decimal,
) -> str:
    a1, b1 = rendimento_span
    a2, b2 = irs_span

    novo_rend_txt = decimal_to_txt_amount(novo_rendimento)
    novo_irs_txt = decimal_to_txt_amount(novo_irs)

    if a1 < a2:
        line = line[:a1] + novo_rend_txt + line[b1:]
        delta = len(novo_rend_txt) - (b1 - a1)
        a2 += delta
        b2 += delta
        line = line[:a2] + novo_irs_txt + line[b2:]
    else:
        line = line[:a2] + novo_irs_txt + line[b2:]
        delta = len(novo_irs_txt) - (b2 - a2)
        a1 += delta
        b1 += delta
        line = line[:a1] + novo_rend_txt + line[b1:]

    return line


def escolher_linha_a_corrigir(regs_nif: List[Dict]) -> Optional[Dict]:
    """
    Escolhe a linha elegível:
    - categoria A
    - A21 não serve
    - de preferência tipo 'A'
    """
    elegiveis = []
    for r in regs_nif:
        t = (r.get("tipo_rendimento") or "").strip().upper()
        if not t.startswith("A"):
            continue
        if t == "A21":
            continue
        elegiveis.append(r)

    if not elegiveis:
        return None

    for r in elegiveis:
        if (r.get("tipo_rendimento") or "").strip().upper() == "A":
            return r

    return elegiveis[0]


def aplicar_retificacoes_dmr(
    dmr_text: str,
    pendentes_df: pd.DataFrame,
) -> Tuple[str, pd.DataFrame, Dict]:
    """
    Regras:
    - procurar NIF no TXT
    - usar linha de rendimento A
    - A21 não serve
    - valor e IRS do Excel já estão negativos
    - novo valor = valor_dmr + valor_excel
    - novo irs   = irs_dmr + irs_excel
    - nunca pode ficar negativo
    """
    lines = dmr_text.splitlines()
    regs = parse_dmr_txt(dmr_text)

    by_nif: Dict[str, List[Dict]] = {}
    for r in regs:
        by_nif.setdefault(r["nif"], []).append(r)

    out_df = pendentes_df.copy()

    resumo = {
        "total_pendentes": int(len(out_df)),
        "corrigidos": 0,
        "nao_encontrados": 0,
        "sem_linha_elegivel": 0,
        "sem_saldo_suficiente": 0,
        "com_erro": 0,
    }

    for i, row in out_df.iterrows():
        nif = normalizar_nif(row["NIF"])
        valor_excel = dec(row["Valor"])
        irs_excel = dec(row["IRS"])

        try:
            regs_nif = by_nif.get(nif, [])
            if not regs_nif:
                out_df.at[i, "Estado"] = "NIF não encontrado"
                out_df.at[i, "Observacoes"] = "Não existe nenhuma linha 006 para o NIF na DMR."
                resumo["nao_encontrados"] += 1
                continue

            reg = escolher_linha_a_corrigir(regs_nif)
            if reg is None:
                out_df.at[i, "Estado"] = "Sem linha elegível"
                out_df.at[i, "Observacoes"] = "Existe o NIF, mas não foi encontrada linha categoria A elegível (A21 excluída)."
                resumo["sem_linha_elegivel"] += 1
                continue

            rendimento_atual = dec(reg["rendimento"])
            irs_atual = dec(reg["irs"])

            novo_rendimento = (rendimento_atual + valor_excel).quantize(DEC2, rounding=ROUND_HALF_UP)
            novo_irs = (irs_atual + irs_excel).quantize(DEC2, rounding=ROUND_HALF_UP)

            if novo_rendimento < 0 or novo_irs < 0:
                out_df.at[i, "Estado"] = "Saldo insuficiente"
                out_df.at[i, "Linha_DMR"] = reg["line_no"]
                out_df.at[i, "Tipo_Rendimento"] = reg["tipo_rendimento"]
                out_df.at[i, "Rendimento_Anterior"] = float(rendimento_atual)
                out_df.at[i, "IRS_Anterior"] = float(irs_atual)
                out_df.at[i, "Observacoes"] = (
                    "A linha existe, mas o valor/rendimento ou IRS da DMR não é suficiente para absorver a diminuição."
                )
                resumo["sem_saldo_suficiente"] += 1
                continue

            old_line = lines[reg["line_index"]]
            new_line = rebuild_line_with_values(
                line=old_line,
                rendimento_span=reg["rendimento_span"],
                novo_rendimento=novo_rendimento,
                irs_span=reg["irs_span"],
                novo_irs=novo_irs,
            )
            lines[reg["line_index"]] = new_line

            # atualizar também o reg em memória, caso o mesmo NIF volte a aparecer no Excel
            reg["rendimento"] = novo_rendimento
            reg["irs"] = novo_irs
            reg["raw"] = new_line

            out_df.at[i, "Estado"] = "Corrigido"
            out_df.at[i, "Linha_DMR"] = reg["line_no"]
            out_df.at[i, "Tipo_Rendimento"] = reg["tipo_rendimento"]
            out_df.at[i, "Rendimento_Anterior"] = float(rendimento_atual)
            out_df.at[i, "Rendimento_Novo"] = float(novo_rendimento)
            out_df.at[i, "IRS_Anterior"] = float(irs_atual)
            out_df.at[i, "IRS_Novo"] = float(novo_irs)
            out_df.at[i, "Observacoes"] = "Linha DMR atualizada com sucesso."

            resumo["corrigidos"] += 1

        except Exception as e:
            out_df.at[i, "Estado"] = "Erro"
            out_df.at[i, "Observacoes"] = str(e)
            resumo["com_erro"] += 1

    novo_txt = "\n".join(lines)
    return novo_txt, out_df, resumo


def dataframe_para_excel_bytes(df: pd.DataFrame, sheet_name: str = "Pendentes Atualizados") -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    output.seek(0)
    return output.read()


def processar_dmr_e_pendentes(
    dmr_file,
    excel_file,
    sheet_name: Optional[str] = None,
) -> Tuple[str, pd.DataFrame, Dict, bytes]:
    """
    Função principal para usar no Streamlit.
    """
    dmr_bytes = dmr_file.read()
    try:
        dmr_text = dmr_bytes.decode("utf-8")
    except UnicodeDecodeError:
        dmr_text = dmr_bytes.decode("latin-1")

    sheet_name_clean = sheet_name.strip() if sheet_name and str(sheet_name).strip() else None
    pendentes_df = ler_pendentes_excel(excel_file, sheet_name=sheet_name_clean)

    novo_txt, pendentes_out, resumo = aplicar_retificacoes_dmr(dmr_text, pendentes_df)
    excel_out = dataframe_para_excel_bytes(pendentes_out)

    return novo_txt, pendentes_out, resumo, excel_out
