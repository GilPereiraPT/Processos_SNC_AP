from __future__ import annotations

import io
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import BinaryIO

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Reconciliação Contabilidade × Ativos", page_icon="📊", layout="wide")
TOLERANCE_DEFAULT = 0.10


def norm_text(value: object) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text.strip().lower())


def norm_code(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return re.sub(r"[^0-9A-Za-z]", "", text)


def money(value: object) -> float:
    if value is None or pd.isna(value):
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
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("latin1", errors="replace")


def load_sicc(uploaded: BinaryIO) -> pd.DataFrame:
    text = decode_csv(uploaded.read())
    lines = text.splitlines()
    header_idx = next((i for i, line in enumerate(lines) if norm_text(line).startswith("conta;designacao da conta")), None)
    if header_idx is None:
        raise ValueError("Não foi encontrado o cabeçalho do balancete SICC.")

    df = pd.read_csv(io.StringIO("\n".join(lines[header_idx:])), sep=";", dtype=str)
    df = df.loc[:, ~df.columns.str.match(r"^Unnamed")]
    df.columns = [norm_text(c) for c in df.columns]
    required = {
        "conta", "designacao da conta", "valor a debito", "valor a credito",
        "valor acumulado a debito", "valor acumulado a credito",
        "saldo a debito", "saldo a credito",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Faltam colunas no SICC: {', '.join(sorted(missing))}")

    out = pd.DataFrame({
        "account": df["conta"].map(norm_code),
        "description": df["designacao da conta"].fillna(""),
        "period_debit": df["valor a debito"].map(money),
        "period_credit": df["valor a credito"].map(money),
        "accum_debit": df["valor acumulado a debito"].map(money),
        "accum_credit": df["valor acumulado a credito"].map(money),
        "balance_debit": df["saldo a debito"].map(money),
        "balance_credit": df["saldo a credito"].map(money),
    })
    out["period_net_debit"] = out["period_debit"] - out["period_credit"]
    out["exercise_net_debit"] = out["balance_debit"] - out["balance_credit"]
    out["accumulated_credit_balance"] = out["balance_credit"] - out["balance_debit"]
    return out[out["account"] != ""].reset_index(drop=True)


def find_header(raw: pd.DataFrame) -> int:
    for idx in range(min(30, len(raw))):
        vals = {norm_text(v) for v in raw.iloc[idx].tolist() if pd.notna(v)}
        if {"codigo", "descricao", "valor contabilistico"}.issubset(vals):
            return idx
    raise ValueError("Não foi encontrado o cabeçalho do balancete Primavera.")


def load_primavera(uploaded: BinaryIO) -> pd.DataFrame:
    raw = pd.read_excel(io.BytesIO(uploaded.read()), header=None, engine="openpyxl")
    h = find_header(raw)
    header = [norm_text(v) for v in raw.iloc[h].tolist()]
    df = raw.iloc[h + 1:].copy()
    df.columns = header

    cols = list(df.columns)
    code_pos = cols.index("codigo")
    desc_pos = cols.index("descricao")
    date_pos = cols.index("data utilizacao")
    gross_pos = cols.index("valor contabilistico")
    residual_pos = cols.index("valor residual")
    rate_pos = cols.index("taxa")
    carrying_pos = cols.index("quantia escriturada")

    out = pd.DataFrame({
        "code_raw": df.iloc[:, code_pos],
        "code": df.iloc[:, code_pos].map(norm_code),
        "description": df.iloc[:, desc_pos].fillna(""),
        "use_date": pd.to_datetime(df.iloc[:, date_pos], errors="coerce"),
        "gross_value": df.iloc[:, gross_pos].map(money),
        "residual_value": df.iloc[:, residual_pos].map(money),
        "rate": df.iloc[:, rate_pos].map(money),
        "dep_period": df.iloc[:, 7].map(money),
        "dep_exercise": df.iloc[:, 8].map(money),
        "dep_accumulated": df.iloc[:, 9].map(money),
        "imp_period": df.iloc[:, 10].map(money),
        "imp_exercise": df.iloc[:, 11].map(money),
        "imp_accumulated": df.iloc[:, 12].map(money),
        "carrying_amount": df.iloc[:, carrying_pos].map(money),
    })
    out["is_account"] = out["code_raw"].map(
        lambda v: bool(v is not None and not pd.isna(v) and not str(v).startswith(" "))
    )
    out = out[out["code"] != ""].reset_index(drop=True)

    # Cada ficha herda a conta analítica de ativo mais recente:
    # 431–437 para ativos fixos tangíveis e 443 para ativos intangíveis.
    current_account = ""
    assigned = []
    for _, row in out.iterrows():
        code = row["code"]
        is_aft = code.startswith(("431", "432", "433", "434", "435", "436", "437"))
        is_intangible = code.startswith("443")
        if row["is_account"] and (is_aft or is_intangible):
            current_account = code
        assigned.append(current_account)
    out["asset_account"] = assigned
    return out


def leaf_rows(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    part = df[df["account"].str.startswith(prefix)].copy()
    codes = part["account"].tolist()
    part["is_leaf"] = [not any(other.startswith(code) and other != code for other in codes) for code in codes]
    return part[part["is_leaf"]].copy()


def asset_prefix_from_account(account: str, source_prefix: str, target_prefix: str) -> str:
    """Converte uma conta SICC na raiz da conta de ativo correspondente no Primavera."""
    return target_prefix + account[len(source_prefix):]


def compare_depreciation(sicc: pd.DataFrame, primavera: pd.DataFrame, tolerance: float) -> pd.DataFrame:
    items = primavera[~primavera["is_account"] & primavera["asset_account"].str.startswith(("431", "432", "433", "434", "435", "436", "437", "443"))].copy()
    records = []

    rules = [
        ("642", "43", "AFT — depreciação do período", "period_net_debit", "dep_period"),
        ("642", "43", "AFT — depreciação do exercício", "exercise_net_debit", "dep_exercise"),
        ("438", "43", "AFT — depreciação acumulada", "accumulated_credit_balance", "dep_accumulated"),
        ("643", "443", "Intangíveis — amortização do período", "period_net_debit", "dep_period"),
        ("643", "443", "Intangíveis — amortização do exercício", "exercise_net_debit", "dep_exercise"),
        ("4483", "443", "Intangíveis — amortização acumulada", "accumulated_credit_balance", "dep_accumulated"),
    ]

    for source_prefix, target_prefix, component, sicc_col, prim_col in rules:
        rows = leaf_rows(sicc, source_prefix)
        target_items = items[items["asset_account"].str.startswith(target_prefix)]
        if rows.empty:
            records.append({
                "Componente": component, "Conta SICC": "—", "Conta(s) Primavera": target_prefix + "…",
                "Descrição SICC": "Conta não incluída no ficheiro", "SICC": pd.NA,
                "Primavera": float(target_items[prim_col].sum()), "Diferença": pd.NA,
                "Estado": "Não disponível",
            })
            continue

        for _, r in rows.iterrows():
            asset_prefix = asset_prefix_from_account(r["account"], source_prefix, target_prefix)
            matched = target_items[target_items["asset_account"].str.startswith(asset_prefix)]
            prim_value = float(matched[prim_col].sum())
            sicc_value = float(r[sicc_col])
            diff = sicc_value - prim_value
            prim_accounts = ", ".join(sorted(matched["asset_account"].dropna().unique())) or asset_prefix
            records.append({
                "Componente": component,
                "Conta SICC": r["account"],
                "Conta(s) Primavera": prim_accounts,
                "Descrição SICC": r["description"],
                "SICC": sicc_value,
                "Primavera": prim_value,
                "Diferença": diff,
                "Estado": "OK" if abs(diff) <= tolerance else "Divergência",
            })
    return pd.DataFrame(records)


def global_summary(sicc: pd.DataFrame, primavera: pd.DataFrame, detail: pd.DataFrame, tolerance: float) -> pd.DataFrame:
    items = primavera[~primavera["is_account"] & primavera["asset_account"].str.startswith(("431", "432", "433", "434", "435", "436", "437", "443"))]
    rows = []
    rules = [
        ("AFT — depreciação do período", "642", "43", "period_net_debit", "dep_period"),
        ("AFT — depreciação do exercício", "642", "43", "exercise_net_debit", "dep_exercise"),
        ("AFT — depreciação acumulada", "438", "43", "accumulated_credit_balance", "dep_accumulated"),
        ("Intangíveis — amortização do período", "643", "443", "period_net_debit", "dep_period"),
        ("Intangíveis — amortização do exercício", "643", "443", "exercise_net_debit", "dep_exercise"),
        ("Intangíveis — amortização acumulada", "4483", "443", "accumulated_credit_balance", "dep_accumulated"),
    ]
    for component, prefix, target_prefix, sicc_col, prim_col in rules:
        src = leaf_rows(sicc, prefix)
        target_items = items[items["asset_account"].str.startswith(target_prefix)]
        prim = float(target_items[prim_col].sum())
        if src.empty:
            rows.append({"Componente": component, "SICC": pd.NA, "Primavera": prim, "Diferença": pd.NA, "Estado": "Não disponível"})
        else:
            val = float(src[sicc_col].sum())
            diff = val - prim
            rows.append({"Componente": component, "SICC": val, "Primavera": prim, "Diferença": diff, "Estado": "OK" if abs(diff) <= tolerance else "Divergência"})

    # Valor contabilístico: 431–437 para AFT e 443 para intangíveis, quando presentes no SICC.
    for label, prefixes, prim_prefix in [
        ("Valor contabilístico AFT", ("431", "432", "433", "434", "435", "436", "437"), "43"),
        ("Valor contabilístico intangíveis", ("443",), "443"),
    ]:
        src_parts = [leaf_rows(sicc, prefix) for prefix in prefixes]
        src_parts = [part for part in src_parts if not part.empty]
        target_items = items[items["asset_account"].str.startswith(prim_prefix)]
        prim = float(target_items["gross_value"].sum())
        if not src_parts:
            rows.append({"Componente": label, "SICC": pd.NA, "Primavera": prim, "Diferença": pd.NA, "Estado": "Não disponível"})
        else:
            src = pd.concat(src_parts, ignore_index=True).drop_duplicates(subset=["account"] )
            val = float(src["exercise_net_debit"].sum())
            diff = val - prim
            rows.append({"Componente": label, "SICC": val, "Primavera": prim, "Diferença": diff, "Estado": "OK" if abs(diff) <= tolerance else "Divergência"})
    return pd.DataFrame(rows)


def validate_assets(primavera: pd.DataFrame, tolerance: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    items = primavera[~primavera["is_account"] & primavera["asset_account"].str.startswith(("431", "432", "433", "434", "435", "436", "437", "443"))].copy()
    items["remaining_depreciable"] = (items["gross_value"] - items["residual_value"] - items["dep_accumulated"]).clip(lower=0)
    desc = items["description"].map(norm_text)
    items["is_land"] = items["asset_account"].str.startswith("431") | desc.str.contains(r"\bterreno|recurso natural", regex=True)
    items["fully_depreciated"] = items["remaining_depreciable"] <= tolerance
    items["not_in_use"] = items["use_date"].isna()
    items["eligible"] = ~items["is_land"] & ~items["fully_depreciated"] & ~items["not_in_use"]

    def reason(row: pd.Series) -> str:
        reasons = []
        if row["eligible"] and row["dep_period"] <= tolerance:
            reasons.append("Sem depreciação no período")
        if row["eligible"] and row["rate"] <= 0:
            reasons.append("Taxa de depreciação zero/não preenchida")
        if row["dep_exercise"] + tolerance < row["dep_period"]:
            reasons.append("Exercício inferior ao período")
        if row["dep_accumulated"] + tolerance < row["dep_exercise"]:
            reasons.append("Acumulada inferior ao exercício")
        return "; ".join(reasons)

    items["Motivo"] = items.apply(reason, axis=1)
    issues = items[items["Motivo"] != ""].copy()
    cols = ["code", "asset_account", "description", "use_date", "rate", "gross_value", "residual_value", "carrying_amount", "remaining_depreciable", "dep_period", "dep_exercise", "dep_accumulated", "Motivo"]
    issues = issues[cols].rename(columns={
        "code": "Ficha", "asset_account": "Conta", "description": "Descrição", "use_date": "Data utilização",
        "rate": "Taxa", "gross_value": "Valor contabilístico", "residual_value": "Valor residual",
        "carrying_amount": "Quantia escriturada", "remaining_depreciable": "Valor por depreciar",
        "dep_period": "Depreciação período", "dep_exercise": "Depreciação exercício",
        "dep_accumulated": "Depreciação acumulada",
    })
    summary = pd.DataFrame([
        {"Controlo": "Fichas analisadas", "Quantidade": len(items)},
        {"Controlo": "Terrenos excluídos", "Quantidade": int(items["is_land"].sum())},
        {"Controlo": "Totalmente depreciados", "Quantidade": int(items["fully_depreciated"].sum())},
        {"Controlo": "Sem data de utilização", "Quantidade": int(items["not_in_use"].sum())},
        {"Controlo": "Bens sujeitos a depreciação", "Quantidade": int(items["eligible"].sum())},
        {"Controlo": "Bens a verificar", "Quantidade": len(issues)},
    ])
    return summary, issues


def style_money(df: pd.DataFrame, cols: list[str]):
    fmt = {c: "{:,.2f} €" for c in cols if c in df.columns}
    return df.style.format(fmt, na_rep="—")


def to_excel(summary, detail, control_summary, issues, sicc, primavera) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary.to_excel(writer, "Resumo", index=False)
        detail.to_excel(writer, "Contas divergentes", index=False)
        control_summary.to_excel(writer, "Controlo fichas", index=False)
        issues.to_excel(writer, "Bens a verificar", index=False)
        sicc.to_excel(writer, "SICC normalizado", index=False)
        primavera.to_excel(writer, "Primavera normalizado", index=False)
        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for cells in ws.columns:
                ws.column_dimensions[cells[0].column_letter].width = min(max(len(str(c.value or "")) for c in cells) + 2, 45)
    return output.getvalue()


st.title("Reconciliação da Contabilidade com o Registo de Ativos")
st.caption("Compatível com balancetes SICC que contenham apenas contas com movimento. As verificações indisponíveis são identificadas, nunca tratadas como diferença zero.")

with st.sidebar:
    tolerance = st.number_input("Tolerância (€)", min_value=0.0, value=TOLERANCE_DEFAULT, step=0.01, format="%.2f")
    only_differences = st.checkbox("Mostrar apenas divergências", value=True)

c1, c2 = st.columns(2)
with c1:
    sicc_file = st.file_uploader("Balancete SICC (CSV)", type=["csv"])
with c2:
    primavera_file = st.file_uploader("Balancete Primavera (XLSX)", type=["xlsx"])

if sicc_file and primavera_file:
    try:
        sicc = load_sicc(sicc_file)
        primavera = load_primavera(primavera_file)
        detail = compare_depreciation(sicc, primavera, tolerance)
        summary = global_summary(sicc, primavera, detail, tolerance)
        control_summary, issues = validate_assets(primavera, tolerance)

        available = []
        for prefix, label in [("642", "642 — depreciações dos AFT"), ("643", "643 — amortizações dos intangíveis"), ("438", "438 — depreciações acumuladas dos AFT"), ("4483", "4483 — amortizações acumuladas dos intangíveis"), ("431", "431–437 — valor contabilístico dos AFT"), ("443", "443 — valor contabilístico dos intangíveis")]:
            available.append({"Grupo": label, "Incluído no SICC": "Sim" if ((sicc["account"].str.startswith(("431", "432", "433", "434", "435", "436", "437")).any()) if prefix == "431" else sicc["account"].str.startswith(prefix).any()) else "Não"})
        st.subheader("Cobertura do ficheiro SICC")
        st.dataframe(pd.DataFrame(available), use_container_width=True, hide_index=True)

        st.subheader("Resumo da reconciliação")
        st.dataframe(style_money(summary, ["SICC", "Primavera", "Diferença"]), use_container_width=True, hide_index=True)

        shown = detail.copy()
        if only_differences:
            shown = shown[shown["Estado"].isin(["Divergência", "Não disponível"])]
        shown = shown.sort_values(["Componente", "Conta SICC"])
        st.subheader("Reconciliação por conta")
        st.dataframe(style_money(shown, ["SICC", "Primavera", "Diferença"]), use_container_width=True, hide_index=True)

        st.subheader("Validação das fichas de ativos")
        st.dataframe(control_summary, use_container_width=True, hide_index=True)
        if issues.empty:
            st.success("Não foram encontrados bens amortizáveis sem depreciação no período nem inconsistências entre período, exercício e acumulada.")
        else:
            st.warning(f"Foram identificadas {len(issues)} fichas a verificar.")
            st.dataframe(style_money(issues, ["Valor contabilístico", "Valor residual", "Quantia escriturada", "Valor por depreciar", "Depreciação período", "Depreciação exercício", "Depreciação acumulada"]), use_container_width=True, hide_index=True)

        st.download_button(
            "Descarregar relatório Excel",
            data=to_excel(summary, detail, control_summary, issues, sicc, primavera),
            file_name="relatorio_reconciliacao_ativos.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as exc:
        st.error(f"Não foi possível processar os ficheiros: {exc}")
        st.exception(exc)
else:
    st.info("Carregue os dois ficheiros para iniciar a reconciliação.")

with st.expander("Lógica aplicada"):
    st.markdown("""
- **AFT:** contas Primavera **431–437** ↔ valor contabilístico SICC **431–437**; período/exercício ↔ **642**; acumulada ↔ saldo credor **438**.
- **Intangíveis:** conta Primavera **443** ↔ valor contabilístico SICC **443**; período/exercício ↔ **643**; acumulada ↔ saldo credor **4483**.
- Nas contas **642/643**, o período é **valor a débito − valor a crédito** e o exercício é **saldo a débito − saldo a crédito**.
- Nas contas **438/4483**, a acumulada é **saldo a crédito − saldo a débito**.
- Os cruzamentos patrimoniais só são efetuados quando as respetivas contas constam do ficheiro SICC.
- Terrenos, bens totalmente depreciados e fichas sem data de utilização são excluídos do teste de ausência de depreciação.
- Uma conta ausente no ficheiro de movimentos é marcada como **Não disponível**, e não como zero.
""")
