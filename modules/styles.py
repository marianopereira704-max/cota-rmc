"""
Identidade visual — aplica o design system documentado na skill
`mariano-identidade-visual` (navy/verde, cards, badges de status, mesh
gradient restrito a cabeçalho/estado vazio).

Cores e tokens de design NÃO são "constantes de regra de negócio" no sentido
que a diretriz do projeto pede pra evitar — são o próprio sistema de design,
intencionalmente fixo entre projetos (Mapa da Farmácia, PEX 2.0, PedidoFarma
Pro, e agora Cota RMC). Centralizados aqui para reaproveitamento.
"""
from __future__ import annotations

NAVY = "#17375E"
NAVY_LIGHT = "#4A6E90"
GREEN = "#8DC63F"
GREEN_DARK = "#639922"
BG_CARD = "#F7F8FA"
BORDER = "#E4E7EB"
TEXT_MUTED = "#7A8699"

STATUS_COLORS = {
    "sugestao": {"bg": "#FAEEDA", "text": "#854F0B"},
    "confirmado": {"bg": "#EAF3DE", "text": "#27500A"},
    "alterado": {"bg": "#DCE9F7", "text": "#123A63"},
    "multiplo": {"bg": "#EEE8F7", "text": "#4A2E7A"},
    # Único par vermelho do sistema — reservado para sinais de urgência real
    # (não usado hoje, mantido reservado — se precisar de urgência de novo
    # no futuro, é este o par a usar, não inventar outro vermelho).
    "urgente": {"bg": "#FBE1DE", "text": "#7A1E14"},
    # Neutro — pílula "sem chamar atenção" (ex: já otimizado, nada a fazer).
    "neutro": {"bg": "#EDEFF2", "text": "#4B5563"},
}

# Mapeamento dos status de negócio do Cota RMC para o par de cor do sistema.
# "Risco de Ruptura" não usa vermelho (fora da paleta) — usa o par âmbar,
# igual a outros estados de atenção do sistema.
BUSINESS_STATUS_STYLE = {
    "Oportunidade": STATUS_COLORS["alterado"],   # azul — sinal informativo, não urgência
    "Risco de Ruptura": STATUS_COLORS["sugestao"],  # âmbar — atenção
    "Normal": STATUS_COLORS["confirmado"],       # verde — ok
}


def inject_base_css() -> str:
    return f"""
    <style>
    :root {{
        --navy: {NAVY};
        --navy-light: {NAVY_LIGHT};
        --green: {GREEN};
        --green-dark: {GREEN_DARK};
        --bg-card: {BG_CARD};
        --border: {BORDER};
        --text-muted: {TEXT_MUTED};
    }}

    /* Botão primário (stButton) */
    div[data-testid="stButton"] button {{
        background-color: var(--navy);
        color: white;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        transition: box-shadow 180ms ease, transform 180ms ease;
    }}
    div[data-testid="stButton"] button:hover {{
        box-shadow: 0 0 0 4px rgba(74, 110, 144, 0.25);
    }}

    div[data-testid="stDownloadButton"] button {{
        background-color: white;
        color: var(--navy);
        border: 1px solid var(--navy);
        border-radius: 8px;
        font-weight: 600;
    }}

    /* Botão "tertiary" (type="tertiary") — usado pra navegação discreta
       (ex: paginação "‹ Página anterior" / "Próxima página ›") e outros
       controles que não devem competir visualmente com o botão primário.
       Precisa de seletor mais específico que a regra acima pra vencer por
       especificidade CSS, já que ambas miram `button` dentro de
       `[data-testid="stButton"]`. */
    div[data-testid="stButton"] button[kind="tertiary"] {{
        background: none;
        border: none;
        box-shadow: none;
        color: var(--navy-light);
        font-weight: 500;
        padding: 2px 4px;
        text-decoration: underline;
    }}
    div[data-testid="stButton"] button[kind="tertiary"]:hover {{
        box-shadow: none;
        color: var(--navy);
    }}
    div[data-testid="stButton"] button[kind="tertiary"]:disabled {{
        color: var(--text-muted);
        text-decoration: none;
        opacity: 0.6;
    }}

    /* Cabeçalho com mesh gradient — restrito à faixa de topo */
    .cota-rmc-header {{
        border-radius: 14px;
        padding: 28px 32px;
        margin-bottom: 24px;
        background:
            radial-gradient(circle at 15% 20%, rgba(23,55,94,0.85), transparent 45%),
            radial-gradient(circle at 80% 10%, rgba(141,198,63,0.55), transparent 40%),
            radial-gradient(circle at 60% 90%, rgba(74,110,144,0.55), transparent 45%),
            radial-gradient(circle at 20% 90%, rgba(99,153,34,0.45), transparent 40%),
            var(--navy);
        color: white;
    }}
    .cota-rmc-header h1 {{
        font-size: 1.9rem;
        font-weight: 700;
        margin: 0;
    }}
    .cota-rmc-header p {{
        color: rgba(255,255,255,0.85);
        margin: 4px 0 0 0;
    }}

    /* Card neutro de conteúdo */
    .cota-rmc-card {{
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 16px 20px;
    }}

    /* Badge de status (pílula) */
    .cota-rmc-badge {{
        display: inline-block;
        padding: 3px 10px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 600;
    }}

    /* Badge de contagem/notificação (círculo sólido) */
    .cota-rmc-count-badge {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 20px;
        height: 20px;
        padding: 0 6px;
        border-radius: 999px;
        background: var(--navy);
        color: white;
        font-size: 12px;
        font-weight: 700;
    }}

    .cota-rmc-count-badge.alerta {{
        background: #854F0B;
    }}

    p, span, div, label {{
        color: inherit;
    }}
    .cota-rmc-muted {{
        color: var(--text-muted);
        font-size: 13px;
    }}

    /* Card "manchete" — um número grande de destaque real, maior que os
       cards de status/métrica ao redor (ex: economia total identificada).
       Gradiente verde: reaproveita o mesmo par de cor usado no cabeçalho,
       não inventa cor nova. */
    .cota-rmc-headline-card {{
        background: linear-gradient(135deg, var(--green) 0%, var(--green-dark) 100%);
        border-radius: 16px;
        padding: 22px 30px;
        margin-bottom: 20px;
        color: white;
    }}
    .cota-rmc-headline-card .headline-label {{
        font-size: 13px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        opacity: 0.92;
    }}
    .cota-rmc-headline-card .headline-value {{
        font-size: 2.75rem;
        font-weight: 800;
        line-height: 1.15;
        margin-top: 2px;
    }}
    .cota-rmc-headline-card .headline-caption {{
        font-size: 13px;
        opacity: 0.85;
        margin-top: 4px;
    }}

    /* Linha expandida do ranking de lojas (produtos "Compra mais caro"
       daquela loja) — só nome do produto + economia, sem repetir colunas. */
    .opv-rank-sublist {{
        padding: 4px 0 10px 4px;
        margin-bottom: 4px;
        border-bottom: 1px solid var(--border);
    }}
    .opv-rank-produto {{
        display: flex;
        justify-content: space-between;
        gap: 12px;
        padding: 4px 0 4px 24px;
        font-size: 13px;
    }}
    .opv-rank-produto .opv-rank-nome {{
        color: #1F2937;
    }}
    .opv-rank-produto .opv-rank-economia {{
        color: #27500A;
        font-weight: 700;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
    }}
    </style>
    """


def status_badge_html(status: str) -> str:
    style = BUSINESS_STATUS_STYLE.get(status, STATUS_COLORS["confirmado"])
    return (
        f'<span class="cota-rmc-badge" style="background:{style["bg"]};color:{style["text"]};">'
        f"{status}</span>"
    )


def header_html(title: str, subtitle: str = "") -> str:
    sub = f"<p>{subtitle}</p>" if subtitle else ""
    return f'<div class="cota-rmc-header"><h1>{title}</h1>{sub}</div>'


def count_badge_html(n: int, alerta: bool = False) -> str:
    cls = "cota-rmc-count-badge alerta" if alerta else "cota-rmc-count-badge"
    return f'<span class="{cls}">{n}</span>'


def page_max_width_css(container_key: str, max_width_px: int = 1150) -> str:
    """
    CSS escopada (via classe `st-key-<container_key>` do st.container) que
    limita a largura de UMA página específica — não afeta as outras, ao
    contrário de mexer direto no `.block-container` global do Streamlit.
    """
    return f"""
    <style>
    div[class*="st-key-{container_key}"] {{
        max-width: {max_width_px}px;
        margin: 0 auto;
    }}
    </style>
    """


def headline_card_html(label: str, value: str, caption: str = "") -> str:
    cap = f'<div class="headline-caption">{caption}</div>' if caption else ""
    return (
        '<div class="cota-rmc-headline-card">'
        f'<div class="headline-label">{label}</div>'
        f'<div class="headline-value">{value}</div>'
        f"{cap}"
        "</div>"
    )
