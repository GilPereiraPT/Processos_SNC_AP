"""Sumário executivo ULSLA: apresentação premium e exportação executiva."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from html import escape
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference, BarChart
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Font, PatternFill

from pools import read_map, pool_details

NAVY = '123253'
BLUE = '216AA0'
CURRENT_COLOR = '#206B9F'
PRIOR_COLOR = '#F4B183'  # laranja claro
CURRENT_FILL = '206B9F'
PRIOR_FILL = 'F4B183'
CONTRACT_GROUP = 'Serviços Saúde - Contrato Programa'
MONTHS = ['', 'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']


def fmt(v, compact=True):
    if v is None or pd.isna(v):
        return '—'
    n = float(v)
    s = f'{n/1e6:,.2f} M€'
    return s.replace(',', '§').replace('.', ',').replace('§', '.')


def comparable(a, b):
    return (b - a, (b - a) / abs(a) * 100 if a else None) if a is not None and b is not None else (None, None)


def _calc(rec):
    d = rec.get('dr', {})
    b = rec.get('balanco', {})
    f = rec.get('dfc', {})

    def summ(keys):
        return sum(d.get(k, 0) for k in keys) if d and all(d.get(k,0) is not None for k in keys) else None

    return {
        'Resultado líquido': d.get('resultado'),
        'Rendimentos': summ(['rendimentos_impostos', 'vendas', 'prestacoes_servicos', 'transferencias', 'outros_rendimentos']),
        'Gastos': summ(['consumos', 'fse', 'pessoal', 'outros_gastos', 'depreciacoes']),
        'Caixa e depósitos': b.get('caixa'),
        'Fluxo operacional': f.get('operacional'),
        'Dívida a fornecedores': __import__('analise_executiva').accounting(rec)['total'],
        'Património líquido': b.get('patrimonio'),
        'Fundo de maneio': (b['ativo_corrente']-b['passivo_corrente']) if b.get('ativo_corrente') is not None and b.get('passivo_corrente') is not None else None,
    }


def _prior_snapshot_from_current(current):
    prior = {}
    if current.get('dr_n1'):
        prior['dr'] = current.get('dr_n1', {})
    if current.get('balanco_n1'):
        prior['balanco'] = current.get('balanco_n1', {})
    if current.get('dfc_n1'):
        prior['dfc'] = current.get('dfc_n1', {})
    return prior if prior else None


def _comparison_rows(current_section, previous_section, labels):
    rows = []
    for name, key in labels:
        a = previous_section.get(key) if previous_section else None
        b = current_section.get(key)
        diff, pct = comparable(a, b)
        rows.append({'Nome': name, 'N-1': a, 'N': b, 'Diferença': diff, 'Percentagem': pct})
    return rows


def _detail_for_period(history, period, mapping):
    rec = history.get(period)
    if not rec or not rec.get('contas_balancete'):
        return pd.DataFrame(columns=['Conta', 'Designação', 'Pool 1', 'Pool 2', 'Valor (€)', 'Estado'])

    detail = pool_details(rec, mapping, 'acumulado').copy()
    y, m = map(int, period.split('-'))
    if m == 1:
        return detail

    prev_key = f'{y}-{m-1:02d}'
    prev_rec = history.get(prev_key)
    if not prev_rec or not prev_rec.get('contas_balancete'):
        detail['Valor (€)'] = None
        return detail

    prev = pool_details(prev_rec, mapping, 'acumulado').set_index('Conta')['Valor (€)']
    detail['Valor (€)'] = detail.apply(
        lambda r: round(r['Valor (€)'] - prev[r['Conta']], 2)
        if r['Conta'] in prev.index and pd.notna(r['Valor (€)']) and pd.notna(prev[r['Conta']])
        else None,
        axis=1,
    )
    return detail


def _segment_info(history, mapping, period, prefix, title):
    yr, mon = map(int, period.split('-'))
    prior = f'{yr-1}-{mon:02d}'
    sign = -1.0 if prefix == '7' else 1.0
    totals = {}

    def grouped_for(key):
        detail = _detail_for_period(history, key, mapping)
        if detail.empty:
            return pd.Series(dtype=float)
        subset = detail[
            detail['Conta'].astype(str).str.startswith(prefix)
            & detail['Pool 1'].astype(str).ne('')
            
        ].copy()
        if subset.empty:
            return pd.Series(dtype=float)
        subset['Valor (€)'] = subset['Valor (€)'].astype(float) * sign
        return subset.groupby('Pool 1')['Valor (€)'].agg(lambda v: v.sum() if v.notna().all() else float('nan')).sort_values(ascending=False)

    # Totais do mês: diferença entre DR acumuladas de fechos consecutivos.
    # A cobertura do mapa de contas não pode eliminar um mês inteiro da DR.
    metric = 'Rendimentos' if prefix == '7' else 'Gastos'
    for year in (yr - 1, yr):
        for month in range(1, mon + 1):
            key = f'{year}-{month:02d}'
            now = _calc(history.get(key, {})).get(metric)
            previous_key = f'{year}-{month-1:02d}'
            before = 0 if month == 1 else _calc(history.get(previous_key, {})).get(metric)
            if now is not None and before is not None:
                totals[key] = round(now-before,2)

    curr = grouped_for(period)
    old = grouped_for(prior)
    rubricas = []
    for name in sorted(set(curr.index) | set(old.index)):
        a = float(old[name]) if name in old else None
        b = float(curr[name]) if name in curr else None
        diff, pct = comparable(a, b)
        rubricas.append({'Nome': name, 'N-1': a, 'N': b, 'Diferença': diff, 'Percentagem': pct})
    rubricas.sort(key=lambda x: abs(x['Diferença']) if x['Diferença'] is not None else -1, reverse=True)

    def acc(year):
        return _calc(history.get(f'{year}-{mon:02d}', {})).get(metric)

    return {
        'title': title,
        'prefix': prefix,
        'totals': totals,
        'month': (totals.get(prior), totals.get(period)),
        'acc': (acc(yr - 1), acc(yr)),
        'rubricas': rubricas,
        'available': bool(totals),
    }


REMUNERATION_GROUPS = {
    'Remunerações certas e permanentes',
    'Abonos variáveis ou eventuais',
    'Encargos sobre remunerações',
}


def _main_contributors(history, mapping, period, prefix, limit=10):
    """Grupos Pool 1 por dimensão do acumulado do ano N (N-1 só comparativo).

    Os saldos são os do balancete de fecho do mesmo mês, sem somar
    os meses entre janeiro e a referência. Remunerações são consolidadas.
    """
    year, month = map(int, period.split('-'))
    prior = f'{year-1}-{month:02d}'
    sign = -1.0 if prefix == '7' else 1.0

    def grouped(key):
        detail = _detail_for_period_measure(history, key, mapping, 'acumulado')
        if detail.empty:
            return pd.Series(dtype=float)
        sub = detail[
            detail['Conta'].astype(str).str.startswith(prefix)
            & detail['Pool 1'].astype(str).str.strip().ne('')
        ].copy()
        if sub.empty:
            return pd.Series(dtype=float)
        sub['Valor (€)'] = pd.to_numeric(sub['Valor (€)'], errors='coerce') * sign
        if prefix == '6':
            sub = sub.loc[~sub['Pool 1'].isin(REMUNERATION_GROUPS)]
        return sub.groupby('Pool 1')['Valor (€)'].agg(lambda v:v.sum() if v.notna().all() else float('nan'))

    current = grouped(period)
    previous = grouped(prior)
    if current.empty:
        return []
    rows = []
    for name in current.index:
        now = float(current[name])
        old = float(previous[name]) if name in previous.index else None
        difference, pct = comparable(old, now)
        rows.append({'Nome': name, 'N': now, 'N-1': old,
                     'Diferença': difference, 'Percentagem': pct})
    rows.sort(key=lambda r: r['N'], reverse=True)
    return rows[:limit]


def _remuneration_analysis(history, mapping, period):
    """Classes 6 classificadas em Pool 1 remuneratória; detalhe por Pool 2.
    Utiliza movimento acumulado à data de fecho, sem duplicação de contas pai.
    """
    year, month = map(int, period.split('-'))
    years = [y for y in (year-2, year-1, year) if f'{y}-{month:02d}' in history]
    totals = {}
    for y in years:
        detail = _detail_for_period_measure(history, f'{y}-{month:02d}', mapping, 'acumulado')
        sub = detail[
            detail['Conta'].astype(str).str.startswith('6')
            & detail['Pool 1'].isin(REMUNERATION_GROUPS)
        ].copy()
        if not sub.empty:
            sub['Valor (€)'] = pd.to_numeric(sub['Valor (€)'], errors='coerce')
            totals[y] = sub
    if not totals:
        return {'total': None, 'pool1': [], 'pool2': [], 'years': years}
    def add_rows(keys, levels):
        all_keys = set()
        for sub in totals.values():
            all_keys.update(tuple(v) for v in sub[levels].drop_duplicates().itertuples(index=False, name=None))
        rows = []
        for key in all_keys:
            yearly = {}
            for y, sub in totals.items():
                mask = pd.Series(True, index=sub.index)
                for col, val in zip(levels, key):
                    mask &= sub[col].eq(val)
                yearly[y] = float(sub.loc[mask, 'Valor (€)'].sum()) if mask.any() and sub.loc[mask, 'Valor (€)'].notna().all() else None
            name = key[-1] if len(key) == 1 else f'{key[0]} · {key[1]}'
            current, old = yearly.get(year), yearly.get(year-1)
            diff, pct = comparable(old, current)
            rows.append({'Nome': name, 'Pool 1': key[0],
                         'Pool 2': key[1] if len(key)>1 else '',
                         'N': current, 'N-1': old,
                         'Diferença': diff, 'Percentagem': pct,
                         'Pontos': [{'Ano': y, 'Valor': yearly.get(y)} for y in years]})
        rows.sort(key=lambda x: x['N'] if x['N'] is not None else float('-inf'), reverse=True)
        return rows
    by1 = add_rows(None, ['Pool 1'])
    by2 = add_rows(None, ['Pool 1', 'Pool 2'])
    total = sum(r['N'] for r in by1) if by1 and all(r['N'] is not None for r in by1) else None
    return {'total': total, 'pool1': by1, 'pool2': by2, 'years': years}


def _render_remunerations(info):
    remun = info['remuneracoes']
    st.subheader('Despesas com pessoal · análise individualizada')
    if remun['total'] is None:
        st.info('Sem dados de remunerações classificados no mês de referência.')
        return
    st.metric('Total acumulado de remunerações e encargos', fmt(remun['total'], True))
    st.markdown('#### Grupos de remunerações')
    _plot_pair(remun['pool1'], info['period'], info['prior'],
               'Despesas com pessoal · grupos remuneratórios')
    for group in remun['pool1']:
        details = [r for r in remun['pool2'] if r['Pool 1'] == group['Pool 1']]
        if not details:
            continue
        with st.container(border=True):
            st.markdown(f"**{group['Pool 1']} — detalhe remuneratório**")
            _plot_pair([{**r, 'Nome':r['Pool 2'] or 'Sem classificação detalhada'}
                        for r in details], info['period'], info['prior'],
                       f"{group['Pool 1']} · detalhe remuneratório")


def _detail_for_period_measure(history, period, mapping, measure="mensal"):
    rec = history.get(period)
    if not rec or not rec.get("contas_balancete"):
        return pd.DataFrame(columns=["Conta", "Designação", "Pool 1", "Pool 2", "Valor (€)", "Estado"])
    if measure == "acumulado":
        return pool_details(rec, mapping, "acumulado").copy()
    return _detail_for_period(history, period, mapping)


def _segment_small_multiples(history, mapping, period, prefix, top_n=12):
    yr, mon = map(int, period.split('-'))
    target_years = [y for y in (yr-2, yr-1, yr) if f"{y}-{mon:02d}" in history]
    grouped_by_year = {}
    sign = -1.0 if prefix == "7" else 1.0
    for y in target_years:
        key = f"{y}-{mon:02d}"
        detail = _detail_for_period_measure(history, key, mapping, measure="acumulado")
        if detail.empty:
            continue
        subset = detail[
            detail['Conta'].astype(str).str.startswith(prefix)
            & detail['Pool 1'].astype(str).ne('')
        ].copy()
        if subset.empty:
            continue
        subset['Valor (€)'] = subset['Valor (€)'].astype(float) * sign
        grouped_by_year[y] = subset.groupby('Pool 1')['Valor (€)'].agg(lambda v:v.sum() if v.notna().all() else float('nan'))
    if not grouped_by_year:
        return []
    rubrics = set()
    for ser in grouped_by_year.values():
        rubrics.update(ser.index.tolist())
    current_ser = grouped_by_year.get(yr, pd.Series(dtype=float))
    ordered = sorted(rubrics, key=lambda r: abs(float(current_ser.get(r, 0.0))) if pd.notna(current_ser.get(r, 0.0)) else 0.0, reverse=True)
    cards = []
    for rub in ordered[:top_n]:
        points = []
        for y in target_years:
            ser = grouped_by_year.get(y)
            val = None if ser is None or rub not in ser.index else float(ser[rub])
            points.append({'Ano': y, 'Valor': val})
        if any(p['Valor'] is not None for p in points):
            cards.append({'Nome': rub, 'Pontos': points})
    return cards


def _mini_y_range(points):
    values = [float(p['Valor']) for p in points if p['Valor'] is not None]
    if not values:
        return None
    low, high = min(values), max(values)
    span = high-low if high>low else max(abs(high)*.15, 1)
    # Reserva adicional para rótulos acima do último ponto.
    return [low-span*.22, high+span*.60]


def _small_multiple_chart(card):
    pts = [p for p in card['Pontos'] if p['Valor'] is not None]
    if not pts:
        return
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[str(p['Ano']) for p in pts],
        y=[p['Valor']/1e6 for p in pts],
        mode='lines+markers+text',
        line=dict(color=CURRENT_COLOR, width=2),
        marker=dict(size=9, color=CURRENT_COLOR),
        text=[fmt(p['Valor'], True).replace(' M€','').replace(' €','') for p in pts],
        textposition='top center',
        textfont=dict(size=10, color='#315776'),
        cliponaxis=False,
        customdata=[[fmt(p['Valor'])] for p in pts],
        hovertemplate='%{x}<br>%{customdata[0]}<extra>'+card['Nome']+'</extra>',
        showlegend=False,
    ))
    fig.update_layout(
        title={'text': card['Nome'].upper(), 'x':0.5, 'y':0.96, 'yanchor':'top', 'xanchor':'center', 'font':{'size':10}},
        height=240,
        margin=dict(l=28, r=28, t=66, b=30),
        paper_bgcolor='#F7FBFF',
        plot_bgcolor='#F7FBFF',
        xaxis=dict(title=None, type='category', categoryorder='array', categoryarray=[str(v['Ano']) for v in pts], tickmode='array', tickvals=[str(v['Ano']) for v in pts], ticktext=[str(v['Ano']) for v in pts], showgrid=True, gridcolor='#E6EEF5', tickfont={'size':10}),
        yaxis=dict(title=None, showgrid=True, gridcolor='#E6EEF5', zeroline=False, tickfont={'size':10},
                   range=[v/1e6 for v in _mini_y_range(pts)], tickformat='.2f', fixedrange=True),
        hovermode='closest',
    )
    st.plotly_chart(fig, width='stretch', config={'displayModeBar': False})


def _render_small_multiples(title, cards, cols_per_row=4):
    st.markdown(f'#### {title}')
    if not cards:
        st.info('Sem dados suficientes para apresentar este destaque por rubrica.')
        return
    for start in range(0, len(cards), cols_per_row):
        cols = st.columns(cols_per_row)
        for col, card in zip(cols, cards[start:start+cols_per_row]):
            with col:
                _small_multiple_chart(card)


def collect(data, period, progress=None, root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    current = data[period]
    yr, mon = map(int, period.split('-'))
    prior = f'{yr-1}-{mon:02d}'
    previous = data.get(prior) or _prior_snapshot_from_current(current)
    cards = _calc(current)

    dr_labels = [
        ('Prestações de serviços', 'prestacoes_servicos'),
        ('Transferências', 'transferencias'),
        ('Consumos', 'consumos'),
        ('FSE', 'fse'),
        ('Gastos com pessoal', 'pessoal'),
        ('Outros gastos', 'outros_gastos'),
        ('Depreciações', 'depreciacoes'),
        ('Resultado líquido', 'resultado'),
    ]
    balan_labels = [
        ('Ativo', 'ativo'),
        ('Passivo', 'passivo'),
        ('Património líquido', 'patrimonio'),
        ('Caixa', 'caixa'),
        ('Fornecedores', 'fornecedores'),
        ('Fornecedores de imobilizado', 'fornecedores_investimento'),
    ]

    mapping = read_map()
    jobs = [
        ('tesouraria_investimento', 'DFC e investimento patrimonial', lambda: __import__('tesouraria_investimento').collect(data,period,root)),
        ('gastos', 'Gastos e evolução mensal', lambda: _segment_info(data, mapping, period, '6', 'Gastos Totais')),
        ('rendimentos', 'Rendimentos e evolução mensal', lambda: _segment_info(data, mapping, period, '7', 'Rendimentos Totais')),
        ('gastos_contribuintes', 'Principais rubricas de gastos', lambda: _main_contributors(data, mapping, period, '6', 10)),
        ('rendimentos_contribuintes', 'Contrato Programa e restantes rendimentos', lambda: _main_contributors(data, mapping, period, '7', 9999)),
        ('remuneracoes', 'Remunerações', lambda: _remuneration_analysis(data, mapping, period)),
        ('gastos_cards', 'Gráficos de gastos dos três anos', lambda: _segment_small_multiples(data, mapping, period, '6', top_n=12)),
        ('rendimentos_cards', 'Gráficos de rendimentos dos três anos', lambda: _segment_small_multiples(data, mapping, period, '7', top_n=30)),
    ]
    result = {
        'period': period, 'year': yr, 'month': mon, 'prior': prior, 'cards': cards,
        'dr': _comparison_rows(current.get('dr', {}), previous.get('dr', {}) if previous else None, dr_labels),
        'balan': _comparison_rows(current.get('balanco', {}), previous.get('balanco', {}) if previous else None, balan_labels),
        'prior_available': previous is not None,
    }
    for index, (key, label, compute) in enumerate(jobs):
        if progress:
            progress(index / len(jobs), label)
        result[key] = compute()
    if progress:
        progress(1.0, 'Indicadores preparados')
    from analise_executiva import enrich
    monthly = {}
    for label, key in [('current',period),('prior',prior)]:
        y,m = map(int,key.split('-'))
        now = data.get(key)
        before = data.get(f'{y}-{m-1:02d}') if m > 1 else None
        if now and (m == 1 or before):
            a = _calc(before) if before else {n:0 for n in cards}
            b = _calc(now)
            monthly[label] = {n:b[n]-a[n] if b[n] is not None and a[n] is not None else None for n in ('Rendimentos','Gastos','Resultado líquido')}
            pa = before.get('dr',{}).get('pessoal') if before else 0
            pb = now.get('dr',{}).get('pessoal')
            monthly[label]['Pessoal'] = pb-pa if pb is not None and pa is not None else None
    return enrich(result,current,previous,_calc(previous) if previous else {},monthly,root)


def _plot_pair(rows, period, prior, title):
    valid = [r for r in rows if r['N'] is not None or r['N-1'] is not None]
    if not valid:
        return
    fig = go.Figure()
    for field, name, color in [('N-1', prior, PRIOR_COLOR), ('N', period, CURRENT_COLOR)]:
        fig.add_bar(
            y=[r['Nome'] for r in valid],
            x=[r[field]/1e6 if r[field] is not None else None for r in valid],
            name=name,
            orientation='h',
            marker_color=color,
            customdata=[[fmt(r[field])] for r in valid],
            hovertemplate='%{y}<br>%{customdata[0]}<extra>' + name + '</extra>',
        )
    fig.update_layout(
        title={'text': title, 'x': 0, 'xanchor': 'left'},
        barmode='group',
        height=max(380, 60 * len(valid)),
        margin=dict(l=170, r=30, t=95, b=40),
        legend=dict(orientation='h', yanchor='bottom', y=1.04, xanchor='left', x=0),
        xaxis_title='M€', xaxis_tickformat='.2f',
        yaxis={'autorange': 'reversed', 'title': None},
        hovermode='closest',
    )
    st.plotly_chart(fig, width='stretch', config={'displayModeBar': False})



def _monthly_figure(segment, info, title):
    yr, m = info['year'], info['month']
    fig = go.Figure()
    for year, color in [(yr - 1, PRIOR_COLOR), (yr, CURRENT_COLOR)]:
        vals = [segment['totals'].get(f'{year}-{j:02d}') for j in range(1,m+1)]
        fig.add_bar(
            x=[MONTHS[j].capitalize()[:3] for j in range(1,m+1)],
            y=[v/1e6 if v is not None else None for v in vals],
            name=str(year), marker_color=color,
            text=[fmt(v).replace(' M€','') if v is not None else '' for v in vals],
            textposition='outside',cliponaxis=False,
            customdata=[[fmt(v)] for v in vals],
            hovertemplate='%{x} '+str(year)+'<br>%{customdata[0]}<extra></extra>')
    observed=[v/1e6 for year in (yr-1,yr) for j in range(1,m+1)
              if (v:=segment['totals'].get(f'{year}-{j:02d}')) is not None]
    low=min([0]+observed);high=max([0]+observed);span=high-low or 1
    fig.update_layout(title={'text':title,'x':0},barmode='group',bargap=.23,
        height=410,margin=dict(l=55,r=25,t=100,b=45),
        yaxis=dict(title='M€',tickformat='.2f',range=[low-span*.04,high+span*.16]),
        xaxis=dict(title=None,type='category'),
        legend=dict(orientation='h',yanchor='bottom',y=1.04,x=0),
        hovermode='x unified',separators=',.')
    return fig


def _series_chart(segment, info, title):
    name='Rendimentos' if segment['prefix']=='7' else 'Gastos'
    fig=_monthly_figure(segment,info,f'{name} do mês · {info["year"]-1} vs. {info["year"]}')
    st.plotly_chart(fig,width='stretch',config={'displayModeBar':False})
    st.caption('Cada par de barras compara o mesmo mês nos dois anos. Valores do mês = DR acumulada do fecho menos DR acumulada do mês anterior; janeiro corresponde ao seu acumulado. Valores em falta não são substituídos por zero.')


def _pmp_signature(root: Path):
    extrato_root = root / 'dados_pmp_extratos'
    files = []
    if extrato_root.exists():
        for p in sorted(extrato_root.glob('extrato_*.csv.gz')):
            stat = p.stat()
            files.append((p.name, stat.st_mtime_ns, stat.st_size))
    return tuple(files)


@st.cache_data(show_spinner=False)
def _compute_pmp_cards(data_snapshot, signature):
    del signature
    try:
        from pmp_extratos import pmp_cards
        df = pmp_cards(data_snapshot)
        return df.to_dict('records') if isinstance(df, pd.DataFrame) and not df.empty else []
    except Exception:
        return []


def _quarter_from_period(period):
    y, m = map(int, period.split('-'))
    return f'{y}-T{m//3}' if m >= 3 else f'{y-1}-T4'


def _pmp_last4(data, period, root: Path):
    target_q = _quarter_from_period(period)
    rows = _compute_pmp_cards(data, _pmp_signature(root))
    if rows:
        df = pd.DataFrame(rows)
        if 'Período' in df and 'PMP (dias)' in df:
            df = df[df['Período'] <= target_q].copy()
            df['PMP (dias)'] = pd.to_numeric(df['PMP (dias)'], errors='coerce')
            df = df[df['PMP (dias)'].notna()].sort_values('Período').tail(4)
            if not df.empty:
                return [(r['Período'], float(r['PMP (dias)']), r.get('Estado') or 'Calculado') for _, r in df.iterrows()]
    # fallback para valores persistidos no histórico importado
    rows = []
    for key, rec in sorted(data.items()):
        if key > period:
            continue
        for name in ('pmp_oficial', 'pmp_regulamentar', 'pmp'):
            v = rec.get(name)
            if isinstance(v, (int, float)):
                rows.append((key, float(v), name))
                break
    return rows[-4:]


def _funding_figure(row,info):
    values=[row['N-1'],row['N']]
    fig=go.Figure(go.Bar(x=[str(info['year']-1),str(info['year'])],
        y=[v/1e6 if v is not None else None for v in values],
        marker_color=[PRIOR_COLOR,CURRENT_COLOR],
        text=[fmt(v) if v is not None else 'Indisponível' for v in values],
        textposition='outside',cliponaxis=False,
        customdata=[[fmt(v)] for v in values],hovertemplate='%{x}<br>%{customdata[0]}<extra></extra>'))
    observed=[v/1e6 for v in values if v is not None]
    low=min([0]+observed);high=max([0]+observed);span=high-low or 1
    fig.update_layout(height=250,margin=dict(l=42,r=20,t=25,b=30),showlegend=False,
        paper_bgcolor='#F7FBFF',plot_bgcolor='#F7FBFF',
        yaxis=dict(title='M€',tickformat='.2f',range=[low-span*.25,high+span*.25]),
        xaxis=dict(type='category'),separators=',.')
    return fig


def _render_funding(info):
    block=info.get('tesouraria_investimento')
    if not block:return
    for key,title,note in [('dfc','DFC · caixa e pagamentos','nota_dfc'),('ativos','Investimento · compras e obras em curso','nota_ativos')]:
        st.subheader(title)
        st.caption(block[note])
        rows=block[key]
        for start in range(0,len(rows),3):
            for col,row in zip(st.columns(3),rows[start:start+3]):
                with col:
                    st.markdown('**'+row['Nome']+'**')
                    st.caption(row['Âmbito'])
                    if row['N'] is None and row['N-1'] is None:
                        st.info('Mapa ou rubrica indisponível para a comparação.')
                    else:
                        st.plotly_chart(_funding_figure(row,info),width='stretch',config={'displayModeBar':False},key=f"funding_{info['period']}_{key}_{row['Nome']}")
                        if row['Diferença'] is not None:
                            pct=(f" ({row['Percentagem']:+.1f}%)".replace('.',',') if row['Percentagem'] is not None else ' (base zero)')
                            st.caption('Variação: '+fmt(row['Diferença'])+pct)


def _render_revenue_split(info):
    groups = info.get('rendimentos_contribuintes', [])
    cp = [r for r in groups if r['Nome'] == CONTRACT_GROUP]
    extra = [r for r in groups if r['Nome'] != CONTRACT_GROUP]
    st.markdown('#### Contrato Programa')
    if cp:
        old, now = cp[0]['N-1'], cp[0]['N']
        _, pct = comparable(old, now)
        st.metric('Rendimento acumulado', fmt(now, True),
                  delta=f'{pct:+.1f}%' if pct is not None else None, delta_color='off')
        _plot_pair(cp, info['period'], info['prior'], 'Contrato Programa · comparação homóloga')
    else:
        st.info('Contrato Programa não classificado no histórico.')
    st.markdown('#### Extra Contrato Programa')
    if extra:
        _plot_pair(extra, info['period'], info['prior'],
                   'Rendimentos extra Contrato Programa · principais grupos')
    else:
        st.info('Não existem rendimentos extra Contrato Programa classificados.')


def _render_segment(segment, info):
    yr = info['year']
    p_old, p_now = segment['month']
    a_old, a_now = segment['acc']
    st.markdown(f'#### {segment["title"]}')
    cols = st.columns(2)
    for col, title, old, now in [
        (cols[0], 'Mês', p_old, p_now),
        (cols[1], 'Acumulado', a_old, a_now),
    ]:
        diff, pct = comparable(old, now)
        delta = f'{pct:+.1f}% · {fmt(diff, True)}' if pct is not None else None
        col.metric(title, fmt(now, True), delta=delta, delta_color='off')
        col.caption(f'{fmt(old, True)} em {yr-1}' if old is not None else 'Homólogo indisponível')
    if segment['available']:
        _series_chart(segment, info, f'{segment["title"]} · evolução mensal')
    else:
        st.info(f'{segment["title"]} indisponíveis: são necessários balancetes de meses consecutivos e período homólogo.')
    key = 'gastos_contribuintes' if segment['prefix'] == '6' else 'rendimentos_contribuintes'
    top = info.get(key, [])
    if segment['prefix'] == '7':
        return  # Contrato Programa e extra-contrato possuem gráficos próprios
    if top:
        _plot_pair(top, info['period'], info['prior'],
                   f'{segment["title"]} · principais grupos pelo valor acumulado')




# Os estados P1/P2/NC são apenas os estados relevantes da dívida,
# e as NC conservam o sinal que consta do XML (habitualmente negativo).
def _debt_summary(df, period):
    if df.empty:
        return None
    needed = {'ValorDoc', 'TipoDocCentral', 'ClassificadorEconomico', 'TipoEntidadeCentral', 'NifEntidade', 'NomeEntidade'}
    if not needed.issubset(df.columns):
        return None
    x = df.loc[df['TipoDocCentral'].astype(str).str.strip().str.upper().isin(('P1', 'P2', 'NC'))].copy()
    if x.empty:
        return None
    x['ValorDoc'] = pd.to_numeric(x['ValorDoc'], errors='coerce')
    if x['ValorDoc'].isna().any():
        raise ValueError('Dívida documental: existem valores em falta ou inválidos; o total não pode ser calculado.')
    x['ClassificadorEconomico'] = x['ClassificadorEconomico'].fillna('').astype(str).str.strip()
    x['TipoEntidadeCentral'] = x['TipoEntidadeCentral'].fillna('').astype(str).str.strip()
    x['NifEntidade'] = x['NifEntidade'].fillna('').astype(str).str.strip()
    x['NomeEntidade'] = x['NomeEntidade'].fillna('').astype(str).str.strip()
    x['TipoDocCentral'] = x['TipoDocCentral'].astype(str).str.upper().str.strip()
    x['Destino'] = x['ClassificadorEconomico'].apply(lambda v: 'Capital' if v.startswith('07') else 'Correntes' if v else 'Sem classificação')
    from sisee_divida import group, is_cga, social
    def sector(row):
        if is_cga(row) or social(row): return 'Estado'
        try: return group(row)
        except ValueError: return 'Não classificado'
    x['Setor'] = x.apply(sector,axis=1)
    def totals(df, column, labels):
        res = df.groupby(column, dropna=False)['ValorDoc'].sum().to_dict()
        return [{'Nome': k, 'Valor': round(float(res.get(k, 0.0)),2)} for k in labels]
    by_doc = totals(x, 'TipoDocCentral', ['P1','P2','NC'])
    total = float(x['ValorDoc'].sum())
    by_type = totals(x, 'Destino', ['Correntes','Capital','Sem classificação'])
    by_sector = totals(x, 'Setor', ['SNS','Estado','Externos','Não classificado'])
    names = x.groupby('NifEntidade')['NomeEntidade'].agg(lambda v: next((n for n in v if n), '')).to_dict()
    top = (x.groupby('NifEntidade')['ValorDoc'].sum().sort_values(ascending=False).head(10))
    top_suppliers = [{'Nif': nif, 'Nome': names.get(nif) or 'Fornecedor sem identificação', 'Valor': round(float(value),2)} for nif, value in top.items() if value > 0]
    rankings={}
    for sector_name in ('SNS','Estado','Externos'):
        sub=x[x['Setor']==sector_name]
        denominator=float(sub['ValorDoc'].sum())
        ranked=sub.groupby('NifEntidade')['ValorDoc'].sum().sort_values(ascending=False)
        rankings[sector_name]=[{'Nif':nif,'Nome':names.get(nif) or 'Credor sem identificação',
            'Valor':round(float(v),2),'Percentagem':float(v)/denominator*100 if denominator>0 else None}
            for nif,v in ranked[ranked>0].head(5).items()]
    factoring=[]
    if 'Factoring' in x:
        fac=x['Factoring'].fillna('').astype(str).str.strip().str.upper()
        yes=fac.isin(('1','S','SIM','TRUE','Y'))
        no=fac.isin(('0','N','NAO','NÃO','FALSE',''))
        factoring=[{'Nome':'Factoring identificado','Valor':float(x.loc[yes,'ValorDoc'].sum())},
                   {'Nome':'Sem factoring indicado','Valor':float(x.loc[no,'ValorDoc'].sum())},
                   {'Nome':'Factoring por conferir','Valor':float(x.loc[~yes & ~no,'ValorDoc'].sum())}]
    return {'rankings':rankings,'factoring':factoring,'period':period,'total':round(total,2),'docs':by_doc,'type':by_type,'sector':by_sector,'suppliers':top_suppliers, 'unclassified': int((x['Destino']=='Sem classificação').sum()), 'unknown_sector':int((x['Setor']=='Não classificado').sum())}


def _debt_signature(root, period):
    path = root / 'dados_xml' / period / 'Dividas.json.gz'
    if path.is_file():
        stat = path.stat()
        return (str(path),stat.st_mtime_ns, stat.st_size)
    return None


@st.cache_data(show_spinner=False, max_entries=12)
def _cached_debt(period, signature):
    if not signature:
        return None
    from divida_xml import load_snapshot
    return _debt_summary(load_snapshot(Path(signature[0]).parent.parent.parent, period, 'Dividas'), period)


def _read_debt(root, period):
    return _cached_debt(period, _debt_signature(root,period))


def _debt_bar(rows, title):
    names=[r['Nome'] for r in rows]
    values=[r['Valor'] for r in rows]
    fig=go.Figure(go.Bar(x=names, y=[v/1e6 for v in values], marker_color=['#206B9F','#F4B183','#65A8A0','#C2B4DE'][:len(rows)],
        customdata=[[fmt(v)] for v in values], hovertemplate='%{x}<br>%{customdata[0]}<extra></extra>'))
    fig.update_layout(title={'text': title, 'x': 0.02},height=315,margin=dict(l=40,r=15,t=65,b=38),yaxis_title='M€',yaxis_tickformat='.2f',yaxis_ticksuffix=' M€')
    st.plotly_chart(fig,width='stretch',config={'displayModeBar':False})


def _render_debt(debt):
    st.subheader('Dívida — estrutura e concentração')
    if debt is None:
        st.info('Para apresentar a estrutura da dívida é necessário importar o ficheiro Dividas.xml do mês de referência. Não são utilizados valores de meses diferentes.')
        return
    a,b,c=st.columns(3)
    a.metric('Dívida total (P1 + P2 + NC)',fmt(debt['total'],True))
    b.metric('Dívida corrente',fmt(next(v['Valor'] for v in debt['type'] if v['Nome']=='Correntes'),True))
    c.metric('Dívida de capital',fmt(next(v['Valor'] for v in debt['type'] if v['Nome']=='Capital'),True))
    col1,col2=st.columns(2)
    with col1: _debt_bar(debt['type'][:2],'Correntes vs. Capital')
    with col2: _debt_bar(debt['sector'][:3],'SNS, Estado e Externos')
    for sector, rows in debt.get('rankings',{}).items():
        st.markdown('#### Maiores credores ' + sector)
        if rows:
            table=pd.DataFrame([{'Credor':r['Nome'],'Montante (M€)':fmt(r['Valor']),
                '% do setor':f"{r['Percentagem']:.1f}%" if r['Percentagem'] is not None else '—'} for r in rows])
            st.dataframe(table,hide_index=True,width='stretch')
        else: st.info('Sem saldos credores positivos neste setor.')
    if debt.get('factoring'):
        st.caption('Factoring é um subconjunto da dívida documental, já incluído no total.')
        st.dataframe(pd.DataFrame([{'Situação':r['Nome'],'Montante (M€)':fmt(r['Valor'])} for r in debt['factoring']]),hide_index=True)
    if debt['unclassified'] or debt['unknown_sector']:
        st.caption('Existem documentos sem classificação económica ou sem código de setor reconhecido; os respetivos valores são mantidos nos totais.')
    st.caption('Dívida dos documentos P1 e P2 líquida de NC, com o sinal contabilístico do XML. A desagregação corresponde ao stock do mês de referência.')

def _prepared_signatures(data, period, root):
    import resultados_preparados as prepared
    core_files = ['visao_executiva.py', 'comparador.py', 'pools.py',
                  'mapa_pools.tsv', 'resultados_preparados.py', 'analise_executiva.py', 'tesouraria_investimento.py']
    core = prepared.digest([prepared.core_history(data, period),
                            prepared.file_signatures(root, [f'dados_s3cp_xml/{period}/BA.json.gz'] + __import__('tesouraria_investimento').source_names(period)),
                            prepared.file_signatures(root, core_files)])
    debt = prepared.digest([_debt_signature(root, period),
                            prepared.file_signatures(root, ['visao_executiva.py', 'divida_xml.py', 'sisee_divida.py', 'resultados_preparados.py', 'analise_executiva.py', 'tesouraria_investimento.py'])])
    pmp_files = core_files + [p.name for p in root.glob('pmp*.py')]
    pmp_files += ['importador_s3cp_xml.py', 'periodos_snc_ap.py']
    pmp_files += [str(p.relative_to(root)) for p in (root / 'dados_s3cp_xml').glob('*/*.json.gz')]
    pmp = prepared.digest([data, _pmp_signature(root), prepared.file_signatures(root, pmp_files)])
    return {'executivo': core, 'divida': debt, 'pmp': pmp}


def _prepare_period(data, period, root, signatures, force=False, progress=None):
    import resultados_preparados as prepared
    def report(fraction, label):
        if progress:
            progress(fraction, label)
    for block, start, end in [('executivo', 0.0, .80), ('divida', .80, .90), ('pmp', .90, 1.0)]:
        if not force and prepared.read(root, period, block, signatures[block]) is not None:
            report(end, block + ' já atualizado')
            continue
        report(start, 'A calcular ' + block)
        if block == 'executivo':
            result = collect(data, period, lambda f, label: report(start + (end-start)*f, label), root=root)
        elif block == 'divida':
            result = _read_debt(root, period)
        else:
            result = _pmp_last4(data, period, root)
        # Não publicar resultados calculados sobre ficheiros que mudaram a meio.
        if _prepared_signatures(data, period, root)[block] != signatures[block]:
            raise RuntimeError('Os dados mudaram durante o cálculo. Repete o recálculo.')
        prepared.write(root, period, block, signatures[block], result)
        report(end, block + ' guardado')


def render(data, period, root: Path):
    import resultados_preparados as prepared
    from datetime import datetime
    root = Path(root)
    from acompanhamento_acss import render_summary as render_acss_summary
    render_acss_summary(root, data, period)
    signatures = _prepared_signatures(data, period, root)
    saved = {b: prepared.read(root, period, b, sig) for b, sig in signatures.items()}
    st.caption('Visão Executiva · atualização 2.3 · DFC, investimento e pessoal')
    st.markdown('#### Preparação de resultados')
    scope = st.radio('Períodos a preparar', ['Período selecionado', 'Todos os períodos'],
                     horizontal=True, key='executivo_preparar_scope')
    force = st.checkbox('Forçar recálculo dos resultados já atualizados', key='executivo_preparar_force')
    st.caption('Indicadores, gráficos, dívida e PMP ficam guardados em JSON. '
               'O botão atualiza os blocos em falta ou alterados; as restantes análises mantêm o funcionamento atual.')
    if st.button('Recalcular e guardar resultados', type='primary', key='executivo_preparar'):
        for extension in ('xlsx', 'pdf'):
            st.session_state.pop('executivo_export_' + extension, None)
        periods = sorted(data) if scope == 'Todos os períodos' else [period]
        bar = st.progress(0.0, text='A iniciar…')
        import time
        started = time.perf_counter()
        try:
            # Evitar que um recálculo forçado reutilize cálculos intermédios antigos.
            _compute_pmp_cards.clear()
            _cached_debt.clear()
            for index, key in enumerate(periods):
                sig = _prepared_signatures(data, key, root)
                def update(fraction, label, index=index, key=key):
                    bar.progress((index + fraction) / len(periods),
                                 text=f'{key} · {label} · {index+1}/{len(periods)}')
                _prepare_period(data, key, root, sig, force, update)
            bar.progress(1.0, text='Preparação concluída')
            st.success(f'Resultados guardados em {time.perf_counter()-started:.1f} segundos.')
        except Exception as exc:
            st.error(f'Não foi possível concluir a preparação: {exc}')
        signatures = _prepared_signatures(data, period, root)
        saved = {b: prepared.read(root, period, b, sig) for b, sig in signatures.items()}
    missing = [b for b, obj in saved.items() if obj is None]
    if missing:
        st.info('Resultados por preparar ou desatualizados: ' + ', '.join(missing) +
                '. Usa o botão acima para atualizar. Os cálculos não são executados ao abrir a página.')
        return
    latest = max(datetime.fromisoformat(obj['prepared_at']) for obj in saved.values())
    updated = latest.astimezone().strftime('%d/%m/%Y %H:%M')
    st.caption(f'Resultados atualizados · última preparação: {updated}')
    info = saved['executivo']['result']
    info['debt'] = saved['divida']['result']
    pmp = saved['pmp']['result']
    from analise_executiva import narratives, reconciliation, read_comment, save_comment
    info['interpretacao'] = narratives(info, pmp)
    yr = info['year']
    mon = info['month']
    date = f'{MONTHS[mon].capitalize()} {yr}'
    logo = root / 'logotipo ULSLA.png'

    st.markdown(
        '''<style>
        .ulsla-premium{background:linear-gradient(110deg,#102844,#245B88);border-radius:18px;padding:24px 30px;color:white;margin-bottom:18px}
        .ulsla-premium small{letter-spacing:2px;color:#D0E0F0}
        .ulsla-premium h1{color:white;font-size:2.5rem;margin:8px 0}
        .ulsla-premium p{color:#D6E4F2;margin:0}
        div[data-testid="stMetric"]{background:#fff;border:1px solid #E4EAF1;border-radius:14px;padding:10px 14px;min-height:116px}
        </style>''',
        unsafe_allow_html=True,
    )
    if logo.exists():
        st.image(str(logo), width=245)
    st.markdown(
        f'<div class="ulsla-premium"><small>SUMÁRIO EXECUTIVO FINANCEIRO · PERÍODO DE REFERÊNCIA</small><h1>{escape(date)}</h1><p>Dados acumulados a {mon:02d}/{yr} · ULS Litoral Alentejano, E.P.E.</p></div>',
        unsafe_allow_html=True,
    )

    names = list(info['cards'])
    for start in (0, 4):
        cols = st.columns(4)
        for col, name in zip(cols, names[start:start + 4]):
            col.metric(name, fmt(info['cards'][name], True))

    st.subheader('Prazo médio de pagamento')
    if pmp:
        cols = st.columns(len(pmp))
        prev = None
        for col, (p, v, origin) in zip(cols, pmp):
            delta = None if prev is None else f'{(v - prev):+.1f} dias'
            col.metric(p, f'{v:.1f} dias', delta=delta, delta_color='inverse')
            prev = v
    else:
        st.info('PMP indisponível. Para apresentar os últimos 4 trimestres é necessário ter os extratos 31/43/45 importados e os BA XML trimestrais disponíveis.')

    _render_funding(info)

    st.subheader('Demonstração de Resultados · período homólogo')
    if info['prior_available']:
        _plot_pair(info['dr'], period, info['prior'], 'DR acumulada · comparação homóloga')
    else:
        st.info('Não existe fecho homólogo da DR disponível.')

    st.subheader('Evolução do balanço')
    if info['prior_available']:
        _plot_pair(info['balan'], period, info['prior'], 'Saldos do balanço · datas homólogas')
    else:
        st.info('Não existe balanço homólogo disponível.')

    st.subheader('Evolução de gastos e rendimentos')
    st.caption('Principais contributos para os gastos: excluem os grupos remuneratórios, apresentados em separado.')
    _render_small_multiples('Gastos — últimos três anos homólogos', info['gastos_cards'], cols_per_row=4)
    _render_small_multiples('Contrato Programa — últimos três anos homólogos', [r for r in info['rendimentos_cards'] if r['Nome'] == CONTRACT_GROUP], cols_per_row=3)
    _render_small_multiples('Rendimentos extra Contrato Programa — últimos três anos homólogos', [r for r in info['rendimentos_cards'] if r['Nome'] != CONTRACT_GROUP], cols_per_row=3)
    _render_segment(info['gastos'], info)
    _render_remunerations(info)
    _render_segment(info['rendimentos'], info)
    _render_revenue_split(info)

    _render_debt(info['debt'])

    st.subheader('Resumo das variações')
    for section in info['interpretacao']:
        st.markdown('**'+section['titulo']+'**')
        st.write(section['texto'])
    with st.expander('Detalhe técnico · perímetros da dívida',expanded=False):
        st.dataframe(pd.DataFrame([{'Rubrica':k,'Valor (M€)':fmt(v)} for k,v in reconciliation(info).items()]),hide_index=True,width='stretch')
        st.caption(info['contabilistica']['conta_27892']['fonte'])
        st.caption('O total documental inclui descontos e encargos associados aos vencimentos, designadamente das contas 242, 245 e outras. A diferença entre estes totais resulta de perímetros distintos e não constitui, por si só, uma divergência contabilística. Este quadro não é incluído no PDF de gestão.')
    st.subheader('Comentário da gestão')
    try:
        persisted = read_comment(root,period)
    except (OSError,ValueError,KeyError) as exc:
        st.error(f'Não foi possível ler o comentário: {exc}')
        return
    comment=st.text_area('Comentário para este período',value=persisted,key='gestao_'+period,height=160)
    if st.button('Guardar comentário da gestão',key='guardar_gestao_'+period):
        try:
            save_comment(root,period,comment)
            persisted=comment
            st.success('Comentário guardado para '+period)
        except OSError as exc:
            st.error(f'Não foi possível guardar: {exc}')
    info['comentario_gestao']=persisted
    st.caption('O PDF e o Excel incluem o último comentário guardado. Os recálculos não alteram os comentários.')

    export_signature = prepared.digest([signatures, period, persisted, [saved[b]['checksum'] for b in saved], prepared.file_signatures(root, ['logotipo ULSLA.png'])])
    for label, extension, mime, builder in [
        ('Excel', 'xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', to_excel),
        ('PDF', 'pdf', 'application/pdf', to_pdf),
    ]:
        state_key = 'executivo_export_' + extension
        if st.button('Preparar Sumário ' + label, key='preparar_export_' + extension):
            with st.spinner('A preparar ' + label + '…'):
                try:
                    st.session_state[state_key] = (export_signature, builder(info, logo, pmp))
                except Exception as exc:
                    st.error(f'Não foi possível preparar {label}: {exc}')
        export = st.session_state.get(state_key)
        if export and export[0] == export_signature:
            st.download_button('Descarregar Sumário ' + label, export[1],
                               f'ULSLA_Sumario_{period}.{extension}', mime=mime,
                               key='descarregar_export_' + extension)



def to_excel(info, logo, pmp):
    wb = Workbook()
    ws = wb.active
    ws.title = 'Sumário Executivo'
    ws.sheet_view.showGridLines = False
    ws.merge_cells('A1:H1')
    ws['A1'] = 'ULSLA · SUMÁRIO EXECUTIVO FINANCEIRO'
    ws['A1'].font = Font(size=18, bold=True, color='FFFFFF')
    ws['A1'].fill = PatternFill('solid', fgColor=NAVY)
    ws.row_dimensions[1].height = 36
    ws.merge_cells('A2:H2')
    ws['A2'] = f"Período de referência: {MONTHS[info['month']].capitalize()} {info['year']}"
    ws['A2'].font = Font(size=14, bold=True, color=BLUE)
    ws.row_dimensions[2].height = 28
    if logo.exists():
        img = XLImage(str(logo))
        img.width = 180
        img.height = 100
        ws.add_image(img, 'F3')

    row = 4
    for title, value in info['cards'].items():
        ws.cell(row, 1, title)
        cell = ws.cell(row, 3, value)
        cell.number_format = '#,##0.00,, "M€"'
        row += 1
    ws.cell(row + 1, 1, 'PMP — últimos 4 trimestres').font = Font(bold=True, color=BLUE)
    r = row + 2
    for per, value, origin in pmp:
        ws.cell(r, 1, per)
        ws.cell(r, 2, value)
        # Não apresentar estado técnico do PMP no sumário
        ws.cell(r, 2).number_format = '0.0'
        r += 1
    ws.column_dimensions['A'].width = 34
    for c in 'BCDEFGH':
        ws.column_dimensions[c].width = 18

    def tab(name, rows):
        s = wb.create_sheet(name)
        s.sheet_view.showGridLines = False
        headers = ['Rubrica', info['prior'], info['period'], 'Variação (M€)', 'Variação (%)']
        s.append(headers)
        for j, h in enumerate(headers, 1):
            s.cell(1, j).fill = PatternFill('solid', fgColor=NAVY)
            s.cell(1, j).font = Font(color='FFFFFF', bold=True)
        for r in rows:
            s.append([r['Nome'], r['N-1'], r['N'], r['Diferença'], r['Percentagem'] / 100 if r['Percentagem'] is not None else None])
        s.column_dimensions['A'].width = 42
        for c in 'BCD':
            s.column_dimensions[c].width = 22
        s.column_dimensions['E'].width = 18
        for line in s.iter_rows(min_row=2):
            for cell in line[1:4]:
                cell.number_format = '#,##0.00,, "M€"'
            line[4].number_format = '0.0%'
        s.freeze_panes = 'B2'
        s.auto_filter.ref = s.dimensions
        return s

    sdr = tab('Resultados', info['dr'])
    sb = tab('Balanço', info['balan'])
    sg = tab('Gastos Rubricas', info['gastos']['rubricas'])
    sr = tab('Rendimentos Rubricas', info['rendimentos']['rubricas'])
    scg = tab('Maiores Gastos', info.get('gastos_contribuintes', []))
    scr = tab('Extra Contrato Programa', [r for r in info.get('rendimentos_contribuintes', []) if r['Nome'] != CONTRACT_GROUP])
    scp = tab('Contrato Programa', [r for r in info.get('rendimentos_contribuintes', []) if r['Nome'] == CONTRACT_GROUP])
    spr1 = tab('Pessoal Grupos', info['remuneracoes']['pool1'])
    spr2 = tab('Pessoal Detalhe', [{**r, 'Nome': r['Pool 1'] + ' · ' + (r['Pool 2'] or 'Sem classificação')} for r in info['remuneracoes']['pool2']])

    def monthly_sheet(name, segment):
        sheet = wb.create_sheet(name)
        sheet.append(['Mês', str(info['year'] - 1), str(info['year'])])
        for m in range(1, info['month'] + 1):
            sheet.append([
                MONTHS[m].capitalize(),
                segment['totals'].get(f"{info['year']-1}-{m:02d}"),
                segment['totals'].get(f"{info['year']}-{m:02d}"),
            ])
        for c in 'BC':
            sheet.column_dimensions[c].width = 22
        sheet.column_dimensions['A'].width = 20
        chart = BarChart()
        chart.type = 'col'
        chart.grouping = 'clustered'
        chart.overlap = 0
        chart.title = f'{name} · comparação mensal'
        chart.y_axis.title = 'M€'
        chart.y_axis.numFmt = '#,##0.00,,\" M€\"'
        chart.add_data(Reference(sheet, min_col=2, max_col=3, min_row=1, max_row=info['month'] + 1), titles_from_data=True)
        chart.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=info['month'] + 1))
        for series,color in zip(chart.series,(PRIOR_FILL,CURRENT_FILL)):
            series.graphicalProperties.line.solidFill=color
            series.graphicalProperties.solidFill=color
        for line in sheet.iter_rows(min_row=2,min_col=2,max_col=3):
            for cell in line:cell.number_format='#,##0.00,, \"M€\"'
        sheet.add_chart(chart, 'E3')
        return sheet

    monthly_sheet('Gastos Mensal', info['gastos'])
    monthly_sheet('Rendimentos Mensal', info['rendimentos'])

    for sheet in (sdr, sb, sg, sr, scg, scr, scp, spr1, spr2):
        if sheet.max_row > 1:
            c = BarChart()
            c.type = 'bar'
            c.grouping = 'clustered'
            c.title = sheet.title + ' · homólogo'
            c.add_data(Reference(sheet, min_col=2, max_col=3, min_row=1, max_row=sheet.max_row), titles_from_data=True)
            c.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=sheet.max_row))
            c.x_axis.title='M€'
            c.x_axis.numFmt='#,##0.00,,\" M€\"'
            for series,color in zip(c.series,(PRIOR_FILL,CURRENT_FILL)):
                series.graphicalProperties.solidFill=color
                series.graphicalProperties.line.solidFill=color
            sheet.add_chart(c, 'G3')

    if info.get('debt') is not None:
        d = info['debt']
        sd=wb.create_sheet('Dívida')
        sd.append(['DÍVIDA · '+d['period'],'Valor (M€)'])
        sd.append(['Total',d['total']])
        for key,heading in [('docs','Situação'),('type','Natureza'),('sector','Setor')]:
            sd.append([heading,None])
            for item in d[key]:sd.append([item['Nome'],item['Valor']])
        sd.append(['Maiores fornecedores',None])
        for item in d['suppliers'][:10]:sd.append([item['Nome'],item['Valor']])
        sd.column_dimensions['A'].width=55;sd.column_dimensions['B'].width=22
        for row in sd.iter_rows(min_row=2):row[1].number_format='#,##0.00,, "M€"'

    from analise_executiva import narratives,reconciliation
    analysis=wb.create_sheet('Resumo das variações')
    analysis.append(['Tema','Resumo das variações'])
    for section in narratives(info,pmp):analysis.append([section['titulo'],section['texto']])
    analysis.append(['Comentário da gestão',info.get('comentario_gestao','')])
    analysis.column_dimensions['A'].width=40
    analysis.column_dimensions['B'].width=125
    from openpyxl.styles import Alignment
    for row in analysis.iter_rows(min_row=2):
        row[1].alignment=Alignment(wrap_text=True,vertical='top')
        analysis.row_dimensions[row[0].row].height=max(42,15*((len(str(row[1].value or ''))//115)+1))
    recon=wb.create_sheet('Perímetros dívida - técnico')
    recon.append(['Rubrica','Valor (M€)'])
    for name,value in reconciliation(info).items():recon.append([name,value])
    recon.append(['Fonte 27892',info.get('contabilistica',{}).get('conta_27892',{}).get('fonte','')])
    recon.append(['Âmbito técnico','O total documental inclui descontos e encargos associados aos vencimentos (242, 245 e outras). Comparação entre perímetros distintos; não é uma divergência contabilística apurada.'])
    recon.column_dimensions['A'].width=60;recon.column_dimensions['B'].width=75
    for row in recon.iter_rows(min_row=2):
        if isinstance(row[1].value,(int,float)):row[1].number_format='#,##0.00,, "M€"'
    for sector,rows in (info.get('debt') or {}).get('rankings',{}).items():
        sheet=wb.create_sheet('Credores '+sector)
        sheet.append(['Credor','Montante (M€)','Percentagem do setor'])
        for r in rows:sheet.append([r['Nome'],r['Valor'],r['Percentagem']/100 if r['Percentagem'] is not None else None])
        sheet.column_dimensions['A'].width=65;sheet.column_dimensions['B'].width=24;sheet.column_dimensions['C'].width=25
        for row in sheet.iter_rows(min_row=2):
            row[1].number_format='#,##0.00,, "M€"';row[2].number_format='0.0%'
    personnel=wb.create_sheet('Reconciliação pessoal')
    personnel.append(['Rubrica','Montante (M€)'])
    for name,val in [('Pessoal na DR',info.get('pessoal_dr')),('Remunerações e encargos',info.get('remuneracoes',{}).get('total')),('Parcela restante',info.get('pessoal_restante'))]:personnel.append([name,val])
    for r in info.get('pessoal_restante_contas',[]):personnel.append([r['Conta']+' '+r['Nome'],r['Valor']])
    personnel.column_dimensions['A'].width=75;personnel.column_dimensions['B'].width=24
    for row in personnel.iter_rows(min_row=2):row[1].number_format='#,##0.00,, "M€"'

    funding=info.get('tesouraria_investimento') or {}
    for key,title in [('dfc','DFC Comparativo'),('ativos','Investimento Comparativo')]:
        rows=funding.get(key,[])
        if not rows:continue
        sheet=tab(title,rows)
        sheet.cell(1,6,'Âmbito')
        sheet.column_dimensions['F'].width=48
        for i,row in enumerate(rows,2):
            sheet.cell(i,6,row['Âmbito'])
            chart=BarChart();chart.type='col';chart.grouping='clustered';chart.overlap=0
            chart.title=row['Nome'];chart.y_axis.title='M€';chart.y_axis.numFmt='#,##0.00,, "M€"'
            chart.add_data(Reference(sheet,min_col=2,max_col=3,min_row=i,max_row=i),titles_from_data=False)
            from openpyxl.chart.series import SeriesLabel
            from openpyxl.chart.data_source import StrRef
            for series,color,letter in zip(chart.series,(PRIOR_FILL,CURRENT_FILL),('B','C')):
                series.title=SeriesLabel(strRef=StrRef(f="'"+title+"'!$"+letter+'$1'))
                series.graphicalProperties.solidFill=color
            chart.width=12;chart.height=7
            sheet.add_chart(chart,('H' if (i-2)%2==0 else 'Q')+str(2+((i-2)//2)*16))
        sheet.cell(len(rows)+3,1,funding.get('nota_dfc' if key=='dfc' else 'nota_ativos',''))

    pm = wb.create_sheet('PMP')
    pm.append(['Período', 'Dias'])
    for per, value, _ in pmp:
        pm.append([per, value])
    pm.column_dimensions['A'].width = 24
    pm.column_dimensions['B'].width = 16
    pm.column_dimensions['C'].width = 44

    for sheet in wb:
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.orientation = 'landscape'
        sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 1
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def to_pdf(info, logo, pmp):
    """PDF visual A4 horizontal: cartões, barras e mini-gráficos vetoriais."""
    import pymupdf as fitz

    doc = fitz.open()
    W, H = 842, 595
    navy = (.07, .16, .27)
    blue = (.13, .42, .63)
    orange = (.95, .64, .40)
    text_color = (.10, .20, .30)
    subtle = (.42, .51, .60)
    pale = (.95, .97, .99)
    border = (.83, .88, .93)
    white = (1, 1, 1)
    font_file = next((str(p) for p in [
        Path('C:/Windows/Fonts/arial.ttf'),
        Path('C:/Windows/Fonts/calibri.ttf'),
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        Path('/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf'),
    ] if p.is_file()), None)

    font_metrics = fitz.Font(fontfile=font_file) if font_file else fitz.Font('helv')

    def write(pg, x, y, val, size=11, color=text_color, font='ulsla', maxwidth=None):
        val = str(val)
        fontname = font if font_file else 'helv'
        if maxwidth:
            while len(val) > 3 and font_metrics.text_length(val, fontsize=size) > maxwidth:
                val = val[:-2]
            if val != str(val):
                val = val.rstrip() + '…'
        pg.insert_text((x, y), val, fontname=fontname, fontsize=size, color=color)

    def page(title, subtitle=None):
        pg = doc.new_page(width=W, height=H)
        if font_file:
            pg.insert_font(fontname='ulsla', fontfile=font_file)
        pg.draw_rect(fitz.Rect(0, 0, W, 85), color=None, fill=navy)
        if logo.exists():
            # A zona do logótipo é branca para preservar o azul institucional.
            pg.draw_rect(fitz.Rect(699, 8, 821, 75), color=None, fill=white, radius=.1)
            pg.insert_image(fitz.Rect(704, 9, 816, 74), filename=str(logo), keep_proportion=True)
        write(pg, 30, 29, 'ULSLA  |  SUMÁRIO EXECUTIVO FINANCEIRO', 15, white)
        write(pg, 30, 52, f'{MONTHS[info["month"]].capitalize()} {info["year"]} · Acumulado a {info["month"]:02d}/{info["year"]}', 11, (.80, .88, .96))
        write(pg, 30, 112, title, 17, navy)
        if subtitle:
            write(pg, 30, 132, subtitle, 9, subtle)
        pg.draw_line((30, 555), (812, 555), color=border, width=.65)
        write(pg, 30, 572, 'ULS Litoral Alentejano, E.P.E.  ·  Valores monetários em M€', 8, subtle)
        write(pg, 762, 572, f'Página {len(doc)}', 8, subtle)
        return pg

    def card(pg, rect, title, value, accent=blue, detail=None):
        r = fitz.Rect(rect)
        pg.draw_rect(r, color=border, fill=pale, radius=.1, width=.7)
        pg.draw_rect(fitz.Rect(r.x0, r.y0, r.x0+4, r.y1), color=None, fill=accent)
        write(pg, r.x0+15, r.y0+22, title, 9, subtle)
        write(pg, r.x0+15, r.y0+49, value, 20, navy)
        if detail:
            write(pg, r.x0+15, r.y0+65, detail, 8, subtle)

    def bar_compare(pg, rows, y0, boxheight, area=None):
        entries = [r for r in rows if r['N'] is not None or r['N-1'] is not None]
        if not entries:
            write(pg, 40, y0+30, 'Não existem valores homólogos disponíveis.', 12, subtle)
            return
        legx=460 if area is None else area[0]+90
        pg.draw_rect(fitz.Rect(legx,y0-18,legx+12,y0-10),color=None,fill=orange)
        write(pg,legx+18,y0-10,str(info['year']-1)+' (N-1)',8,subtle)
        pg.draw_rect(fitz.Rect(legx+115,y0-18,legx+127,y0-10),color=None,fill=blue)
        write(pg,legx+133,y0-10,str(info['year'])+' (N)',8,subtle)
        label_x, x0, x1 = (38, 245, 782) if area is None else (area[0],area[0]+168,area[1])
        max_abs = max((abs(float(r[f])) for r in entries for f in ('N-1', 'N') if r[f] is not None), default=1) or 1
        xmin = min([float(r[f]) for r in entries for f in ('N-1','N') if r[f] is not None] + [0])
        xmax = max([float(r[f]) for r in entries for f in ('N-1','N') if r[f] is not None] + [0])
        if xmax == xmin: xmax = xmin + 1
        xzero = x0 + (0-xmin) / (xmax-xmin) * (x1-x0)
        pg.draw_line((xzero,y0+3), (xzero,y0+boxheight-8), color=border, width=.9)
        step = boxheight / len(entries)
        for i, r in enumerate(entries):
            y = y0 + i*step + 9
            label_lines = wrapped(r['Nome'],x0-label_x-10,8 if area is None else 7)
            for li, line in enumerate(label_lines[:2]):
                write(pg, label_x, y+6+li*10, line, 8 if area is None else 7, text_color)
            for j, (key, color) in enumerate((('N-1',orange), ('N',blue))):
                val=r[key]
                if val is None: continue
                v=float(val)
                px=x0+(v-xmin)/(xmax-xmin)*(x1-x0)
                ya=y+2+j*12
                left=min(px,xzero); right=max(px,xzero)
                if right-left < 1: right=left+1
                pg.draw_rect(fitz.Rect(left,ya,right,ya+9),color=None,fill=color)
                # Numeric labels beyond bars are deliberately compact.
                label=fmt(v,True)
                lx=(px+5) if v>=0 else max(x0,px-78)
                lx=min(lx, x1-76)
                write(pg,lx,ya+8,label,7,navy)

    def mini(pg, rect, entry):
        x0,y0,x1,y1=rect
        pg.draw_rect(fitz.Rect(*rect), color=border, fill=pale, radius=.1, width=.7)
        name = entry['Nome']
        # Two lines prevent long account descriptions from overlapping.
        if len(name)>30:
            cut=name.rfind(' ',0,29)
            if cut < 10: cut=28
            head=[name[:cut],name[cut:].strip()]
        else: head=[name]
        for i,line in enumerate(head[:2]):
            write(pg,x0+10,y0+17+i*10,line[:36],8,navy)
        pts=entry['Pontos']
        observed=[p['Valor'] for p in pts if p['Valor'] is not None]
        if not observed:
            write(pg,x0+9,y0+55,'Sem dados',9,subtle)
            return
        lo=min(observed); hi=max(observed)
        span=hi-lo if hi!=lo else max(abs(hi)*.15,1)
        lo-=span*.24;hi+=span*.58
        n=len(pts)
        left=x0+25;right=x1-22;top=y0+47;bottom=y1-28
        pg.draw_line((left,bottom),(right,bottom),color=border,width=.7)
        for j in range(3):
            gy=top+(bottom-top)*j/2
            pg.draw_line((left,gy),(right,gy),color=border,width=.35)
        coords=[]
        for j,p in enumerate(pts):
            xx=left+(right-left)*(j/(n-1) if n>1 else .5)
            write(pg,xx-13,y1-11,str(p['Ano']),7,subtle)
            if p['Valor'] is None:
                coords.append(None);continue
            yy=bottom-(p['Valor']-lo)/(hi-lo)*(bottom-top)
            coords.append((xx,yy,p['Valor']))
        for a,b in zip(coords,coords[1:]):
            if a and b:pg.draw_line((a[0],a[1]),(b[0],b[1]),color=blue,width=2)
        for pos in coords:
            if not pos:continue
            xx,yy,val=pos
            pg.draw_circle((xx,yy),3.3,color=None,fill=blue)
            value=fmt(val,True)
            # Small value labels kept inside the card.
            write(pg,max(x0+5,min(x1-67,xx-19)),max(y0+36,yy-10),value,7,blue)

    from analise_executiva import narratives, reconciliation
    sections = narratives(info,pmp)

    def wrapped(text,width=778,size=10):
        lines=[]
        for para in str(text).split('\n'):
            words=para.split();line=''
            for word in words:
                trial=(line+' '+word).strip()
                if font_metrics.text_length(trial,fontsize=size)>width and line:
                    lines.append(line);line=word
                else:line=trial
                # URLs or very long words are split to keep every glyph visible.
                while font_metrics.text_length(line,fontsize=size)>width:
                    cut=len(line)-1
                    while font_metrics.text_length(line[:cut],fontsize=size)>width:cut-=1
                    lines.append(line[:cut]);line=line[cut:]
            lines.append(line)
        return lines

    def paragraph(pg,text,x=32,y=165,width=776,size=10,leading=14):
        for line in wrapped(text,width,size):
            write(pg,x,y,line,size);y+=leading
        return y

    def text_pages(title,items):
        pg=page(title,'Variações mensais e acumuladas · comparação homóloga')
        y=163
        for item in items:
            if y>487:pg=page(title+' · continuação');y=163
            write(pg,32,y,item['titulo'],12,navy);y+=23
            for line in wrapped(item['texto'],776,10):
                if y>531:pg=page(title+' · continuação');y=165
                write(pg,32,y,line,10);y+=15
            y+=18

    pg=page('Síntese executiva','Indicadores essenciais, comparação homóloga e prazo médio de pagamento')
    entries=list(info['cards'].items())
    for i,(name,value) in enumerate(entries):
        x=30+(i%4)*200;y=148+(i//4)*78
        card(pg,(x,y,x+191,y+69),name,fmt(value,True))
    paragraph(pg,sections[0]['texto'],y=320,size=9,leading=13)
    write(pg,30,450,'PRAZO MÉDIO DE PAGAMENTO · ÚLTIMOS 4 TRIMESTRES',11,navy)
    if pmp:
        for i,(per,val,state) in enumerate(pmp[-4:]):
            card(pg,(30+i*200,463,221+i*200,535),per,f'{val:.1f}'.replace('.',',')+' dias')
    else:write(pg,32,485,'Dados de PMP indisponíveis.',10,subtle)

    pg=page('Demonstração de Resultados','Acumulado · gastos apresentados e resultado líquido reportado na DR')
    bar_compare(pg,info['dr'],165,340)
    write(pg,32,535,'Os gastos apresentados podem não abranger todas as rubricas que integram o resultado líquido.',8,subtle)
    pg=page('Evolução do balanço','Rubricas do Balanço · a conta 27892 não integra os fornecedores neste gráfico')
    bar_compare(pg,info['balan'],165,255)
    b=info.get('balanco_atual',{});a=info.get('balanco_anterior',{})
    from analise_executiva import comparison
    context=' '.join(comparison(n,a.get(k),b.get(k),'saldo à data') for n,k in [('Outras contas a receber','outras_contas_receber'),('Adiantamentos de clientes','adiantamentos_clientes')])
    paragraph(pg,context+' As variações observadas não demonstram, por si só, a origem dos movimentos.',y=451,size=9,leading=14)

    funding=info.get('tesouraria_investimento') or {}
    for key,title,note in [('dfc','DFC · caixa e pagamentos','nota_dfc'),('ativos','Investimento · compras e obras em curso','nota_ativos')]:
        rows=funding.get(key,[])
        if not rows:continue
        for start in range(0,len(rows),6):
            pg=page(title,'Comparação homóloga · '+str(info['year']-1)+' laranja / '+str(info['year'])+' azul · valores em M€')
            for i,row in enumerate(rows[start:start+6]):
                x=30+(i%3)*265;y=153+(i//3)*177
                pg.draw_rect(fitz.Rect(x,y,x+251,y+165),color=border,fill=pale,radius=.1,width=.7)
                for j,line in enumerate(wrapped(row['Nome'],231,8.5)[:2]):write(pg,x+10,y+17+j*11,line,8.5,navy)
                for j,line in enumerate(wrapped(row['Âmbito'],231,7)[:2]):write(pg,x+10,y+44+j*9,line,7,subtle)
                vals=[row['N-1'],row['N']]
                observed=[v for v in vals if v is not None]
                lo=min([0]+observed);hi=max([0]+observed);span=hi-lo or 1
                top=y+83;bottom=y+143
                zero=bottom-(0-lo)/span*(bottom-top)
                pg.draw_line((x+17,zero),(x+234,zero),color=border,width=.7)
                for j,(val,color) in enumerate(zip(vals,(orange,blue))):
                    xx=x+37+j*112
                    write(pg,xx-12,y+73,fmt(val),8,navy)
                    write(pg,xx+2,y+158,str(info['year']-1+j),7,subtle)
                    if val is None:continue
                    yy=bottom-(val-lo)/span*(bottom-top)
                    left,bot=min(zero,yy),max(zero,yy)
                    pg.draw_rect(fitz.Rect(xx,left,xx+44,max(left+1,bot)),color=None,fill=color)
            paragraph(pg,funding.get(note,''),y=519,size=8,leading=11)

    # Narrativas completas, sem truncar bases zero, indisponibilidades ou comentários.
    text_pages('Resumo das variações',sections[1:4])
    text_pages('Posição financeira e dívida',sections[6:])
    if info.get('comentario_gestao','').strip():
        text_pages('Comentário da gestão',[{'titulo':'Comentário guardado · '+info['period'],'texto':info['comentario_gestao']}])

    def mini_pages(title, cards, cols=3, rows=3):
        if not cards:return
        capacity=cols*rows
        for start in range(0,len(cards),capacity):
            pg=page(title,'Valores acumulados · três anos homólogos')
            subset=cards[start:start+capacity]
            actual_rows=max(1,(len(subset)+cols-1)//cols)
            ch=min(175,(377-(actual_rows-1)*10)/actual_rows)
            cw=(782-(cols-1)*10)/cols
            for i,e in enumerate(subset):
                x=30+(i%cols)*(cw+10);y=155+(i//cols)*(ch+10)
                mini(pg,(x,y,x+cw,y+ch),e)

    mini_pages('Gastos · evolução homóloga',info.get('gastos_cards',[]),4,3)
    pg=page('Principais contributos para os gastos','Grupos não remuneratórios · exclui os três grupos de remunerações e encargos')
    bar_compare(pg,info.get('gastos_contribuintes',[]),165,360)

    pg=page('Rendimentos · Contrato Programa e extra contrato','Componentes separadas para preservar a leitura dos rendimentos extra contrato')
    cp=[r for r in info.get('rendimentos_cards',[]) if r['Nome']==CONTRACT_GROUP]
    if cp:mini(pg,(30,155,315,335),cp[0])
    else:write(pg,35,180,'Contrato Programa indisponível.',10,subtle)
    cp_rows=[r for r in info.get('rendimentos_contribuintes',[]) if r['Nome']==CONTRACT_GROUP]
    paragraph(pg,next(r['texto'] for r in sections if r['titulo']=='Contrato Programa'),x=32,y=365,width=275,size=9,leading=14)
    extra=[r for r in info.get('rendimentos_contribuintes',[]) if r['Nome']!=CONTRACT_GROUP]
    write(pg,350,156,'RENDIMENTOS EXTRA CONTRATO PROGRAMA',10,navy)
    if extra:bar_compare(pg,extra,193,265,area=(350,794))
    paragraph(pg,next(r['texto'] for r in sections if r['titulo']=='Rendimentos extra Contrato Programa'),x=350,y=480,width=445,size=9,leading=13)
    mini_pages('Extra Contrato Programa · evolução homóloga',[r for r in info.get('rendimentos_cards',[]) if r['Nome']!=CONTRACT_GROUP])

    d=info.get('debt')
    pg=page('Dívida · estrutura por setor','Dívida a fornecedores e obrigações documentais · perímetros distintos')
    card(pg,(30,150,410,235),'DÍVIDA A FORNECEDORES',fmt(info.get('contabilistica',{}).get('total')))
    card(pg,(430,150,811,235),'DÍVIDA DOCUMENTAL',fmt(d['total']) if d else '—')
    paragraph(pg,'A dívida a fornecedores abrange os fornecedores, os fornecedores de imobilizado e o saldo credor líquido da conta 27892. A dívida documental inclui também descontos e encargos associados aos vencimentos; por isso, os dois totais têm perímetros distintos.',y=267,size=10,leading=15)
    if d:
        write(pg,32,342,'DÍVIDA DOCUMENTAL POR SETOR',11,navy)
        for i,r in enumerate(d['sector'][:3]):
            card(pg,(30+i*265,357,280+i*265,435),r['Nome'],fmt(r['Valor']))
        for i,r in enumerate(d['type'][:2]):
            write(pg,32+i*395,478,r['Nome']+': '+fmt(r['Valor']),11,navy)
    else:write(pg,32,360,'A informação documental não está disponível para este período.',11,subtle)
    if d:
        pg=page('Maiores credores por setor','Cinco maiores saldos credores líquidos · percentagem no total líquido do respetivo setor')
        for col,sector in enumerate(('SNS','Estado','Externos')):
            x=30+col*265
            write(pg,x,164,sector,14,navy)
            den=next((r['Valor'] for r in d['sector'] if r['Nome']==sector),None)
            write(pg,x,184,'Total: '+fmt(den),10,subtle)
            rows=d.get('rankings',{}).get(sector,[])
            if not rows:write(pg,x,215,'Sem saldos positivos.',9,subtle)
            for i,r in enumerate(rows):
                y=218+i*56
                lines=wrapped(r['Nome'],245,8)
                for j,line in enumerate(lines[:2]):write(pg,x,y+j*11,line,8,navy)
                pct=f"{r['Percentagem']:.1f}%" if r.get('Percentagem') is not None else 'percentagem indisponível'
                write(pg,x,y+29,fmt(r['Valor'])+' · '+pct,9,blue)
        y=519
        for r in d.get('factoring',[]):
            write(pg,32,y,r['Nome']+': '+fmt(r['Valor'])+' (incluído no stock)',8,subtle);y+=12

    # Detalhe remuneratório apenas no anexo; compacto e sem páginas por subgrupo.
    pg=page('Anexo · gastos com pessoal','Reconciliação da DR com remunerações e encargos do balancete')
    for i,(name,val) in enumerate([('PESSOAL · DR',info.get('pessoal_dr')),('REMUNERAÇÕES E ENCARGOS',info.get('remuneracoes',{}).get('total')),('PARCELA RESTANTE',info.get('pessoal_restante'))]):
        card(pg,(30+i*265,150,280+i*265,225),name,fmt(val))
    bar_compare(pg,info['remuneracoes']['pool1'],265,135)
    rest=info.get('pessoal_restante_contas',[])
    if rest:
        detail='Parcela fora dos três grupos remuneratórios: '+ '; '.join(r['Conta']+' '+r['Nome']+': '+fmt(r['Valor']) for r in rest)+'.'
        paragraph(pg,detail,y=425,size=8,leading=12)
    # Gráficos agrupados por natureza, iguais ao detalhe do dashboard.
    # Partilhar a página entre grupos pequenos evita anexos com um único gráfico.
    details=info['remuneracoes']['pool2']
    detail_page=None
    cursor=155
    for group in info['remuneracoes']['pool1']:
        rows=[dict(r,Nome=r['Pool 2'] or 'Sem classificação detalhada')
              for r in details if r['Pool 1']==group['Pool 1']]
        offset=0
        while offset<len(rows):
            capacity=int((535-cursor-36)/28) if detail_page is not None else 0
            if capacity<1:
                detail_page=page('Anexo · detalhe remuneratório',
                    'Comparação acumulada homóloga por componente · valores em M€')
                cursor=155
                capacity=int((535-cursor-36)/28)
            count=min(capacity,len(rows)-offset)
            heading=group['Pool 1']+(' · continuação' if offset else '')
            write(detail_page,32,cursor+5,heading,11,navy)
            bar_compare(detail_page,rows[offset:offset+count],cursor+32,count*28)
            cursor+=36+count*28
            offset+=count

    out=doc.tobytes(garbage=4,deflate=True)
    doc.close()
    return out
