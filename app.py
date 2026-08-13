from __future__ import annotations

import html

import streamlit as st
import pandas as pd

from config import load_config
from modules import auth, styles
from modules.data_loader import load_base_completa, load_rmc_table, load_lojas_movimento
from modules.matching_engine import (
    resolver_rmc_para_produto_unificado,
    montar_novo_alias,
    ALIAS_COLUMNS,
)
from modules.business_rules import (
    montar_tabela_principal,
    anexar_precos_fornecedores,
    classificar_oportunidade_venda,
    calcular_demanda_diaria,
    classificar_status,
    calcular_pedido_sugerido,
    STATUS_OPORTUNIDADE,
    STATUS_RUPTURA,
    STATUS_NORMAL,
    ESTADO_NAO_COMPRA,
    ESTADO_COMPRA_MAIS_CARO,
    ESTADO_JA_OTIMIZADO,
)
from modules.storage import SpacesClient, SpacesStorageError
from modules.oportunidades_table import ler_ordenacao_atual, montar_pill, renderizar_tabela

cfg = load_config()
st.set_page_config(page_title=cfg.app_name, layout="wide")

# instanciado aqui (topo do script, roda em toda página) de propósito — o
# CookieManager só consegue de fato gravar um valor pendente no navegador se
# for reinstanciado em reruns subsequentes; instanciar só dentro da tela de
# login perdia a escrita assim que o login autenticava e o app saía dali.
cookies = auth.get_cookies()
if not cookies.ready():
    st.stop()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
if not auth.is_authenticated():
    auth.render_login_screen(cfg.app_name, cookies)
    st.stop()

st.markdown(styles.inject_base_css(), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Storage (opcional — app funciona em modo local se Spaces não configurado)
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_storage_client() -> SpacesClient | None:
    try:
        return SpacesClient(cfg.spaces)
    except SpacesStorageError:
        return None


storage = get_storage_client()


# Leitura pesada de arquivo (em especial a movimentação das lojas, que pode
# ter centenas de milhares de linhas) precisa de cache — sem isso, o
# Streamlit reexecuta a leitura inteira do zero a cada interação (qualquer
# clique, inclusive trocar de seção no menu, dispara um rerun do script
# completo), o que travava o app por 1-2 minutos a cada clique com exports
# grandes. st.cache_data invalida sozinho quando o conteúdo do arquivo muda.
@st.cache_data(show_spinner="Lendo BASE_COMPLETA...")
def _load_base_completa_cached(file, schema):
    return load_base_completa(file, schema)


@st.cache_data(show_spinner="Lendo movimentação das lojas (pode levar 1-2 min na primeira leitura de exports grandes)...")
def _load_lojas_movimento_cached(file, schema):
    return load_lojas_movimento(file, schema)


def _load_aliases_df() -> pd.DataFrame:
    if storage is None:
        return pd.DataFrame(columns=ALIAS_COLUMNS)
    return storage.read_dataframe_json(cfg.key_alias_table, ALIAS_COLUMNS)


def _save_aliases_df(df: pd.DataFrame) -> None:
    if storage is not None:
        storage.write_dataframe_json(cfg.key_alias_table, df)


def _save_pending_snapshot(df: pd.DataFrame) -> None:
    if storage is not None:
        cols = ["ean", "familia", "produto_rmc", "laboratorio_rmc"]
        storage.write_dataframe_json(cfg.key_pending_table, df[cols] if len(df) else df)


def _load_pending_snapshot() -> pd.DataFrame:
    if storage is None:
        return pd.DataFrame()
    return storage.read_dataframe_json(cfg.key_pending_table, ["ean", "familia", "produto_rmc", "laboratorio_rmc"])


# ---------------------------------------------------------------------------
# Estado de sessão
# ---------------------------------------------------------------------------
ss = st.session_state
ss.setdefault("base_df", None)
ss.setdefault("rmc_dfs", {})       # {laboratorio: df}
ss.setdefault("lojas_df", None)
ss.setdefault("aliases_df", _load_aliases_df())
ss.setdefault("dias_cobertura", cfg.business.dias_cobertura_padrao)
ss.setdefault("margem_seguranca", cfg.business.margem_seguranca_ruptura)
ss.setdefault("dias_periodo_snapshot", 30)
ss.setdefault("opv_estados_ativos", {ESTADO_NAO_COMPRA, ESTADO_COMPRA_MAIS_CARO, ESTADO_JA_OTIMIZADO})
ss.setdefault("opv_pagina", 1)
ss.setdefault("opv_pagina_ranking", 1)
ss.setdefault("opv_ranking_expandido", set())


def _recompute_pipeline():
    """
    Roda o matching (RMC -> produto unificado), monta `ss['tabela_final']`
    (grão loja x produto x laboratório da loja) e anexa preço/desvio de cada
    fornecedor RMC carregado — chamado incondicionalmente a cada rerun,
    independente de qual seção está ativa no menu lateral.

    Isso preserva o comportamento de quando a navegação era por st.tabs: lá,
    todo bloco de aba rodava a cada rerun, então mudar um parâmetro na aba
    Configurações recalculava a tabela principal na hora, mesmo sem visitar
    a aba Dados de novo. Com st.navigation, só a função da página ativa
    executa — sem isso aqui rodando fora das páginas, o resultado ficaria
    desatualizado ao trocar de seção sem passar por Dados.
    """
    pronto = ss["base_df"] is not None and ss["rmc_dfs"] and ss["lojas_df"] is not None
    if not pronto:
        return None

    rmc_concat = pd.concat(ss["rmc_dfs"].values(), ignore_index=True)
    match = resolver_rmc_para_produto_unificado(rmc_concat, ss["base_df"], ss["aliases_df"])
    _save_pending_snapshot(match.pendencias)

    tabela = montar_tabela_principal(ss["lojas_df"], match.rmc_resolvido, ss["base_df"])
    tabela, col_map = anexar_precos_fornecedores(tabela, match.rmc_resolvido)
    tabela = classificar_oportunidade_venda(tabela, col_map)
    tabela = calcular_demanda_diaria(tabela, ss["dias_periodo_snapshot"])
    tabela = classificar_status(tabela, ss["dias_cobertura"], ss["margem_seguranca"])
    tabela = calcular_pedido_sugerido(tabela, ss["dias_cobertura"])
    ss["tabela_final"] = tabela
    ss["fornecedores_col_map"] = col_map

    return match


def _filtros_tabela(df: pd.DataFrame, key_prefix: str) -> pd.DataFrame:
    """UF continua sendo filtro (não aparece mais como coluna na Tabela
    Principal, mas os dados de todas as UFs continuam lá por baixo)."""
    col1, col2, col3 = st.columns(3)
    ufs = ["Todos"] + sorted(df["uf"].dropna().unique().tolist())
    uf_sel = col1.selectbox("UF", ufs, key=f"{key_prefix}_uf")
    cnpjs = ["Todos"] + sorted(df["cnpj"].dropna().unique().tolist())
    cnpj_sel = col2.selectbox("CNPJ", cnpjs, key=f"{key_prefix}_cnpj")
    produtos = ["Todos"] + sorted(df["produto"].dropna().unique().tolist())
    produto_sel = col3.selectbox("Produto", produtos, key=f"{key_prefix}_produto")

    out = df
    if uf_sel != "Todos":
        out = out[out["uf"] == uf_sel]
    if cnpj_sel != "Todos":
        out = out[out["cnpj"] == cnpj_sel]
    if produto_sel != "Todos":
        out = out[out["produto"] == produto_sel]
    return out


# ---------------------------------------------------------------------------
# Seção: Configurações
# ---------------------------------------------------------------------------
def pagina_configuracoes():
    st.subheader("Parâmetros de cálculo")
    st.caption(
        "Esses valores controlam Risco de Ruptura e Pedido Sugerido em todo o app. "
        "Nada aqui é fixo no código — mude à vontade."
    )
    c1, c2 = st.columns(2)
    with c1:
        ss["dias_cobertura"] = st.number_input(
            "Pedir para quantos dias?",
            min_value=cfg.business.dias_cobertura_min,
            max_value=cfg.business.dias_cobertura_max,
            value=ss["dias_cobertura"],
            help="Usado no cálculo de Pedido Sugerido e no limiar de Risco de Ruptura.",
        )
        ss["dias_periodo_snapshot"] = st.number_input(
            "Quantos dias o snapshot de movimentação carregado representa?",
            min_value=1,
            value=ss["dias_periodo_snapshot"],
            help=(
                "Ex.: se o export do GPS Farma cobre maio+junho+julho, informe ~92. "
                "Isso não vem do arquivo — precisa ser informado, pois define a demanda diária."
            ),
        )
    with c2:
        ss["margem_seguranca"] = st.slider(
            "Margem de segurança para Risco de Ruptura",
            min_value=0.5, max_value=1.0, value=float(ss["margem_seguranca"]), step=0.01,
            help="Estoque abaixo de (demanda diária × dias × margem) dispara o alerta de ruptura.",
        )
        st.metric("Cobertura mínima de segurança", f"{ss['margem_seguranca']*100:.0f}%")


# ---------------------------------------------------------------------------
# Seção: Dados (upload + matching)
# ---------------------------------------------------------------------------
def pagina_dados():
    # controle de acesso de verdade, não só ocultar do menu — st.navigation
    # gera uma URL própria por página (ex: /pagina_dados), então quem souber
    # a URL pode tentar acessar direto mesmo sem o item aparecer no menu.
    if auth.current_profile() != auth.PERFIL_CONSULTOR:
        st.error("Esta seção não está disponível para o seu perfil.", icon="🚫")
        return

    st.subheader("1. Base unificada de EAN (genéricos)")
    base_file = st.file_uploader("BASE_COMPLETA.xlsx", type=["xlsx"], key="up_base")
    if base_file is not None:
        try:
            df, report = _load_base_completa_cached(base_file, cfg.schema)
            ss["base_df"] = df
            st.success(report.resumo)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Erro ao ler BASE_COMPLETA: {exc}")

    st.subheader("2. Tabela(s) de preço RMC — uma por laboratório")
    with st.form("form_rmc_upload", clear_on_submit=True):
        rmc_lab_name = st.text_input("Nome do laboratório desta tabela")
        rmc_file = st.file_uploader("Arquivo da tabela RMC", type=["xlsx"], key="up_rmc")
        submitted = st.form_submit_button("Adicionar tabela RMC")
        if submitted:
            if not rmc_lab_name.strip():
                st.error("Informe o nome do laboratório.")
            elif rmc_file is None:
                st.error("Selecione o arquivo.")
            else:
                try:
                    df, report = load_rmc_table(rmc_file, rmc_lab_name.strip(), cfg.schema)
                    ss["rmc_dfs"][rmc_lab_name.strip()] = df
                    st.success(report.resumo)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Erro ao ler tabela RMC: {exc}")

    if ss["rmc_dfs"]:
        st.caption(f"Laboratórios RMC carregados: {', '.join(ss['rmc_dfs'].keys())}")
        remover = st.selectbox("Remover laboratório", ["—"] + list(ss["rmc_dfs"].keys()))
        if remover != "—" and st.button("Remover"):
            del ss["rmc_dfs"][remover]
            st.rerun()

    st.subheader("3. Movimentação das lojas (export GPS Farma)")
    lojas_file = st.file_uploader("Export de movimentação por CNPJ", type=["xlsx"], key="up_lojas")
    if lojas_file is not None:
        try:
            df, report = _load_lojas_movimento_cached(lojas_file, cfg.schema)
            ss["lojas_df"] = df
            st.success(report.resumo)
            with st.expander("Detalhe do que foi descartado na limpeza"):
                st.json(report.motivos_descarte)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Erro ao ler movimentação das lojas: {exc}")

    st.divider()

    pronto = ss["base_df"] is not None and ss["rmc_dfs"] and ss["lojas_df"] is not None
    if not pronto:
        st.info("Carregue os 3 tipos de arquivo acima para rodar o matching.")
    else:
        # recalcula aqui (não reaproveita o resultado do topo do script): se
        # o upload que acabou de completar 'pronto' foi processado acima,
        # nesta mesma execução, o cálculo do topo do script ainda é o de
        # ANTES desse upload — chamar de novo aqui, depois do processamento
        # dos uploads, garante que match reflita o estado já atualizado.
        match = _recompute_pipeline()

        st.subheader("Cobertura do matching")
        c1, c2, c3 = st.columns(3)
        c1.metric("Cobertura", f"{match.cobertura_pct:.1f}%")
        c2.metric("Resolvidos", len(match.rmc_resolvido))
        c3.metric("Pendentes", len(match.pendencias))

        if match.tem_pendencias:
            st.warning(
                f"{len(match.pendencias)} produto(s) da tabela RMC sem correspondência confirmada. "
                "Eles ficam **inativos** (fora de qualquer cálculo/tabela) até você confirmar abaixo.",
                icon="⚠️",
            )
            with st.expander("Resolver pendências manualmente", expanded=True):
                produtos_disponiveis = sorted(ss["base_df"]["produto_unificado"].unique().tolist())
                for idx, row in match.pendencias.reset_index(drop=True).iterrows():
                    st.markdown(f"**{row['produto_rmc']}** — EAN `{row['ean']}` — {row['laboratorio_rmc']}")
                    col_sel, col_btn = st.columns([3, 1])
                    escolha = col_sel.selectbox(
                        "Produto unificado correspondente",
                        ["— selecione —"] + produtos_disponiveis,
                        key=f"pend_{row['ean']}_{row['laboratorio_rmc']}",
                        label_visibility="collapsed",
                    )
                    if col_btn.button("Confirmar", key=f"btn_{row['ean']}_{row['laboratorio_rmc']}"):
                        if escolha == "— selecione —":
                            st.error("Selecione um produto antes de confirmar.")
                        else:
                            novo = montar_novo_alias(
                                row["ean"], row["laboratorio_rmc"], escolha, auth.current_profile() or "desconhecido"
                            )
                            ss["aliases_df"] = pd.concat(
                                [ss["aliases_df"], pd.DataFrame([novo])], ignore_index=True
                            )
                            _save_aliases_df(ss["aliases_df"])
                            st.rerun()

        st.success("Tabela principal recalculada. Veja nas próximas seções.")


# ---------------------------------------------------------------------------
# Seção: Oportunidades de Venda
# ---------------------------------------------------------------------------
# Tamanho de página da tabela HTML/CSS customizada (modules/oportunidades_table.py).
# Diferente da versão anterior (pandas Styler, limitada a ~262 mil células),
# este componente não tem esse teto — mas ainda pagina de propósito: rolagem
# livre por dezenas de milhares de linhas exigiria reimplementar
# virtualização de linhas em JS, e a decisão (registrada na conversa que
# aprovou essa abordagem) foi manter paginação pra não introduzir essa
# complexidade extra agora.
TAMANHO_PAGINA_TABELA = 150

# Ranking de lojas: também paginado (mesmo motivo — evita renderizar
# centenas de linhas nativas do Streamlit, cada uma com um botão de
# exibir/ocultar, de uma vez só).
TAMANHO_PAGINA_RANKING = 20

OPV_PAGE_WRAP_KEY = "opv_page_wrap"

ESTADOS_ORDEM = [ESTADO_NAO_COMPRA, ESTADO_COMPRA_MAIS_CARO, ESTADO_JA_OTIMIZADO]
ESTADOS_SLUG = {
    ESTADO_NAO_COMPRA: "nao-compra",
    ESTADO_COMPRA_MAIS_CARO: "compra-mais-caro",
    ESTADO_JA_OTIMIZADO: "ja-otimizado",
}


def _fmt_reais_inteiro(valor: float) -> str:
    """R$ formatado pt-BR sem casas decimais (economia_potencial já vem
    arredondada pra baixo em business_rules) — ex: 1408306 -> 'R$ 1.408.306'."""
    return f"R$ {valor:,.0f}".replace(",", ".")


def _cor_estado_venda(estado: str) -> dict[str, str]:
    if estado == ESTADO_COMPRA_MAIS_CARO:
        return styles.STATUS_COLORS["confirmado"]  # verde — é uma boa notícia, não urgência
    if estado == ESTADO_JA_OTIMIZADO:
        return styles.STATUS_COLORS["neutro"]  # cinza — mesma pílula, sem chamar atenção
    return styles.BUSINESS_STATUS_STYLE[STATUS_OPORTUNIDADE]  # mesmo par que "Oportunidade" já usava


def _renderizar_cards_estado(contagens: dict[str, int]) -> None:
    """3 cards clicáveis (toggle) que ligam/desligam cada estado no filtro da
    tabela abaixo — estado ativo/inativo persistido em
    ss['opv_estados_ativos'] (um set, sobrevive a reruns normalmente)."""
    cols = st.columns(3)
    for col, estado in zip(cols, ESTADOS_ORDEM):
        slug = ESTADOS_SLUG[estado]
        ativo = estado in ss["opv_estados_ativos"]
        par = _cor_estado_venda(estado)
        cor_fundo = par["bg"] if ativo else "#FFFFFF"
        cor_texto = par["text"] if ativo else styles.TEXT_MUTED
        cor_borda = par["text"] if ativo else styles.BORDER
        col.markdown(
            f"""
            <style>
            div[class*="st-key-opv-card-{slug}"] button {{
                background: {cor_fundo} !important;
                color: {cor_texto} !important;
                border: 1.5px solid {cor_borda} !important;
                font-weight: 700 !important;
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )
        with col.container(key=f"opv-card-{slug}"):
            clicado = st.button(
                f"{contagens.get(estado, 0)} · {estado}",
                key=f"opv-card-btn-{slug}",
                width="stretch",
            )
            if clicado:
                if ativo:
                    ss["opv_estados_ativos"].discard(estado)
                else:
                    ss["opv_estados_ativos"].add(estado)
                st.rerun()


def _calcular_pagina(*, total_itens: int, tamanho_pagina: int, pagina_key: str) -> tuple[int, int, int]:
    """
    Calcula (e reclampa, se o total encolheu por causa de um filtro) a página
    atual — sem renderizar nada. Retorna (inicio, fim, total_paginas); quem
    chama fatia o DataFrame com `df.iloc[inicio:fim]` e, depois de desenhar o
    conteúdo, chama `_renderizar_rodape_paginacao` — a navegação fica no
    rodapé do card, não no topo.
    """
    total_paginas = max(1, -(-total_itens // tamanho_pagina))
    if pagina_key not in ss or ss[pagina_key] > total_paginas:
        ss[pagina_key] = 1
    pagina_atual = ss[pagina_key]
    inicio = (pagina_atual - 1) * tamanho_pagina
    fim = inicio + tamanho_pagina
    return inicio, fim, total_paginas


def _renderizar_rodape_paginacao(
    *,
    total_itens: int,
    inicio: int,
    fim: int,
    total_paginas: int,
    pagina_key: str,
    rotulo_singular: str,
    rotulo_plural: str,
) -> None:
    """
    Rodapé do card: contagem de linhas + links discretos ("‹ Página
    anterior" / "Próxima página ›", botões type="tertiary" — sem aparência de
    botão, sem campo numérico "Página (de N)"). Chamar DEPOIS do conteúdo da
    página atual, como rodapé natural do card.
    """
    pagina_atual = ss[pagina_key]
    rotulo = rotulo_singular if total_itens == 1 else rotulo_plural
    col_caption, col_prev, col_next = st.columns([5, 1, 1])
    col_caption.caption(f"{total_itens} {rotulo} no filtro atual · mostrando {inicio + 1}–{min(fim, total_itens)}")
    with col_prev:
        if st.button("‹ Página anterior", key=f"{pagina_key}_prev", type="tertiary", disabled=(pagina_atual == 1)):
            ss[pagina_key] = pagina_atual - 1
            st.rerun()
    with col_next:
        if st.button(
            "Próxima página ›", key=f"{pagina_key}_next", type="tertiary", disabled=(pagina_atual == total_paginas)
        ):
            ss[pagina_key] = pagina_atual + 1
            st.rerun()


def _renderizar_ranking_lojas(caros_no_filtro: pd.DataFrame) -> None:
    ranking = (
        caros_no_filtro.groupby("cnpj", as_index=False)
        .agg(
            economia_potencial_total=("economia_potencial", "sum"),
            qtd_produtos=("produto", "count"),
        )
        .sort_values("economia_potencial_total", ascending=False)
        .reset_index(drop=True)
    )

    with st.expander(f"Ranking de lojas por economia potencial ({len(ranking)} loja(s))", expanded=True):
        inicio, fim, total_paginas = _calcular_pagina(
            total_itens=len(ranking), tamanho_pagina=TAMANHO_PAGINA_RANKING, pagina_key="opv_pagina_ranking",
        )
        pagina_ranking = ranking.iloc[inicio:fim]

        col_h1, col_h2, col_h3, col_h4 = st.columns([3, 2, 2, 1])
        col_h1.markdown("**CNPJ**")
        col_h2.markdown("**Economia potencial total**")
        col_h3.markdown("**Produtos com oportunidade**")

        for i, row in enumerate(pagina_ranking.itertuples(index=False)):
            cnpj_loja = row.cnpj
            expandido = cnpj_loja in ss["opv_ranking_expandido"]
            with st.container(key=f"opv-rank-row-{i}"):
                c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
                c1.write(cnpj_loja)
                c2.write(_fmt_reais_inteiro(row.economia_potencial_total))
                # neutro de propósito — é só uma contagem, não um sinal de
                # bom/ruim, então não usa nenhum par de cor semântico.
                c3.markdown(
                    f'<span style="color:{styles.TEXT_MUTED};font-weight:600;">{int(row.qtd_produtos)}</span>',
                    unsafe_allow_html=True,
                )
                with c4:
                    if st.button(
                        "▾" if expandido else "▸",
                        key=f"opv-rank-toggle-{cnpj_loja}",
                        type="tertiary",
                    ):
                        if expandido:
                            ss["opv_ranking_expandido"].discard(cnpj_loja)
                        else:
                            ss["opv_ranking_expandido"].add(cnpj_loja)
                        st.rerun()

                if expandido:
                    produtos_loja = caros_no_filtro.loc[
                        caros_no_filtro["cnpj"] == cnpj_loja, ["produto", "economia_potencial"]
                    ].sort_values("economia_potencial", ascending=False)
                    linhas_html = "".join(
                        '<div class="opv-rank-produto">'
                        f'<span class="opv-rank-nome">{html.escape(str(produto))}</span>'
                        f'<span class="opv-rank-economia">{_fmt_reais_inteiro(economia)}</span>'
                        "</div>"
                        for produto, economia in zip(produtos_loja["produto"], produtos_loja["economia_potencial"])
                    )
                    st.markdown(f'<div class="opv-rank-sublist">{linhas_html}</div>', unsafe_allow_html=True)

        _renderizar_rodape_paginacao(
            total_itens=len(ranking),
            inicio=inicio,
            fim=fim,
            total_paginas=total_paginas,
            pagina_key="opv_pagina_ranking",
            rotulo_singular="loja",
            rotulo_plural="loja(s)",
        )


def pagina_oportunidades_venda():
    if "tabela_final" not in ss:
        st.info("Carregue os dados na seção **Dados** primeiro.")
        return

    tabela_final = ss["tabela_final"]
    col_map: dict[str, dict[str, str]] = ss.get("fornecedores_col_map", {})
    fornecedores = list(col_map.keys())

    if not fornecedores:
        st.info("Nenhum fornecedor RMC carregado ainda.")
        return

    st.markdown(styles.page_max_width_css(OPV_PAGE_WRAP_KEY), unsafe_allow_html=True)
    with st.container(key=OPV_PAGE_WRAP_KEY):
        # --- card de economia total: soma na BASE INTEIRA, sem nenhum filtro
        # desta página — é o número "manchete", pra levar numa reunião. ---
        economia_total = tabela_final.loc[
            tabela_final["estado_venda"] == ESTADO_COMPRA_MAIS_CARO, "economia_potencial"
        ].sum()
        qtd_oportunidades_total = int((tabela_final["estado_venda"] == ESTADO_COMPRA_MAIS_CARO).sum())
        st.markdown(
            styles.headline_card_html(
                "Economia potencial identificada",
                _fmt_reais_inteiro(economia_total),
                f"{qtd_oportunidades_total} produto(s) sendo comprados mais caro do que no fornecedor",
            ),
            unsafe_allow_html=True,
        )

        # --- cards de status: contagem sobre a base inteira (não sobre os
        # filtros de UF/CNPJ/Produto abaixo), pra sempre refletir o total
        # real. Aparência inalterada — só herda a largura do wrapper acima. ---
        contagens = tabela_final["estado_venda"].value_counts().to_dict()
        _renderizar_cards_estado(contagens)

        st.divider()

        # filtros de UF/CNPJ/Produto — chamado UMA VEZ só (renderiza os
        # selectboxes); o resultado é reaproveitado tanto pro ranking quanto
        # pra tabela principal abaixo.
        df_filtrado = _filtros_tabela(tabela_final, "opv")

        # --- ranking por loja: soma de economia_potencial (só "Compra mais
        # caro") por CNPJ, dentro do filtro de UF/CNPJ/Produto acima — mas
        # não do toggle dos cards de estado, porque o ranking é sempre sobre
        # a oportunidade de conversão em si, faz sentido mesmo com o card
        # "Compra mais caro" desligado no momento. ---
        caros_no_filtro = df_filtrado[df_filtrado["estado_venda"] == ESTADO_COMPRA_MAIS_CARO]
        if len(caros_no_filtro):
            _renderizar_ranking_lojas(caros_no_filtro)

        # tabela principal: filtro de UF/CNPJ/Produto + toggle dos cards de estado
        df = df_filtrado[df_filtrado["estado_venda"].isin(ss["opv_estados_ativos"])]
        if df.empty:
            st.info("Nenhuma linha para os filtros selecionados.")
            return

        sort_col, sort_dir = ler_ordenacao_atual("opv_tabela", "economia_potencial", "desc")
        df = df.sort_values(sort_col, ascending=(sort_dir == "asc"), na_position="last")

        # dentro de um card com borda (st.expander — mesmo componente usado
        # no ranking de lojas acima, pra garantir aparência idêntica: mesma
        # borda, mesmo border-radius, sem inventar uma segunda variação
        # visual de "card").
        with st.expander(f"Produtos ({len(df)} linha(s))", expanded=True):
            inicio, fim, total_paginas = _calcular_pagina(
                total_itens=len(df), tamanho_pagina=TAMANHO_PAGINA_TABELA, pagina_key="opv_pagina",
            )
            pagina_df = df.iloc[inicio:fim]

            colunas_tabela = [
                {"key": "produto", "label": "Produto", "type": "text", "sortable": True, "sticky": True},
                {"key": "cnpj", "label": "CNPJ", "type": "text", "sortable": True, "sticky": False},
                {"key": "laboratorio_loja", "label": "Laboratório", "type": "text", "sortable": True, "sticky": False},
                {"key": "venda_loja", "label": "Venda Loja", "type": "integer", "sortable": True, "sticky": False},
                {"key": "estoque_loja", "label": "Estoque Loja", "type": "integer", "sortable": True, "sticky": False},
                {
                    "key": "preco_compra_unitario", "label": "Preço atual", "type": "currency",
                    "sortable": True, "sticky": False,
                },
            ]
            for fornecedor in fornecedores:
                colunas_tabela.append({
                    "key": col_map[fornecedor]["preco"], "label": f"Preço {fornecedor}", "type": "currency",
                    "sortable": True, "sticky": False,
                })
            colunas_tabela += [
                {"key": "estado_venda", "label": "Estado", "type": "pill", "sortable": True, "sticky": False},
                {"key": "desvio_pct_melhor", "label": "Desvio %", "type": "percent", "sortable": True, "sticky": False},
                {
                    "key": "economia_potencial", "label": "Economia (R$)", "type": "currency",
                    "sortable": True, "sticky": False,
                },
            ]

            colunas_dados = (
                ["produto", "cnpj", "laboratorio_loja", "venda_loja", "estoque_loja", "preco_compra_unitario"]
                + [col_map[f]["preco"] for f in fornecedores]
                + ["estado_venda", "desvio_pct_melhor", "economia_potencial"]
            )
            linhas_tabela = pagina_df[colunas_dados].to_dict(orient="records")
            for linha in linhas_tabela:
                linha["estado_venda"] = montar_pill(linha["estado_venda"], _cor_estado_venda(linha["estado_venda"]))

            renderizar_tabela(colunas_tabela, linhas_tabela, sort_col, sort_dir, key="opv_tabela")

            _renderizar_rodape_paginacao(
                total_itens=len(df),
                inicio=inicio,
                fim=fim,
                total_paginas=total_paginas,
                pagina_key="opv_pagina",
                rotulo_singular="linha",
                rotulo_plural="linha(s)",
            )


# ---------------------------------------------------------------------------
# Seção: Pedido Sugerido
# ---------------------------------------------------------------------------
def pagina_pedido_sugerido():
    if "tabela_final" not in ss:
        st.info("Carregue os dados na seção **Dados** primeiro.")
    else:
        st.subheader(f"Pedido sugerido para {ss['dias_cobertura']} dia(s) de cobertura")
        df = _filtros_tabela(ss["tabela_final"], "pedido")
        df = df[df["pedido_sugerido"] > 0].sort_values("pedido_sugerido", ascending=False)

        colunas = ["uf", "cnpj", "produto", "estoque_loja", "demanda_diaria", "pedido_sugerido", "status"]
        st.dataframe(df[colunas], hide_index=True)
        st.caption(f"{len(df)} itens com sugestão de pedido > 0")


# ---------------------------------------------------------------------------
# Seção: Dashboard
# ---------------------------------------------------------------------------
def pagina_dashboard():
    if "tabela_final" not in ss:
        st.info("Carregue os dados na seção **Dados** primeiro.")
        return

    df = ss["tabela_final"]
    col_map: dict[str, dict[str, str]] = ss.get("fornecedores_col_map", {})
    st.caption(
        "Indicadores iniciais — sujeitos a revisão de prioridade/layout junto com você "
        "antes da versão final para o diretor."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Lojas na base", df["cnpj"].nunique())
    c2.metric("Produtos RMC ativos", df["produto"].nunique())
    oportunidades = (df["status"] == STATUS_OPORTUNIDADE).sum()
    c3.metric("Oportunidades (positivação)", oportunidades)
    rupturas = (df["status"] == STATUS_RUPTURA).sum()
    c4.metric("Itens em Risco de Ruptura", rupturas)

    # Desvio/economia agregados através de TODOS os fornecedores RMC
    # carregados — cada combinação (linha, fornecedor) com preço de compra e
    # preço do fornecedor vira um ponto comparável (generaliza o que antes
    # era um único "preco_rmc" pra N fornecedores).
    partes = []
    for fornecedor, cols in col_map.items():
        parte = df[["cnpj", "produto", "venda_loja", "preco_compra_unitario", cols["preco"]]].rename(
            columns={cols["preco"]: "preco_fornecedor"}
        )
        partes.append(parte)

    if partes:
        comparaveis = pd.concat(partes, ignore_index=True)
        comparaveis = comparaveis[
            comparaveis["preco_compra_unitario"].notna() & comparaveis["preco_fornecedor"].notna()
        ].copy()
        comparaveis["desvio_pct"] = (
            (comparaveis["preco_compra_unitario"] - comparaveis["preco_fornecedor"]) / comparaveis["preco_fornecedor"] * 100
        )
        comparaveis["economia_potencial"] = (
            (comparaveis["preco_compra_unitario"] - comparaveis["preco_fornecedor"]).clip(lower=0) * comparaveis["venda_loja"]
        )

        st.subheader("Desvio médio de preço (Compra vs fornecedores RMC)")
        st.metric("Desvio médio", f"{comparaveis['desvio_pct'].mean():.1f}%")
        st.metric("Economia potencial estimada (período)", f"R$ {comparaveis['economia_potencial'].sum():,.2f}")

        st.subheader("Top 10 lojas com maior desvio médio de preço")
        rank_lojas = (
            comparaveis.groupby("cnpj")["desvio_pct"].mean().sort_values(ascending=False).head(10)
        )
        st.bar_chart(rank_lojas)

        st.subheader("Top 10 produtos com maior economia potencial")
        rank_produtos = (
            comparaveis.groupby("produto")["economia_potencial"].sum().sort_values(ascending=False).head(10)
        )
        st.bar_chart(rank_produtos)


# ---------------------------------------------------------------------------
# Conteúdo comum a todas as seções (topo da área principal)
# ---------------------------------------------------------------------------
st.markdown(
    styles.header_html(cfg.app_name, "Comparativo de preço de compra das lojas x tabela RMC"),
    unsafe_allow_html=True,
)

if storage is None:
    st.info(
        "Storage do Spaces não configurado nesta sessão — funcionando apenas com dados "
        "em memória (perdidos ao fechar). Configure `.streamlit/secrets.toml` para persistir "
        "aliases confirmados entre sessões.",
        icon="ℹ️",
    )

# Alerta de pendências persistidas de sessões anteriores
pending_snapshot = _load_pending_snapshot()
if len(pending_snapshot) > 0 and "produtos_rmc_resolvidos" not in ss:
    st.warning(
        f"{styles.count_badge_html(len(pending_snapshot), alerta=True)} "
        f"produto(s) da tabela RMC ainda sem correspondência confirmada na base unificada "
        f"(de uma sessão anterior). Carregue os arquivos na seção **Dados** para resolver.",
        icon="⚠️",
    )

# Roda incondicionalmente (mesmo em páginas != Dados) só pelo efeito colateral
# de manter ss['tabela_final'] em dia; pagina_dados() chama de novo por conta
# própria depois de processar upload, então o retorno aqui não é usado.
_recompute_pipeline()

# ---------------------------------------------------------------------------
# Navegação (sidebar nativa do Streamlit)
# ---------------------------------------------------------------------------
# Seção Dados é exclusiva do perfil consultor — some do menu por completo pro
# diretor (não aparece nem desabilitada). pagina_dados() também se protege
# sozinha (ver guarda no topo da função) contra acesso direto pela URL.
eh_consultor = auth.current_profile() == auth.PERFIL_CONSULTOR

if eh_consultor:
    paginas = [
        st.Page(pagina_dados, title="Dados", icon="📥", default=True),
        st.Page(pagina_configuracoes, title="Configurações", icon="⚙️"),
        st.Page(pagina_oportunidades_venda, title="Oportunidades de Venda", icon="📋"),
        st.Page(pagina_pedido_sugerido, title="Pedido Sugerido", icon="🛒"),
        st.Page(pagina_dashboard, title="Dashboard", icon="📊"),
    ]
else:
    paginas = [
        st.Page(pagina_configuracoes, title="Configurações", icon="⚙️", default=True),
        st.Page(pagina_oportunidades_venda, title="Oportunidades de Venda", icon="📋"),
        st.Page(pagina_pedido_sugerido, title="Pedido Sugerido", icon="🛒"),
        st.Page(pagina_dashboard, title="Dashboard", icon="📊"),
    ]

pg = st.navigation(paginas)
pg.run()

auth.render_logout_sidebar()
