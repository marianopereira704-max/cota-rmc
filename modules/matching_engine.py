"""
Motor de matching — RMC é a âncora.

Fluxo:
  1. Para cada EAN de cada tabela RMC carregada, tenta resolver o
     `produto_unificado` correspondente via BASE_COMPLETA.
  2. O que não resolve direto entra em `aliases confirmados` (correção manual
     persistida) SE já houver uma correção salva anteriormente para aquele
     par (ean, laboratorio_rmc).
  3. O que continua sem resolução vira PENDÊNCIA — fica marcado como
     inativo (não participa de nenhum cálculo) até o usuário confirmar
     manualmente a qual produto unificado ele pertence.
  4. Uma vez resolvido o produto_unificado de cada item RMC, recupera-se
     TODAS as variantes de EAN daquele produto na BASE_COMPLETA — isso é o
     que permite casar a movimentação da loja mesmo que ela tenha comprado
     um EAN diferente do que está na tabela RMC, desde que ambos apontem
     para o mesmo produto_unificado.

Importante: aliases têm chave (ean, laboratorio_rmc) — não só ean — porque
o mesmo EAN pode, em tese, pertencer a laboratórios RMC diferentes com
contratos distintos ao longo do tempo.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


ALIAS_COLUMNS = ["ean", "laboratorio_rmc", "produto_unificado_confirmado", "confirmado_por", "confirmado_em"]


@dataclass
class MatchingResult:
    """
    rmc_resolvido: tabela RMC + produto_unificado já resolvido (direto ou via alias)
    pendencias: itens RMC sem produto_unificado resolvido — precisam de ação manual
    cobertura_pct: % dos itens RMC ativos (com EAN) que estão resolvidos
    """
    rmc_resolvido: pd.DataFrame
    pendencias: pd.DataFrame
    cobertura_pct: float

    @property
    def tem_pendencias(self) -> bool:
        return len(self.pendencias) > 0


def resolver_rmc_para_produto_unificado(
    rmc_df: pd.DataFrame,
    base_df: pd.DataFrame,
    aliases_df: pd.DataFrame | None = None,
) -> MatchingResult:
    """
    rmc_df: saída de load_rmc_table (pode ser concat de vários laboratórios)
    base_df: saída de load_base_completa
    aliases_df: tabela de correções manuais já confirmadas anteriormente
                (colunas = ALIAS_COLUMNS). None ou vazio = nenhuma ainda.
    """
    if aliases_df is None or len(aliases_df) == 0:
        aliases_df = pd.DataFrame(columns=ALIAS_COLUMNS)

    base_lookup = base_df.drop_duplicates("ean").set_index("ean")["produto_unificado"]

    rmc = rmc_df.copy()
    rmc["produto_unificado"] = rmc["ean"].map(base_lookup)

    # aplica aliases confirmados onde o match direto falhou
    sem_match = rmc["produto_unificado"].isna()
    if sem_match.any() and len(aliases_df) > 0:
        alias_lookup = aliases_df.set_index(["ean", "laboratorio_rmc"])["produto_unificado_confirmado"]
        chave = list(zip(rmc.loc[sem_match, "ean"], rmc.loc[sem_match, "laboratorio_rmc"]))
        resolved_via_alias = pd.Series(chave, index=rmc.loc[sem_match].index).map(
            lambda k: alias_lookup.get(k)
        )
        rmc.loc[sem_match, "produto_unificado"] = resolved_via_alias

    resolvidos = rmc[rmc["produto_unificado"].notna()].copy()
    pendencias = rmc[rmc["produto_unificado"].isna()].copy()
    pendencias = pendencias.drop(columns=["produto_unificado"], errors="ignore")

    total = len(rmc)
    cobertura = (len(resolvidos) / total * 100) if total else 100.0

    return MatchingResult(rmc_resolvido=resolvidos, pendencias=pendencias, cobertura_pct=cobertura)


def variantes_ean_por_produto(base_df: pd.DataFrame, produtos_unificados: list[str]) -> pd.DataFrame:
    """
    Dado um conjunto de produtos_unificados (os que vieram do RMC resolvido),
    devolve TODAS as linhas da BASE_COMPLETA que pertencem a esses produtos —
    ou seja, todo EAN-variante que uma loja poderia ter usado para o mesmo
    genérico.
    Saída: [ean, produto_unificado]
    """
    subset = base_df[base_df["produto_unificado"].isin(produtos_unificados)]
    return subset[["ean", "produto_unificado"]].drop_duplicates()


def montar_novo_alias(ean: str, laboratorio_rmc: str, produto_unificado_confirmado: str, confirmado_por: str) -> dict:
    import datetime as _dt
    return {
        "ean": ean,
        "laboratorio_rmc": laboratorio_rmc,
        "produto_unificado_confirmado": produto_unificado_confirmado,
        "confirmado_por": confirmado_por,
        "confirmado_em": _dt.datetime.now().isoformat(timespec="seconds"),
    }
