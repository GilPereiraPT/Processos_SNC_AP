from __future__ import annotations
from pathlib import Path
from html import escape
import streamlit as st

ROOT = Path(__file__).resolve().parent
LOGO_CANDIDATES = [
    'logotipo ULSLA.png',
    'logotipo_ULSLA.png',
    'logo_ulsla.png',
    'ulsla_logo.png',
    'Logotipo ULSLA.png',
]


def find_logo() -> Path | None:
    for name in LOGO_CANDIDATES:
        p = ROOT / name
        if p.exists():
            return p
    # procurar em subpastas mais comuns
    for pattern in ('assets/logotipo ULSLA.png', 'assets/logo_ulsla.png', 'assets/ulsla_logo.png'):
        matches = list(ROOT.glob(pattern))
        if matches:
            return matches[0]
    return None


def apply_css():
    st.markdown(
        """
        <style>
        .stApp {background:linear-gradient(145deg,#f5f8fc,#edf3f8);color:#19334e;}
        .block-container {padding-top:1.3rem;padding-bottom:3rem;}
        h1,h2,h3 {color:#173550;}
        [data-testid="stMetric"] {background:white;border:1px solid #dbe6ef;border-radius:16px;padding:16px;}
        .ulsla-hero {
            background: linear-gradient(135deg, #0d355d 0%, #166a7a 100%);
            padding: 1.2rem 1.4rem;
            border-radius: 18px;
            color: white;
            margin-bottom: 1rem;
            box-shadow: 0 8px 24px rgba(0,0,0,0.08);
        }
        .ulsla-subtle {
            color: #6b7280;
            font-size: 0.95rem;
            margin-top: 0.2rem;
        }
        .ulsla-card {
            border: 1px solid #d7dde5;
            border-radius: 16px;
            padding: 1rem 1rem 0.5rem 1rem;
            background: white;
            min-height: 210px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.03);
        }
        .ulsla-card h3 {
            margin-top: 0;
            margin-bottom: 0.35rem;
            color: #16324f;
        }
        .ulsla-card p {
            color: #516173;
            font-size: 0.95rem;
            min-height: 64px;
        }
        .ulsla-mini-note {
            font-size: 0.85rem;
            color: #6b7280;
        }
        .ulsla-section-title {
            margin-top: 0.5rem;
            margin-bottom: 0.5rem;
            color: #16324f;
            font-weight: 700;
            font-size: 1.2rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def hero(title: str, subtitle: str = "", small_caption: str = ""):
    apply_css()
    logo = find_logo()
    left, right = st.columns([1, 7])
    with left:
        if logo:
            st.image(str(logo), use_container_width=True)
    with right:
        st.markdown(
            f"""
            <div class='ulsla-hero'>
                <div style='font-size:2.1rem;font-weight:800;line-height:1.1'>{escape(title)}</div>
                {f"<div style='margin-top:0.45rem;font-size:1.04rem;opacity:0.95'>{escape(subtitle)}</div>" if subtitle else ''}
                {f"<div style='margin-top:0.35rem;font-size:0.9rem;opacity:0.88'>{escape(small_caption)}</div>" if small_caption else ''}
            </div>
            """,
            unsafe_allow_html=True,
        )


def _period_widget(method, label, options, *args, target=None, **kwargs):
    """Seletor temporal acessível; preserva valores, chaves e callbacks existentes."""
    import hashlib
    host = target if target is not None else st
    identity = str(kwargs.get('key') or label)
    token = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]
    box_key = 'ulsla_period_'+token
    with host.container(key=box_key):
        value = getattr(st, method)(label, options, *args, **kwargs)
        selected = bool(value) if isinstance(value,list) else value is not None and str(value) not in ('','—')
        formatter = kwargs.get('format_func', str)
        formatted = ', '.join(str(formatter(v)) for v in value) if isinstance(value,list) else str(formatter(value)) if selected else ''
        caption = ('Selecionado: '+formatted) if selected else 'Selecione o período para continuar.'
        if kwargs.get('disabled'): caption = 'Seleção indisponível nesta opção.'
        st.caption(caption)
    background, border = ('#e3f2fa','#126b8a') if selected else ('#fff5d6','#a86c00')
    st.markdown(f'''<style>
    .st-key-{box_key} [data-baseweb="select"] > div {{
      background:{background}!important;border:2px solid {border}!important;border-radius:10px!important;min-height:44px;
    }}
    .st-key-{box_key} [data-baseweb="select"] * {{color:#123a55!important;font-weight:650;}}
    .st-key-{box_key} [data-baseweb="select"]:hover > div {{border-color:#a86c00!important;}}
    .st-key-{box_key} [data-baseweb="select"]:focus-within > div {{
      border-color:#0058a3!important;box-shadow:0 0 0 3px #94c9ef!important;
    }}
    .st-key-{box_key} [data-testid="stWidgetLabel"] p {{font-weight:750!important;}}
    </style>''',unsafe_allow_html=True)
    return value


def period_selectbox(label, options, *args, target=None, **kwargs):
    return _period_widget('selectbox',label,options,*args,target=target,**kwargs)


def period_multiselect(label, options, *args, target=None, **kwargs):
    return _period_widget('multiselect',label,options,*args,target=target,**kwargs)
