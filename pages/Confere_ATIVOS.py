from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import BinaryIO

import pandas as pd
import streamlit as st


st.set_page_config(page_title="Reconciliação Contabilidade × Ativos", page_icon="📊", layout="wide")

TOLERANCE_DEFAULT = 0.10


@dataclass
class ReconciliationResult:
    summary: pd.DataFrame
    detail: pd.DataFrame
    account_differences: pd.DataFrame
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
    # Portuguese number format: 1.234,56; also tolerates 1234.56.
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
        "conta",
        "designacao da conta",
        "saldo a debito",
        "saldo a credito",
        "valor acumulado a debito",
        "valor acumulado a credito",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Faltam colunas no SICC: {', '.join(sorted(missing))}")

    out = pd.DataFrame({
        "account": df["conta"].map(normalize_code),
        "description": df["designacao da conta"].fillna(""),
        "debit_balance": df["saldo a debito"].map(money_to_float),
        "credit_balance": df["saldo a credito"].map(money_to_float),
        "accum_debit": df["valor acumulado a debito"].map(money_to_float),
        "accum_credit": df["valor acumulado a credito"].map(money_to_float),
    })
    out["net_balance"] = out["debit_balance"] - out["credit_balance"]
    return out[out["account"] != ""].reset_index(drop=True)


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

    # The report has a two-row header; the useful names are on the second row.
    header = [normalize_text(v) for v in raw.iloc[header_idx].tolist()]
    df = raw.iloc[header_idx + 1:].copy()
    df.columns = header

    # Duplicate blank/ambiguous headings are identified by their report positions.
    columns = list(df.columns)
    code_pos = columns.index("codigo")
    desc_pos = columns.index("descricao")
    gross_pos = columns.index("valor contabilistico")
    residual_pos = columns.index("valor residual")
    accumulated_dep_pos = 9  # "Acumulada" under Depreciação
    accumulated_imp_pos = 12  # "Acumulada" under Imparidade
    carrying_pos = columns.index("quantia escriturada")

    out = pd.DataFrame({
        "code_raw": df.iloc[:, code_pos],
        "code": df.iloc[:, code_pos].map(normalize_code),
        "description": df.iloc[:, desc_pos].fillna(""),
        "gross_value": df.iloc[:, gross_pos].map(money_to_float),
        "residual_value": df.iloc[:, residual_pos].map(money_to_float),
        "accumulated_depreciation": df.iloc[:, accumulated_dep_pos].map(money_to_float),
        "accumulated_impairment": df.iloc[:, accumulated_imp_pos].map(money_to_float),
        "carrying_amount": df.iloc[:, carrying_pos].map(money_to_float),
    })
    out["is_account"] = out["code_raw"].map(
        lambda v: bool(v is not None and not (isinstance(v, float) and pd.isna(v)) and not str(v).startswith(" "))
    )
    return out[out["code"] != ""].reset_index(drop=True)


def accounting_row(df: pd.DataFrame, account: str) -> pd.Series | None:
    match = df[df["account"] == account]
    return None if match.empty else match.iloc[0]


def depreciation_account(asset_account: str) -> str:
    # SNC/SNC-AP: 432 -> 4382; 43331 -> 438331; 43511 -> 438511.
    if not asset_account.startswith("43") or asset_account.startswith("438"):
        return ""
    return "438" + asset_account[2:]


def impairment_account(asset_account: str) -> str:
    # Common SNC/SNC-AP mapping: 432 -> 4392; 43331 -> 439331.
    if not asset_account.startswith("43") or asset_account.startswith(("438", "439")):
        return ""
    return "439" + asset_account[2:]



def build_account_differences(accounting: pd.DataFrame, assets: pd.DataFrame, tolerance: float) -> pd.DataFrame:
    """Cria uma lista auditável de divergências sem duplicar saldos de contas agregadoras."""
    account_assets = assets[assets["is_account"] & assets["code"].str.startswith("43")].copy()
    account_assets = account_assets[~account_assets["code"].str.startswith(("438", "439"))]
    codes = account_assets["code"].tolist()
    account_assets["leaf"] = [not any(other.startswith(code) and other != code for other in codes) for code in codes]
    leaf = account_assets[account_assets["leaf"]].copy()

    records: list[dict] = []

    # Valor bruto: pode ser comparado diretamente ao nível da conta de ativo.
    for _, row in leaf.iterrows():
        code = row["code"]
        acc = accounting_row(accounting, code)
        sicc_value = float(acc["net_balance"]) if acc is not None else 0.0
        primavera_value = float(row["gross_value"])
        difference = sicc_value - primavera_value
        if abs(difference) > tolerance or acc is None:
            records.append({
                "Componente": "Valor bruto",
                "Conta SICC": code,
                "Conta(s) Primavera": code,
                "Descrição": row["description"],
                "SICC": sicc_value,
                "Primavera": primavera_value,
                "Diferença SICC - Primavera": difference,
                "Nível de comparação": "Conta individual",
                "Observação": "Conta inexistente no SICC" if acc is None else "Diferença na conta de ativo",
            })

    # Depreciações e imparidades: comparar ao nível efetivamente disponível no SICC.
    # 4382 corresponde ao grupo de ativos 432; 4383 a 433; etc.
    for component, sicc_prefix, primavera_column in (
        ("Depreciação acumulada", "438", "accumulated_depreciation"),
        ("Imparidade acumulada", "439", "accumulated_impairment"),
    ):
        group_accounts = accounting[accounting["account"].str.match(fr"^{sicc_prefix}\d$")].copy()
        expected_groups = sorted({"43" + code[2] for code in leaf["code"] if len(code) >= 3})
        sicc_group_codes = set(group_accounts["account"].tolist())
        all_sicc_codes = sorted(sicc_group_codes | {sicc_prefix + g[2:] for g in expected_groups})

        for sicc_code in all_sicc_codes:
            asset_prefix = "43" + sicc_code[3:]
            linked = leaf[leaf["code"].str.startswith(asset_prefix)]
            if linked.empty:
                continue
            acc = accounting_row(accounting, sicc_code)
            sicc_value = float(acc["credit_balance"] - acc["debit_balance"]) if acc is not None else 0.0
            primavera_value = float(linked[primavera_column].sum())
            difference = sicc_value - primavera_value
            if abs(difference) > tolerance or (acc is None and abs(primavera_value) > tolerance):
                linked_codes = ", ".join(linked["code"].astype(str).tolist())
                records.append({
                    "Componente": component,
                    "Conta SICC": sicc_code,
                    "Conta(s) Primavera": linked_codes,
                    "Descrição": str(acc["description"]) if acc is not None else f"Grupo {asset_prefix}",
                    "SICC": sicc_value,
                    "Primavera": primavera_value,
                    "Diferença SICC - Primavera": difference,
                    "Nível de comparação": f"Grupo {asset_prefix}*",
                    "Observação": (
                        "Conta de depreciação/imparidade inexistente no SICC"
                        if acc is None else
                        f"Compara {sicc_code} com a soma das contas Primavera {asset_prefix}*"
                    ),
                })

    result = pd.DataFrame(records)
    if result.empty:
        return pd.DataFrame(columns=[
            "Componente", "Conta SICC", "Conta(s) Primavera", "Descrição",
            "SICC", "Primavera", "Diferença SICC - Primavera",
            "Nível de comparação", "Observação", "Diferença absoluta",
        ])
    result["Diferença absoluta"] = result["Diferença SICC - Primavera"].abs()
    return result.sort_values("Diferença absoluta", ascending=False).reset_index(drop=True)

def reconcile(accounting: pd.DataFrame, assets: pd.DataFrame, tolerance: float) -> ReconciliationResult:
    account_rows = assets[assets["is_account"] & assets["code"].str.startswith("43")].copy()
    account_rows = account_rows[~account_rows["code"].str.startswith(("438", "439"))]

    records: list[dict] = []
    for _, asset in account_rows.iterrows():
        code = asset["code"]
        acc = accounting_row(accounting, code)
        dep_code = depreciation_account(code)
        dep = accounting_row(accounting, dep_code)
        imp_code = impairment_account(code)
        imp = accounting_row(accounting, imp_code)

        sicc_dep = float(dep["credit_balance"] - dep["debit_balance"]) if dep is not None else 0.0
        sicc_imp = float(imp["credit_balance"] - imp["debit_balance"]) if imp is not None else 0.0
        sicc_gross = float(acc["net_balance"]) if acc is not None else 0.0
        # The SICC total account 43 already incorporates the credit balances of 438/439.
        # Reconstruct its gross value before comparing it with the Primavera total.
        if code == "43":
            sicc_gross += sicc_dep + sicc_imp
        sicc_net = sicc_gross - sicc_dep - sicc_imp

        prim_gross = float(asset["gross_value"])
        prim_dep = float(asset["accumulated_depreciation"])
        prim_imp = float(asset["accumulated_impairment"])
        prim_net = float(asset["carrying_amount"])

        diff_gross = sicc_gross - prim_gross
        diff_dep = sicc_dep - prim_dep
        diff_imp = sicc_imp - prim_imp
        diff_net = sicc_net - prim_net
        max_diff = max(abs(diff_gross), abs(diff_dep), abs(diff_imp), abs(diff_net))

        records.append({
            "Conta ativo": code,
            "Descrição": asset["description"],
            "Conta depreciação": dep_code,
            "Conta imparidade": imp_code,
            "SICC bruto": sicc_gross,
            "Primavera bruto": prim_gross,
            "Dif. bruto": diff_gross,
            "SICC depreciação": sicc_dep,
            "Primavera depreciação": prim_dep,
            "Dif. depreciação": diff_dep,
            "SICC imparidade": sicc_imp,
            "Primavera imparidade": prim_imp,
            "Dif. imparidade": diff_imp,
            "SICC líquido calculado": sicc_net,
            "Primavera quantia escriturada": prim_net,
            "Dif. líquido": diff_net,
            "Estado": "Divergência" if max_diff > tolerance else "OK",
            "Maior diferença": max_diff,
        })

    detail = pd.DataFrame(records)
    # Keep leaf-level accounts for actionable analysis; parent totals remain available in full detail.
    codes = detail["Conta ativo"].tolist()
    detail["Nível final"] = [not any(other.startswith(code) and other != code for other in codes) for code in codes]

    total_row = detail[detail["Conta ativo"] == "43"]
    if total_row.empty:
        total = {
            "SICC bruto": detail.loc[detail["Nível final"], "SICC bruto"].sum(),
            "Primavera bruto": detail.loc[detail["Nível final"], "Primavera bruto"].sum(),
            "SICC depreciação": detail.loc[detail["Nível final"], "SICC depreciação"].sum(),
            "Primavera depreciação": detail.loc[detail["Nível final"], "Primavera depreciação"].sum(),
            "SICC imparidade": detail.loc[detail["Nível final"], "SICC imparidade"].sum(),
            "Primavera imparidade": detail.loc[detail["Nível final"], "Primavera imparidade"].sum(),
            "SICC líquido calculado": detail.loc[detail["Nível final"], "SICC líquido calculado"].sum(),
            "Primavera quantia escriturada": detail.loc[detail["Nível final"], "Primavera quantia escriturada"].sum(),
        }
    else:
        total = total_row.iloc[0].to_dict()

    summary = pd.DataFrame([
        {"Componente": "Valor bruto", "SICC": total["SICC bruto"], "Primavera": total["Primavera bruto"]},
        {"Componente": "Depreciação acumulada", "SICC": total["SICC depreciação"], "Primavera": total["Primavera depreciação"]},
        {"Componente": "Imparidade acumulada", "SICC": total["SICC imparidade"], "Primavera": total["Primavera imparidade"]},
        {"Componente": "Quantia escriturada", "SICC": total["SICC líquido calculado"], "Primavera": total["Primavera quantia escriturada"]},
    ])
    summary["Diferença SICC - Primavera"] = summary["SICC"] - summary["Primavera"]
    summary["Estado"] = summary["Diferença SICC - Primavera"].abs().map(lambda x: "OK" if x <= tolerance else "Divergência")
    account_differences = build_account_differences(accounting, assets, tolerance)
    return ReconciliationResult(summary, detail, account_differences, accounting, assets)


def format_currency(df: pd.DataFrame, columns: list[str]) -> pd.io.formats.style.Styler:
    return df.style.format({c: "{:,.2f} €" for c in columns}).map(
        lambda v: "background-color: #ffe6e6" if v == "Divergência" else ("background-color: #e7f6e7" if v == "OK" else ""),
        subset=["Estado"] if "Estado" in df.columns else None,
    )


def to_excel(result: ReconciliationResult) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        result.summary.to_excel(writer, sheet_name="Resumo", index=False)
        result.account_differences.to_excel(writer, sheet_name="Contas divergentes", index=False)
        result.detail.to_excel(writer, sheet_name="Reconciliação técnica", index=False)
        result.accounting.to_excel(writer, sheet_name="SICC normalizado", index=False)
        result.assets.to_excel(writer, sheet_name="Primavera normalizado", index=False)
        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for column_cells in ws.columns:
                max_len = min(max(len(str(cell.value or "")) for cell in column_cells) + 2, 45)
                ws.column_dimensions[column_cells[0].column_letter].width = max_len
    return output.getvalue()


st.title("Reconciliação do Balancete Contabilístico com o Registo de Ativos")
st.caption("Compara o balancete SICC com o balancete de ativos Primavera, separando valor bruto, depreciações, imparidades e quantia escriturada.")

with st.sidebar:
    st.header("Parâmetros")
    tolerance = st.number_input("Tolerância (€)", min_value=0.0, value=TOLERANCE_DEFAULT, step=0.01, format="%.2f")
    only_final = st.checkbox("Mostrar apenas contas de último nível", value=True)
    only_differences = st.checkbox("Mostrar apenas divergências", value=True)

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

        st.subheader("Resumo global")
        summary_currency = ["SICC", "Primavera", "Diferença SICC - Primavera"]
        st.dataframe(format_currency(result.summary, summary_currency), use_container_width=True, hide_index=True)

        net_diff = float(result.summary.loc[result.summary["Componente"] == "Quantia escriturada", "Diferença SICC - Primavera"].iloc[0])
        gross_diff = float(result.summary.loc[result.summary["Componente"] == "Valor bruto", "Diferença SICC - Primavera"].iloc[0])
        dep_diff = float(result.summary.loc[result.summary["Componente"] == "Depreciação acumulada", "Diferença SICC - Primavera"].iloc[0])
        k1, k2, k3 = st.columns(3)
        k1.metric("Diferença líquida", f"{net_diff:,.2f} €")
        k2.metric("Diferença no valor bruto", f"{gross_diff:,.2f} €")
        k3.metric("Diferença nas depreciações", f"{dep_diff:,.2f} €")

        st.subheader("Contas responsáveis pelas divergências")
        st.caption(
            "As depreciações e imparidades são comparadas ao nível efetivamente existente no SICC. "
            "Quando uma conta 438/439 agrega várias subcontas Primavera, estas são apresentadas em conjunto."
        )
        account_differences = result.account_differences.copy()
        component_filter = st.multiselect(
            "Componente a analisar",
            options=account_differences["Componente"].drop_duplicates().tolist(),
            default=account_differences["Componente"].drop_duplicates().tolist(),
        )
        if component_filter:
            account_differences = account_differences[account_differences["Componente"].isin(component_filter)]
        account_money = ["SICC", "Primavera", "Diferença SICC - Primavera", "Diferença absoluta"]
        st.dataframe(format_currency(account_differences, account_money), use_container_width=True, hide_index=True)

        with st.expander("Ver reconciliação técnica por conta Primavera"):
            detail = result.detail.copy()
            if only_final:
                detail = detail[detail["Nível final"]]
            if only_differences:
                detail = detail[detail["Estado"] == "Divergência"]
            detail = detail.sort_values("Maior diferença", ascending=False)
            money_cols = [c for c in detail.columns if c.startswith(("SICC", "Primavera", "Dif.")) or c == "Maior diferença"]
            st.dataframe(format_currency(detail, money_cols), use_container_width=True, hide_index=True)

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

with st.expander("Critério de reconciliação"):
    st.markdown(
        """
- **Valor bruto:** saldo líquido devedor da conta de ativo (431 a 437) comparado com o valor contabilístico do Primavera.
- **Depreciação acumulada:** saldo credor da conta 438 correspondente, por exemplo `43331 → 438331`.
- **Imparidade acumulada:** saldo credor da conta 439 correspondente, por exemplo `43331 → 439331`.
- **Quantia escriturada:** valor bruto menos depreciações e imparidades, comparado com a quantia escriturada do Primavera.
- Uma diferença dentro da tolerância definida é classificada como **OK**.
        """
    )
