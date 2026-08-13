"""
Tabela HTML/CSS customizada da página "Oportunidades de Venda".

Existe porque o st.dataframe nativo do Streamlit não consegue (verificado
empiricamente, não suposição): (1) pílulas de verdade — cantos arredondados,
padding próprio — dentro de uma célula (a grade é desenhada em canvas, só
pinta o retângulo inteiro da célula); (2) coluna sticky + cabeçalho sticky
simultâneos junto com rolagem livre por muitas linhas sem paginação; (3)
formatação numérica brasileira garantida (o `format="localized"` do
column_config depende do locale do navegador de quem está vendo, não é
controlável pelo servidor). Decisão registrada e confirmada com Mariano.

Usa Custom Components v2 (`st.components.v2.component`) — não v1 (não usa
`components.v1.html`, que é depreciado). A tabela inteira (cabeçalho +
linhas) é HTML montado em JS a partir de `data`; clicar num cabeçalho
ordenável chama `setStateValue` (não `setTriggerValue`), porque o valor
precisa persistir em `st.session_state[key]` e já fica disponível pro script
Python ler *na mesma rodada* do clique (testado e confirmado: não há atraso
de uma rodada) — sem isso a tabela pareceria travar um clique atrás.

Ainda pagina (não é rolagem virtual/infinita): 100-200 linhas por vez mantém
o payload JSON e o DOM do navegador leves. Rolagem livre por dezenas de
milhares de linhas exigiria reimplementar virtualização de linhas em JS
(observar scroll, montar/desmontar linhas conforme a viewport) — decisão
consciente de não fazer isso agora para não introduzir fragilidade extra;
ver conversa que aprovou esta abordagem.
"""
from __future__ import annotations

import math
from typing import Any

import streamlit as st

from modules import styles

CSS = f"""
.opv-wrap {{
    font-family: "Source Sans Pro", sans-serif;
}}
.opv-table-scroll {{
    overflow: auto;
    max-height: 620px;
    border: 1px solid {styles.BORDER};
    border-radius: 12px;
}}
table.opv-table {{
    border-collapse: separate;
    border-spacing: 0;
    width: max-content;
    min-width: 100%;
    font-size: 13px;
    color: #1F2937;
}}
table.opv-table thead th {{
    position: sticky;
    top: 0;
    z-index: 2;
    background: {styles.BG_CARD};
    font-weight: 600;
    text-align: left;
    padding: 10px 14px;
    border-bottom: 1px solid {styles.BORDER};
    white-space: nowrap;
    user-select: none;
}}
table.opv-table thead th[data-sortable="true"] {{
    cursor: pointer;
}}
table.opv-table thead th[data-sortable="true"]:hover {{
    background: #EEF0F3;
}}
table.opv-table thead th.opv-sticky-col {{
    left: 0;
    z-index: 3;
}}
table.opv-table tbody td {{
    padding: 8px 14px;
    border-bottom: 1px solid #F0F1F3;
    white-space: nowrap;
    background: white;
}}
table.opv-table tbody td.opv-sticky-col {{
    position: sticky;
    left: 0;
    z-index: 1;
}}
table.opv-table tbody tr:hover td {{
    background: #FAFBFC;
}}
table.opv-table tbody tr:nth-child(even) td {{
    background: #FCFCFD;
}}
table.opv-table tbody tr:nth-child(even):hover td {{
    background: #F5F6F8;
}}
.opv-num {{
    text-align: right;
    font-variant-numeric: tabular-nums;
    display: block;
}}
.opv-pill {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    white-space: nowrap;
}}
.opv-sort-arrow {{
    margin-left: 4px;
    opacity: 0.55;
    font-size: 10px;
}}
.opv-empty {{
    padding: 24px;
    text-align: center;
    color: {styles.TEXT_MUTED};
}}
"""

JS = """
export default function (component) {
  const { data, parentElement, setStateValue } = component;

  // usa o próprio div declarado em html= (não cria um elemento novo à parte
  // — Streamlit dimensiona o componente observando o que já existe desde o
  // mount inicial; um <div> criado do zero via createElement depois não é
  // observado do mesmo jeito e o componente fica com altura 0, escondendo
  // o conteúdo mesmo ele existindo no DOM).
  const root = parentElement.querySelector("#opv-mount");
  root.className = "opv-wrap";

  const columns = data.columns || [];
  const rows = data.rows || [];
  const sortCol = data.sortCol;
  const sortDir = data.sortDir;

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  function fmtInt(v) {
    if (v === null || v === undefined) return "";
    return Math.round(v).toLocaleString("pt-BR");
  }

  function fmtBRL(v) {
    if (v === null || v === undefined) return "";
    return "R$ " + v.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function fmtPct(v) {
    if (v === null || v === undefined) return "";
    const sinal = v >= 0 ? "+" : "";
    return sinal + v.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + "%";
  }

  function renderCell(col, row) {
    const raw = row[col.key];
    if (col.type === "pill") {
      if (raw === null || raw === undefined || !raw.value) return "";
      return `<span class="opv-pill" style="background:${raw.bg};color:${raw.text};">${escapeHtml(raw.value)}</span>`;
    }
    if (raw === null || raw === undefined) return "";
    if (col.type === "currency") return `<span class="opv-num">${fmtBRL(raw)}</span>`;
    if (col.type === "percent") return `<span class="opv-num">${fmtPct(raw)}</span>`;
    if (col.type === "integer") return `<span class="opv-num">${fmtInt(raw)}</span>`;
    return escapeHtml(raw);
  }

  if (rows.length === 0) {
    root.innerHTML = '<div class="opv-empty">Nenhuma linha para os filtros selecionados.</div>';
    return;
  }

  let html = '<div class="opv-table-scroll"><table class="opv-table"><thead><tr>';
  for (const col of columns) {
    const stickyClass = col.sticky ? " opv-sticky-col" : "";
    let arrow = "";
    if (col.sortable && col.key === sortCol) {
      arrow = `<span class="opv-sort-arrow">${sortDir === "asc" ? "▲" : "▼"}</span>`;
    }
    html += `<th class="${stickyClass}" data-col="${col.key}" data-sortable="${!!col.sortable}">${escapeHtml(col.label)}${arrow}</th>`;
  }
  html += "</tr></thead><tbody>";
  for (const row of rows) {
    html += "<tr>";
    for (const col of columns) {
      const stickyClass = col.sticky ? " opv-sticky-col" : "";
      html += `<td class="${stickyClass}">${renderCell(col, row)}</td>`;
    }
    html += "</tr>";
  }
  html += "</tbody></table></div>";

  root.innerHTML = html;

  root.querySelectorAll('th[data-sortable="true"]').forEach((th) => {
    th.onclick = () => {
      const col = th.getAttribute("data-col");
      let novaDirecao = "desc";
      if (col === sortCol) {
        novaDirecao = sortDir === "desc" ? "asc" : "desc";
      }
      setStateValue("sortCol", col);
      setStateValue("sortDir", novaDirecao);
    };
  });
}
"""

_TABELA_OPORTUNIDADES = st.components.v2.component(
    "cota_rmc_tabela_oportunidades",
    html="<div id='opv-mount'></div>",
    css=CSS,
    js=JS,
)


def ler_ordenacao_atual(key: str, coluna_padrao: str, direcao_padrao: str) -> tuple[str, str]:
    """
    Lê a ordenação atual (coluna + direção) do estado do componente — sem
    montar nada. Precisa ser chamado ANTES de ordenar/paginar o DataFrame em
    Python, porque o componente só mostra o que já vier pronto em `data`
    (ele não ordena nada sozinho no JS).
    """
    estado = st.session_state.get(key, {})
    return estado.get("sortCol", coluna_padrao), estado.get("sortDir", direcao_padrao)


def montar_pill(valor: str, par_cor: dict[str, str]) -> dict[str, str]:
    return {"value": valor, "bg": par_cor["bg"], "text": par_cor["text"]}


def _limpo(v: Any) -> Any:
    """NaN/NaT do pandas não serializa em JSON — vira None (célula em branco)."""
    if v is None:
        return None
    try:
        if isinstance(v, float) and math.isnan(v):
            return None
    except TypeError:
        return None
    return v


def renderizar_tabela(
    colunas: list[dict],
    linhas: list[dict],
    sort_col: str,
    sort_dir: str,
    key: str,
) -> None:
    """
    Renderiza a tabela. `linhas` já deve vir ORDENADA e PAGINADA — este
    componente só desenha o que recebe, não ordena/pagina sozinho.

    `colunas`: lista de {key, label, type: "text"|"currency"|"percent"|
    "integer"|"pill", sortable: bool, sticky: bool}.
    """
    linhas_limpas = [{k: _limpo(v) for k, v in linha.items()} for linha in linhas]

    _TABELA_OPORTUNIDADES(
        key=key,
        data={"columns": colunas, "rows": linhas_limpas, "sortCol": sort_col, "sortDir": sort_dir},
        default={"sortCol": sort_col, "sortDir": sort_dir},
        on_sortCol_change=lambda: None,
        on_sortDir_change=lambda: None,
    )
