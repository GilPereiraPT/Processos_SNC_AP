from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import BinaryIO

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Reconciliação Contabilidade × Ativos", page_icon="📊", layout="wide")

TOLERANCE_DEFAULT = 0.10
ZERO_DEPRECIATION_THRESHOLD = 0.005
MONTHS_PT = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}


@dataclass
class ReconciliationResult:
    summary: pd.DataFrame
    account_differences: pd.DataFrame
    technical_detail: pd.DataFrame
    asset_warnings: pd.DataFrame
    asset_control_summary: pd.DataFrame
    accounting: pd.DataFrame
    assets: pd.DataFrame


def normalize_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text.strip().lower())


def normalize_code(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return re.sub(r"[^0-9A-Za-z]", "", text)


def money_to_float(value: object) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0.0
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    text = str(value).strip().replace("€", "").replace("\u00a0", "").replace(" ", "")
    if not text or text in {"-", "—"}:
        return 0.0
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(Decimal(text))
    except (InvalidOperation, ValueError):
        return 0.0


def decode_csv(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin1"):
        try:
            text = data.decode(encoding)
            if ";" in text:
                return text
        except UnicodeDecodeError:
            continue
    return data.decode("latin1", errors="replace")


def parse_sicc_period(lines: list[str]) -> tuple[int | None, int | None]:
    year = None
    month = None
    for line in lines[:15]:
        norm = normalize_text(line)
        if norm.startswith("exercicio:"):
            match = re.search(r"(20\d{2})", norm)
            year = int(match.group(1)) if match else None
        if norm.startswith("intervalo de meses:"):
            for name, number in MONTHS_PT.items():
                if name in norm:
                    month = number
                    break
    return year, month


def load_sicc(uploaded: BinaryIO) -> pd.DataFrame:
    data = uploaded.read()
    text = decode_csv(data)
    lines = text.splitlines()
    header_idx = next(
        (i for i, line in enumerate(lines) if normalize_text(line).startswith("conta;designacao da conta")),
        None,
    )
    if header_idx is None:
        raise ValueError("Não foi encontrado o cabeçalho do balancete SICC.")

    df = pd.read_csv(io.StringIO("\n".join(lines[header_idx:])), sep=";", dtype=str)
    df = df.loc[:, ~df.columns.str.match(r"^Unnamed")]
    df.columns = [normalize_text(c) for c in df.columns]

    required = {
        "conta", "designacao da conta", "valor a debito", "valor a credito",
        "valor acumulado a debito", "valor acumulado a credito", "saldo a debito", "saldo a credito",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Faltam colunas no SICC: {', '.join(sorted(missing))}")

    out = pd.DataFrame({
        "account": df["conta"].map(normalize_code),
        "description": df["designacao da conta"].fillna(""),
        "period_debit": df["valor a debito"].map(money_to_float),
        "period_credit": df["valor a credito"].map(money_to_float),
        "accum_debit": df["valor acumulado a debito"].map(money_to_float),
        "accum_credit": df["valor acumulado a credito"].map(money_to_float),
        "debit_balance": df["saldo a debito"].map(money_to_float),
        "credit_balance": df["saldo a credito"].map(money_to_float),
    })
    out["period_net"] = out["period_debit"] - out["period_credit"]
    out["exercise_net"] = out["accum_debit"] - out["accum_credit"]
    out["net_balance"] = out["debit_balance"] - out["credit_balance"]
    out = out[out["account"] != ""].reset_index(drop=True)
    year, month = parse_sicc_period(lines)
    out.attrs["report_year"] = year
    out.attrs["report_month"] = month
    return out


def find_primavera_header(raw: pd.DataFrame) -> int:
    for idx in range(min(30, len(raw))):
        values = {normalize_text(v) for v in raw.iloc[idx].tolist() if pd.notna(v)}
        if "codigo" in values and "descricao" in values and "valor contabilistico" in values:
            return idx
    raise ValueError("Não foi encontrado o cabeçalho do balancete Primavera.")


def load_primavera(uploaded: BinaryIO) -> pd.DataFrame:
    data = uploaded.read()
    raw = pd.read_excel(io.BytesIO(data), header=None, engine="openpyxl")
    header_idx = find_primavera_header(raw)
    header = [normalize_text(v) for v in raw.iloc[header_idx].tolist()]
    df = raw.iloc[header_idx + 1:].copy()
    df.columns = header

    columns = list(df.columns)
    code_pos = columns.index("codigo")
    desc_pos = columns.index("descricao")
    date_pos = columns.index("data utilizacao")
    gross_pos = columns.index("valor contabilistico")
    residual_pos = columns.index("valor residual")
    rate_pos = columns.index("taxa")
    dep_period_pos, dep_exercise_pos, dep_accum_pos = 7, 8, 9
    imp_period_pos, imp_exercise_pos, imp_accum_pos = 10, 11, 12
    carrying_pos = columns.index("quantia escriturada")

    raw_codes = df.iloc[:, code_pos]
    out = pd.DataFrame({
        "code_raw": raw_codes,
        "code": raw_codes.map(normalize_code),
        "description": df.iloc[:, desc_pos].fillna(""),
        "use_date": pd.to_datetime(df.iloc[:, date_pos], errors="coerce"),
        "gross_value": df.iloc[:, gross_pos].map(money_to_float),
        "residual_value": df.iloc[:, residual_pos].map(money_to_float),
        "rate": df.iloc[:, rate_pos].map(money_to_float),
        "depreciation_period": df.iloc[:, dep_period_pos].map(money_to_float),
        "depreciation_exercise": df.iloc[:, dep_exercise_pos].map(money_to_float),
        "accumulated_depreciation": df.iloc[:, dep_accum_pos].map(money_to_float),
        "impairment_period": df.iloc[:, imp_period_pos].map(money_to_float),
        "impairment_exercise": df.iloc[:, imp_exercise_pos].map(money_to_float),
        "accumulated_impairment": df.iloc[:, imp_accum_pos].map(money_to_float),
        "carrying_amount": df.iloc[:, carrying_pos].map(money_to_float),
    })
    out["is_account"] = raw_codes.map(
        lambda v: bool(v is not None and not (isinstance(v, float) and pd.isna(v)) and not str(v).startswith(" "))
    )

    current_account = ""
    parent_accounts: list[str] = []
    for _, row in out.iterrows():
        if row["is_account"] and str(row["code"]).startswith("43"):
            current_account = str(row["code"])
        parent_accounts.append(current_account)
    out["asset_account"] = parent_accounts
    return out[out["code"] != ""].reset_index(drop=True)


def accounting_row(df: pd.DataFrame, account: str) -> pd.Series | None:
    match = df[df["account"] == account]
    return None if match.empty else match.iloc[0]


def leaf_rows(df: pd.DataFrame, code_column: str) -> pd.DataFrame:
    result = df.copy()
    codes = result[code_column].astype(str).tolist()
    result["is_leaf"] = [not any(other.startswith(code) and other != code for other in codes) for code in codes]
    return result[result["is_leaf"]].copy()


def linked_primavera_accounts(assets: pd.DataFrame, prefix: str) -> pd.DataFrame:
    accounts = assets[assets["is_account"] & assets["code"].str.startswith(prefix)].copy()
    return leaf_rows(accounts, "code")


def add_difference(records: list[dict], component: str, sicc_account: str, linked: pd.DataFrame,
                   sicc_value: float, primavera_column: str, description: str, tolerance: float,
                   level: str, note: str) -> None:
    primavera_value = float(linked[primavera_column].sum()) if not linked.empty else 0.0
    difference = sicc_value - primavera_value
    if abs(difference) > tolerance:
        records.append({
            "Componente": component,
            "Conta SICC": sicc_account,
            "Conta(s) Primavera": ", ".join(linked["code"].astype(str).tolist()),
            "Descrição": description,
            "SICC": sicc_value,
            "Primavera": primavera_value,
            "Diferença SICC - Primavera": difference,
            "Nível de comparação": level,
            "Observação": note,
        })


def build_account_differences(accounting: pd.DataFrame, assets: pd.DataFrame, tolerance: float) -> pd.DataFrame:
    records: list[dict] = []
    prim_accounts = assets[assets["is_account"] & assets["code"].str.startswith("43")].copy()
    prim_accounts = prim_accounts[~prim_accounts["code"].str.startswith(("438", "439"))]
    prim_leaf = leaf_rows(prim_accounts, "code")

    # Valor bruto por conta final.
    for _, row in prim_leaf.iterrows():
        code = row["code"]
        acc = accounting_row(accounting, code)
        sicc_value = float(acc["net_balance"]) if acc is not None else 0.0
        difference = sicc_value - float(row["gross_value"])
        if abs(difference) > tolerance or acc is None:
            records.append({
                "Componente": "Valor bruto",
                "Conta SICC": code,
                "Conta(s) Primavera": code,
                "Descrição": row["description"],
                "SICC": sicc_value,
                "Primavera": float(row["gross_value"]),
                "Diferença SICC - Primavera": difference,
                "Nível de comparação": "Conta individual",
                "Observação": "Conta inexistente no SICC" if acc is None else "Diferença na conta de ativo",
            })

    # Depreciação do período e do exercício: contas 642 finais efetivamente existentes no SICC.
    sicc_642 = leaf_rows(accounting[accounting["account"].str.startswith("642")], "account")
    for _, acc in sicc_642.iterrows():
        suffix = str(acc["account"])[3:]
        asset_prefix = "43" + suffix
        linked = prim_leaf[prim_leaf["code"].str.startswith(asset_prefix)]
        if linked.empty:
            continue
        add_difference(records, "Depreciação do período", str(acc["account"]), linked,
                       float(acc["period_net"]), "depreciation_period", str(acc["description"]), tolerance,
                       f"Grupo {asset_prefix}*", "Movimento do período da 642 versus Depreciação — Período")
        add_difference(records, "Depreciação do exercício", str(acc["account"]), linked,
                       float(acc["net_balance"]), "depreciation_exercise", str(acc["description"]), tolerance,
                       f"Grupo {asset_prefix}*", "Saldo da 642 versus Depreciação — Exercício")

    # Depreciação e imparidade acumuladas: contas finais 438/439.
    for sicc_prefix, component, primavera_column in (
        ("438", "Depreciação acumulada", "accumulated_depreciation"),
        ("439", "Imparidade acumulada", "accumulated_impairment"),
    ):
        sicc_rows = leaf_rows(accounting[accounting["account"].str.startswith(sicc_prefix)], "account")
        for _, acc in sicc_rows.iterrows():
            suffix = str(acc["account"])[3:]
            asset_prefix = "43" + suffix
            linked = prim_leaf[prim_leaf["code"].str.startswith(asset_prefix)]
            if linked.empty:
                continue
            sicc_value = float(acc["credit_balance"] - acc["debit_balance"])
            add_difference(records, component, str(acc["account"]), linked, sicc_value, primavera_column,
                           str(acc["description"]), tolerance, f"Grupo {asset_prefix}*",
                           f"Saldo da {sicc_prefix} versus total acumulado do Primavera")

    result = pd.DataFrame(records)
    columns = ["Componente", "Conta SICC", "Conta(s) Primavera", "Descrição", "SICC", "Primavera",
               "Diferença SICC - Primavera", "Nível de comparação", "Observação", "Diferença absoluta"]
    if result.empty:
        return pd.DataFrame(columns=columns)
    result["Diferença absoluta"] = result["Diferença SICC - Primavera"].abs()
    return result.sort_values("Diferença absoluta", ascending=False).reset_index(drop=True)


def validate_asset_depreciation(assets: pd.DataFrame, accounting: pd.DataFrame, tolerance: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    items = assets[~assets["is_account"]].copy()
    year = accounting.attrs.get("report_year")
    month = accounting.attrs.get("report_month")
    report_date = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0) if year and month else pd.Timestamp.today()

    items["is_land"] = items["asset_account"].str.startswith("431") | items["description"].map(normalize_text).str.contains(r"\bterreno\b")
    items["not_in_use_yet"] = items["use_date"].notna() & (items["use_date"] > report_date)
    items["remaining_depreciable"] = (items["carrying_amount"] - items["residual_value"]).clip(lower=0)
    items["fully_depreciated"] = items["remaining_depreciable"] <= tolerance
    items["eligible"] = (~items["is_land"]) & (~items["not_in_use_yet"]) & (~items["fully_depreciated"]) & (items["gross_value"] > tolerance)
    items["indicative_monthly_depreciation"] = (
        (items["gross_value"] - items["residual_value"]).clip(lower=0) * items["rate"] / 100 / 12
    )

    warning_records: list[dict] = []
    for _, row in items[items["eligible"]].iterrows():
        reasons: list[str] = []
        severity = ""
        if row["rate"] <= 0:
            reasons.append("Taxa de depreciação zero ou não preenchida")
            severity = "Crítica"
        if abs(row["depreciation_period"]) <= ZERO_DEPRECIATION_THRESHOLD:
            reasons.append("Sem depreciação no período")
            severity = "Crítica"
        if row["depreciation_exercise"] + tolerance < row["depreciation_period"]:
            reasons.append("Depreciação do exercício inferior à do período")
            severity = severity or "Alta"
        if row["accumulated_depreciation"] + tolerance < row["depreciation_exercise"]:
            reasons.append("Depreciação acumulada inferior à do exercício")
            severity = severity or "Alta"
        if reasons:
            warning_records.append({
                "Prioridade": severity,
                "Ficha": row["code"],
                "Conta do ativo": row["asset_account"],
                "Descrição": row["description"],
                "Data de utilização": row["use_date"],
                "Taxa (%)": row["rate"],
                "Valor contabilístico": row["gross_value"],
                "Valor residual": row["residual_value"],
                "Quantia escriturada": row["carrying_amount"],
                "Valor depreciável remanescente": row["remaining_depreciable"],
                "Depreciação indicativa mensal": row["indicative_monthly_depreciation"],
                "Depreciação do período": row["depreciation_period"],
                "Depreciação do exercício": row["depreciation_exercise"],
                "Depreciação acumulada": row["accumulated_depreciation"],
                "Anomalia": "; ".join(reasons),
            })

    warnings = pd.DataFrame(warning_records)
    if not warnings.empty:
        order = pd.Categorical(warnings["Prioridade"], ["Crítica", "Alta", "Média", "Baixa"], ordered=True)
        warnings = warnings.assign(_order=order).sort_values(["_order", "Valor depreciável remanescente"], ascending=[True, False]).drop(columns="_order")

    control_summary = pd.DataFrame([
        {"Controlo": "Total de fichas de ativos", "Quantidade": len(items), "Valor": float(items["gross_value"].sum())},
        {"Controlo": "Terrenos excluídos", "Quantidade": int(items["is_land"].sum()), "Valor": float(items.loc[items["is_land"], "gross_value"].sum())},
        {"Controlo": "Bens totalmente depreciados", "Quantidade": int(items["fully_depreciated"].sum()), "Valor": float(items.loc[items["fully_depreciated"], "gross_value"].sum())},
        {"Controlo": "Bens sujeitos a depreciação no período", "Quantidade": int(items["eligible"].sum()), "Valor": float(items.loc[items["eligible"], "gross_value"].sum())},
        {"Controlo": "Possíveis bens sem depreciação", "Quantidade": int(((items["eligible"]) & (items["depreciation_period"].abs() <= ZERO_DEPRECIATION_THRESHOLD)).sum()), "Valor": float(items.loc[(items["eligible"]) & (items["depreciation_period"].abs() <= ZERO_DEPRECIATION_THRESHOLD), "remaining_depreciable"].sum())},
        {"Controlo": "Bens elegíveis com taxa zero", "Quantidade": int(((items["eligible"]) & (items["rate"] <= 0)).sum()), "Valor": float(items.loc[(items["eligible"]) & (items["rate"] <= 0), "remaining_depreciable"].sum())},
    ])
    return warnings, control_summary


def reconcile(accounting: pd.DataFrame, assets: pd.DataFrame, tolerance: float) -> ReconciliationResult:
    total_43 = assets[assets["is_account"] & (assets["code"] == "43")]
    if total_43.empty:
        raise ValueError("O balancete Primavera não contém a conta total 43.")
    prim_total = total_43.iloc[0]

    def sicc_value(account: str, column: str, invert: bool = False) -> float:
        row = accounting_row(accounting, account)
        if row is None:
            return 0.0
        value = float(row[column])
        return -value if invert else value

    # 43 no SICC é líquido de 438/439; reconstruir o bruto.
    sicc_43 = accounting_row(accounting, "43")
    if sicc_43 is None:
        raise ValueError("O balancete SICC não contém a conta 43.")
    dep_438 = accounting_row(accounting, "438")
    imp_439 = accounting_row(accounting, "439")
    sicc_acc_dep = float(dep_438["credit_balance"] - dep_438["debit_balance"]) if dep_438 is not None else 0.0
    sicc_acc_imp = float(imp_439["credit_balance"] - imp_439["debit_balance"]) if imp_439 is not None else 0.0
    sicc_net = float(sicc_43["net_balance"])
    sicc_gross = sicc_net + sicc_acc_dep + sicc_acc_imp

    row_642 = accounting_row(accounting, "642")
    sicc_period = float(row_642["period_net"]) if row_642 is not None else 0.0
    sicc_exercise = float(row_642["net_balance"]) if row_642 is not None else 0.0

    summary = pd.DataFrame([
        {"Componente": "Valor bruto", "Conta SICC": "43 + 438 + 439", "SICC": sicc_gross, "Primavera": float(prim_total["gross_value"])},
        {"Componente": "Depreciação do período", "Conta SICC": "642 — movimento do período", "SICC": sicc_period, "Primavera": float(prim_total["depreciation_period"])},
        {"Componente": "Depreciação do exercício", "Conta SICC": "642 — saldo", "SICC": sicc_exercise, "Primavera": float(prim_total["depreciation_exercise"])},
        {"Componente": "Depreciação acumulada", "Conta SICC": "438 — saldo credor", "SICC": sicc_acc_dep, "Primavera": float(prim_total["accumulated_depreciation"])},
        {"Componente": "Imparidade acumulada", "Conta SICC": "439 — saldo credor", "SICC": sicc_acc_imp, "Primavera": float(prim_total["accumulated_impairment"])},
        {"Componente": "Quantia escriturada", "Conta SICC": "43 — saldo líquido", "SICC": sicc_net, "Primavera": float(prim_total["carrying_amount"])},
    ])
    summary["Diferença SICC - Primavera"] = summary["SICC"] - summary["Primavera"]
    summary["Estado"] = summary["Diferença SICC - Primavera"].abs().map(lambda x: "OK" if x <= tolerance else "Divergência")

    account_differences = build_account_differences(accounting, assets, tolerance)
    warnings, control_summary = validate_asset_depreciation(assets, accounting, tolerance)

    technical = assets[assets["is_account"] & assets["code"].str.startswith("43")].copy()
    technical = technical[["code", "description", "gross_value", "depreciation_period", "depreciation_exercise",
                           "accumulated_depreciation", "accumulated_impairment", "carrying_amount"]]
    return ReconciliationResult(summary, account_differences, technical, warnings, control_summary, accounting, assets)


def format_currency(df: pd.DataFrame, columns: list[str]) -> pd.io.formats.style.Styler:
    fmt = {c: "{:,.2f} €" for c in columns if c in df.columns}
    styler = df.style.format(fmt)
    if "Estado" in df.columns:
        styler = styler.map(
            lambda v: "background-color: #ffe6e6" if v == "Divergência" else ("background-color: #e7f6e7" if v == "OK" else ""),
            subset=["Estado"],
        )
    return styler


def to_excel(result: ReconciliationResult) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        result.summary.to_excel(writer, sheet_name="Resumo", index=False)
        result.account_differences.to_excel(writer, sheet_name="Contas divergentes", index=False)
        result.asset_control_summary.to_excel(writer, sheet_name="Controlo fichas", index=False)
        result.asset_warnings.to_excel(writer, sheet_name="Bens a verificar", index=False)
        result.technical_detail.to_excel(writer, sheet_name="Primavera por conta", index=False)
        result.accounting.to_excel(writer, sheet_name="SICC normalizado", index=False)
        result.assets.to_excel(writer, sheet_name="Primavera normalizado", index=False)
        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for column_cells in ws.columns:
                max_len = min(max(len(str(cell.value or "")) for cell in column_cells) + 2, 55)
                ws.column_dimensions[column_cells[0].column_letter].width = max_len
    return output.getvalue()


st.title("Reconciliação do Balancete Contabilístico com o Registo de Ativos")
st.caption("Cruza valor bruto, depreciação do período, do exercício e acumulada, e deteta fichas de ativos potencialmente não depreciadas.")

with st.sidebar:
    st.header("Parâmetros")
    tolerance = st.number_input("Tolerância (€)", min_value=0.0, value=TOLERANCE_DEFAULT, step=0.01, format="%.2f")

col1, col2 = st.columns(2)
with col1:
    sicc_file = st.file_uploader("Balancete da contabilidade — SICC (CSV)", type=["csv"])
with col2:
    primavera_file = st.file_uploader("Balancete do registo de ativos — Primavera (XLSX)", type=["xlsx"])

if sicc_file and primavera_file:
    try:
        accounting = load_sicc(sicc_file)
        assets = load_primavera(primavera_file)
        result = reconcile(accounting, assets, tolerance)

        tab1, tab2, tab3, tab4 = st.tabs([
            "Resumo", "Divergências por conta", "Bens sem depreciação", "Dados técnicos"
        ])

        with tab1:
            st.subheader("Resumo global")
            st.dataframe(format_currency(result.summary, ["SICC", "Primavera", "Diferença SICC - Primavera"]),
                         use_container_width=True, hide_index=True)
            metrics = {row["Componente"]: row["Diferença SICC - Primavera"] for _, row in result.summary.iterrows()}
            k1, k2, k3 = st.columns(3)
            k1.metric("Diferença — período", f"{metrics.get('Depreciação do período', 0):,.2f} €")
            k2.metric("Diferença — exercício", f"{metrics.get('Depreciação do exercício', 0):,.2f} €")
            k3.metric("Diferença — acumulada", f"{metrics.get('Depreciação acumulada', 0):,.2f} €")

        with tab2:
            st.subheader("Contas responsáveis pelas divergências")
            st.caption("Período: movimento da 642. Exercício: saldo da 642. Acumulada: saldo credor da 438.")
            differences = result.account_differences.copy()
            options = differences["Componente"].drop_duplicates().tolist() if not differences.empty else []
            selected = st.multiselect("Componente", options=options, default=options)
            if selected:
                differences = differences[differences["Componente"].isin(selected)]
            st.dataframe(format_currency(differences, ["SICC", "Primavera", "Diferença SICC - Primavera", "Diferença absoluta"]),
                         use_container_width=True, hide_index=True)

        with tab3:
            st.subheader("Validação das fichas de ativos")
            st.caption("Exclui terrenos, bens ainda não colocados em utilização e bens totalmente depreciados. Sinaliza os restantes quando não têm depreciação no período ou apresentam incoerências.")
            st.dataframe(format_currency(result.asset_control_summary, ["Valor"]), use_container_width=True, hide_index=True)
            if result.asset_warnings.empty:
                st.success("Não foram identificados bens amortizáveis sem depreciação no período nem incoerências básicas entre período, exercício e acumulada.")
            else:
                st.warning(f"Foram identificadas {len(result.asset_warnings)} fichas para verificação.")
                st.dataframe(format_currency(result.asset_warnings, [
                    "Valor contabilístico", "Valor residual", "Quantia escriturada",
                    "Valor depreciável remanescente", "Depreciação indicativa mensal",
                    "Depreciação do período", "Depreciação do exercício", "Depreciação acumulada",
                ]), use_container_width=True, hide_index=True)

        with tab4:
            st.subheader("Dados normalizados")
            with st.expander("Primavera por conta"):
                st.dataframe(result.technical_detail, use_container_width=True, hide_index=True)
            with st.expander("SICC normalizado"):
                st.dataframe(result.accounting, use_container_width=True, hide_index=True)

        st.download_button(
            "Descarregar relatório Excel",
            data=to_excel(result),
            file_name="relatorio_reconciliacao_ativos.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as exc:
        st.error(f"Não foi possível processar os ficheiros: {exc}")
        st.exception(exc)
else:
    st.info("Carregue os dois ficheiros para iniciar a reconciliação.")

with st.expander("Critérios aplicados"):
    st.markdown(
        """
- **Depreciação do período:** Primavera `Depreciação — Período` versus movimento líquido do período nas contas `642x`.
- **Depreciação do exercício:** Primavera `Depreciação — Exercício` versus saldo líquido das contas `642x`.
- **Depreciação acumulada:** Primavera `Depreciação — Acumulada` versus saldo credor das contas `438x`.
- **Bens sem depreciação:** são excluídos terrenos (`431`), bens ainda não utilizados e bens totalmente depreciados. Os restantes são sinalizados quando o valor do período é zero.
- A depreciação mensal indicativa é apenas um controlo auxiliar: `(valor contabilístico − valor residual) × taxa ÷ 12`.
        """
    )
