from __future__ import annotations

import io
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple

import pandas as pd


DEC2 = Decimal("0.01")


def dec2(v: Decimal) -> Decimal:
    return v.quantize(DEC2, rounding=ROUND_HALF_UP)


def to_decimal(value) -> Decimal:
    """
    Converte vários formatos para Decimal.
    Aceita:
    - 100
    - 100.25
    - "100,25"
    - "-100,25"
    - ""
    - None
    """
    if value is None:
        return Decimal("0.00")

    if isinstance(value, Decimal):
        return dec2(value)

    if isinstance(value, (int, float)):
        return dec2(Decimal(str(value)))

    s = str(value).strip()
    if not s:
        return Decimal("0.00")

    s = s.replace(" ", "")
    s = s.replace(".", "")
    s = s.replace(",", ".")

    try:
        return dec2(Decimal(s))
    except InvalidOperation:
        return Decimal("0.00")


def decimal_to_pt_str(v: Decimal) -> str:
    return f"{dec2(v):.2f}".replace(".", ",")


def txt_amount_to_decimal(s: str) -> Decimal:
    """
    Converte um campo DMR TXT com sinal e 2 casas implícitas.
    Ex:
      +00000000064387 -> 643.87
      -00000000010000 -> -100.00
    """
    s = (s or "").strip()
    if not s:
        return Decimal("0.00")

    sign = -1 if s.startswith("-") else 1
    digits = re.sub(r"[^\d]", "", s)

    if not digits:
        return Decimal("0.00")

    return dec2((Decimal(digits) / Decimal("100")) * sign)


def decimal_to_txt_amount(v: Decimal, width: int = 13) -> str:
    """
    Converte Decimal para campo DMR TXT com sinal e 2 casas implícitas.
    Ex:
      643.87 -> +00000000064387
      -5.10  -> -00000000000510

    width = nº de dígitos após o sinal.
    """
    v = dec2(v)
    sign = "+" if v >= 0 else "-"
    cents = int(abs(v) * 100)
    return f"{sign}{cents:0{width}d}"


def normalizar_nif(v) -> str:
    s = str(v or "").strip()
    s = re.sub(r"\D", "", s)
    return s


def excel_bytes_to_df(uploaded_file, sheet_name=None) -> pd.DataFrame:
    """
    Lê um Excel recebido do Streamlit uploader.
    """
    data = uploaded_file.read()
    bio = io.BytesIO(data)
    return pd.read_excel(bio, sheet_name=sheet_name, dtype=object)


def ler_pendentes_excel(uploaded_file, sheet_name=None) -> pd.DataFrame:
    """
    Lê o Excel das pendências.
    Espera:
      Coluna A -> NIF
      Coluna C -> Valor
      Coluna D -> IRS

    Pode ter cabeçalhos variados; usa posição.
    """
    df = excel_bytes_to_df(uploaded_file, sheet_name=sheet_name)

    if isinstance(df, dict):
        # quando sheet_name=None e há várias folhas
        first_sheet = next(iter(df))
        df = df[first_sheet]

    if df is None or df.empty:
        return pd.DataFrame(columns=["NIF", "Valor", "IRS"])

    cols = list(df.columns)
    if len(cols) < 4:
        raise ValueError(
            "O ficheiro Excel deve ter pelo menos 4 colunas: A=NIF, C=Valor, D=IRS."
        )

    out = pd.DataFrame()
    out["NIF"] = df.iloc[:, 0].apply(normalizar_nif)
    out["Valor"] = df.iloc[:, 2].apply(to_decimal)
    out["IRS"] = df.iloc[:, 3].apply(to_decimal)

    # remove linhas totalmente vazias / sem NIF
    out = out[out["NIF"].astype(str).str.strip() != ""].copy()

    out.reset_index(drop=True, inplace=True)
    out["Excel_Row"] = out.index + 2  # considerando cabeçalho na linha 1
    return out


def parse_dmr_txt(text: str) -> List[Dict]:
    """
    Parse das linhas 006 da DMR TXT, com base no formato observado:

    1-3   : '006'
    4-10  : nº linha
    11-19 : NIF
    20-37 : campo fixo
    38-50 : rendimento
    51-53 : tipo rendimento (A, A21, A22...)
    54    : natureza ('C')
    55-67 : IRS
    68-80 : Segurança Social

    Índices Python:
    [0:3]    = 006
    [3:10]   = nº linha
    [10:19]  = NIF
    [19:37]  = campo fixo
    [37:50]  = rendimento
    [50:53]  = tipo
    [53:54]  = natureza
    [54:67]  = IRS
    [67:80]  = Seg. Social
    """
    regs: List[Dict] = []
    lines = text.splitlines()

    for idx, line in enumerate(lines):
        if not line.startswith("006"):
            continue

        if len(line) < 80:
            continue

        try:
            line_no = line[3:10].strip()
            nif = line[10:19].strip()

            rendimento_txt = line[37:50]
            tipo_raw = line[50:53]
            natureza = line[53:54]
            irs_txt = line[54:67]
            ss_txt = line[67:80]

            tipo_rendimento = tipo_raw.strip()

            rendimento = txt_amount_to_decimal(rendimento_txt)
            irs = txt_amount_to_decimal(irs_txt)
            ss = txt_amount_to_decimal(ss_txt)

            regs.append(
                {
                    "line_index": idx,
                    "line_no": line_no,
                    "nif": normalizar_nif(nif),
                    "tipo_rendimento": tipo_rendimento,
                    "natureza": natureza,
                    "rendimento": rendimento,
                    "irs": irs,
                    "seg_social": ss,
                    "rendimento_span": (37, 50),
                    "irs_span": (54, 67),
                    "ss_span": (67, 80),
                    "raw": line,
                }
            )
        except Exception:
            continue

    return regs


def escolher_linha_a_corrigir(regs_nif: List[Dict]) -> Optional[Dict]:
    """
    Regras:
    - tem de ser categoria A
    - A21 não serve
    - prefere exatamente "A"
    """
    elegiveis = []

    for r in regs_nif:
        t = (r.get("tipo_rendimento") or "").strip().upper()

        if not t:
            continue
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


def atualizar_campo_linha(line: str, span: Tuple[int, int], novo_valor: Decimal) -> str:
    ini, fim = span
    original = line[ini:fim]
    novo_txt = decimal_to_txt_amount(novo_valor, width=(fim - ini - 1))
    if len(novo_txt) != (fim - ini):
        raise ValueError(
            f"Comprimento inesperado ao atualizar campo {span}: "
            f"original={len(original)} novo={len(novo_txt)}"
        )
    return line[:ini] + novo_txt + line[fim:]


def recalcular_totais_004_005(lines: List[str]) -> List[str]:
    """
    Recalcula os totais 004 e 005 com base nas linhas 006.
    Mapeamento observado:

    004:
    - total rendimento bruto -> soma dos rendimentos das 006
    - total IRS             -> soma IRS das 006
    - total SS              -> soma Seg. Social das 006

    005:
    repete os principais totais em posições usadas no ficheiro observado.

    Esta função é conservadora: só altera 004 e 005 se existirem.
    """
    regs = parse_dmr_txt("\n".join(lines))

    total_rendimento = dec2(sum((r["rendimento"] for r in regs), Decimal("0.00")))
    total_irs = dec2(sum((r["irs"] for r in regs), Decimal("0.00")))
    total_ss = dec2(sum((r["seg_social"] for r in regs), Decimal("0.00")))

    new_lines = lines[:]

    idx004 = next((i for i, ln in enumerate(new_lines) if ln.startswith("004")), None)
    idx005 = next((i for i, ln in enumerate(new_lines) if ln.startswith("005")), None)

    if idx004 is not None:
        ln = new_lines[idx004]
        # Formato observado da linha 004:
        # 004+000000299461994+00000048945800+00000039286126+00000000662742...
        #     campo1 total?       rendimento         IRS              SS
        #
        # Mantemos campo 1 intacto e atualizamos:
        # [17:31] rendimento
        # [31:45] IRS
        # [45:59] SS
        if len(ln) >= 59:
            ln = ln[:17] + decimal_to_txt_amount(total_rendimento, 13) + ln[31:]
            ln = ln[:31] + decimal_to_txt_amount(total_irs, 13) + ln[45:]
            ln = ln[:45] + decimal_to_txt_amount(total_ss, 13) + ln[59:]
            new_lines[idx004] = ln

    if idx005 is not None:
        ln = new_lines[idx005]
        # Formato observado da linha 005:
        # 005+000000014136999+...+0000000313598993+000000048945800+000000039286126+000000000662742...
        #
        # Atualiza os 3 campos finais principais se a linha tiver comprimento suficiente.
        # Posições observadas:
        # [73:88] rendimento
        # [88:102] IRS
        # [102:116] SS
        if len(ln) >= 116:
            ln = ln[:73] + decimal_to_txt_amount(total_rendimento, 14) + ln[88:]
            ln = ln[:88] + decimal_to_txt_amount(total_irs, 13) + ln[102:]
            ln = ln[:102] + decimal_to_txt_amount(total_ss, 13) + ln[116:]
            new_lines[idx005] = ln

    return new_lines


def processar_retificacao_dmr(
    dmr_text: str,
    pendentes_df: pd.DataFrame,
) -> Tuple[str, pd.DataFrame, pd.DataFrame]:
    """
    Devolve:
    - novo texto DMR
    - resumo das alterações
    - Excel atualizado
    """
    if not isinstance(pendentes_df, pd.DataFrame):
        raise ValueError("O ficheiro das pendências não foi lido como DataFrame.")

    lines = dmr_text.splitlines()
    regs = parse_dmr_txt(dmr_text)

    if not regs:
        raise ValueError("Não foram encontradas linhas 006 na DMR TXT.")

    regs_by_nif: Dict[str, List[Dict]] = {}
    for r in regs:
        regs_by_nif.setdefault(r["nif"], []).append(r)

    resumo_rows = []
    pend_out = pendentes_df.copy()

    estados = []
    observacoes = []
    linha_dmr_out = []
    tipo_out = []
    rendimento_ant_out = []
    rendimento_novo_out = []
    irs_ant_out = []
    irs_novo_out = []

    for _, row in pend_out.iterrows():
        nif = normalizar_nif(row.get("NIF"))
        delta_valor = to_decimal(row.get("Valor"))
        delta_irs = to_decimal(row.get("IRS"))

        regs_nif = regs_by_nif.get(nif, [])
        reg = escolher_linha_a_corrigir(regs_nif)

        if not nif:
            estados.append("Erro")
            observacoes.append("NIF vazio.")
            linha_dmr_out.append("")
            tipo_out.append("")
            rendimento_ant_out.append("")
            rendimento_novo_out.append("")
            irs_ant_out.append("")
            irs_novo_out.append("")
            continue

        if reg is None:
            estados.append("Não encontrado")
            observacoes.append("Sem linha elegível de categoria A (A21 excluída) para este NIF.")
            linha_dmr_out.append("")
            tipo_out.append("")
            rendimento_ant_out.append("")
            rendimento_novo_out.append("")
            irs_ant_out.append("")
            irs_novo_out.append("")
            continue

        rendimento_ant = to_decimal(reg["rendimento"])
        irs_ant = to_decimal(reg["irs"])

        # Excel já vem negativo; a diminuição é feita por soma algébrica
        rendimento_novo = dec2(rendimento_ant + delta_valor)
        irs_novo = dec2(irs_ant + delta_irs)

        if rendimento_novo < 0:
            estados.append("Erro")
            observacoes.append(
                f"Rendimento insuficiente na DMR. Atual={decimal_to_pt_str(rendimento_ant)} "
                f"delta={decimal_to_pt_str(delta_valor)}."
            )
            linha_dmr_out.append(reg["line_no"])
            tipo_out.append(reg["tipo_rendimento"])
            rendimento_ant_out.append(decimal_to_pt_str(rendimento_ant))
            rendimento_novo_out.append("")
            irs_ant_out.append(decimal_to_pt_str(irs_ant))
            irs_novo_out.append("")
            continue

        if irs_novo < 0:
            estados.append("Erro")
            observacoes.append(
                f"IRS insuficiente na DMR. Atual={decimal_to_pt_str(irs_ant)} "
                f"delta={decimal_to_pt_str(delta_irs)}."
            )
            linha_dmr_out.append(reg["line_no"])
            tipo_out.append(reg["tipo_rendimento"])
            rendimento_ant_out.append(decimal_to_pt_str(rendimento_ant))
            rendimento_novo_out.append("")
            irs_ant_out.append(decimal_to_pt_str(irs_ant))
            irs_novo_out.append("")
            continue

        idx_line = reg["line_index"]
        ln = lines[idx_line]

        ln = atualizar_campo_linha(ln, reg["rendimento_span"], rendimento_novo)
        ln = atualizar_campo_linha(ln, reg["irs_span"], irs_novo)

        lines[idx_line] = ln

        # atualizar o reg local também, para coerência se houver novo cálculo depois
        reg["rendimento"] = rendimento_novo
        reg["irs"] = irs_novo
        reg["raw"] = ln

        estados.append("Atualizado")
        observacoes.append("Linha DMR corrigida com sucesso.")
        linha_dmr_out.append(reg["line_no"])
        tipo_out.append(reg["tipo_rendimento"])
        rendimento_ant_out.append(decimal_to_pt_str(rendimento_ant))
        rendimento_novo_out.append(decimal_to_pt_str(rendimento_novo))
        irs_ant_out.append(decimal_to_pt_str(irs_ant))
        irs_novo_out.append(decimal_to_pt_str(irs_novo))

        resumo_rows.append(
            {
                "NIF": nif,
                "Linha_DMR": reg["line_no"],
                "Tipo_Rendimento": reg["tipo_rendimento"],
                "Valor_Excel": decimal_to_pt_str(delta_valor),
                "IRS_Excel": decimal_to_pt_str(delta_irs),
                "Rendimento_Antes": decimal_to_pt_str(rendimento_ant),
                "Rendimento_Novo": decimal_to_pt_str(rendimento_novo),
                "IRS_Antes": decimal_to_pt_str(irs_ant),
                "IRS_Novo": decimal_to_pt_str(irs_novo),
                "Resultado": "Atualizado",
            }
        )

    pend_out["Estado"] = estados
    pend_out["Observação"] = observacoes
    pend_out["Linha_DMR"] = linha_dmr_out
    pend_out["Tipo_Rendimento"] = tipo_out
    pend_out["Rendimento_Antes"] = rendimento_ant_out
    pend_out["Rendimento_Novo"] = rendimento_novo_out
    pend_out["IRS_Antes"] = irs_ant_out
    pend_out["IRS_Novo"] = irs_novo_out

    lines = recalcular_totais_004_005(lines)

    resumo_df = pd.DataFrame(resumo_rows)
    novo_dmr = "\n".join(lines)

    return novo_dmr, resumo_df, pend_out
