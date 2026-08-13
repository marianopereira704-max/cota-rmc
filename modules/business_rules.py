"""
Regras de negócio sobre a tabela consolidada loja x produto (RMC).

Todas as funções recebem os parâmetros de negócio (dias de cobertura, margem
de segurança) explicitamente — nunca lidos de uma constante interna. Quem
decide o valor efetivo é a camada de UI (Configurações), com os defaults
vindos de `config.BusinessDefaults` apenas como valor inicial de formulário.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

STATUS_OPORTUNIDADE = "Oportunidade"
STATUS_RUPTURA = "Risco de Ruptura"
STATUS_NORMAL = "Normal"

# Estados de oportunidade de venda — usados só na página "Oportunidades de
# Venda", conceito separado de STATUS_OPORTUNIDADE/STATUS_RUPTURA/STATUS_NORMAL
# acima (aqueles continuam existindo, usados no Pedido Sugerido e no
# Dashboard; risco de ruptura é sobre estoque baixo, não sobre preço, e não
# aparece nesta página nova).
ESTADO_NAO_COMPRA = "Não compra"
ESTADO_COMPRA_MAIS_CARO = "Compra mais caro"
ESTADO_JA_OTIMIZADO = "Já otimizado"


def montar_tabela_principal(
    lojas_df: pd.DataFrame,
    rmc_resolvido: pd.DataFrame,
    base_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    lojas_df: saída de load_lojas_movimento (agregado por uf, cnpj, ean, laboratorio_loja)
    rmc_resolvido: MatchingResult.rmc_resolvido (já com produto_unificado)
    base_df: BASE_COMPLETA carregada (para expandir variantes de EAN por produto)

    Devolve uma linha por (uf, cnpj, produto_unificado, laboratorio_loja) —
    granularidade do lado da LOJA, independente de quantos fornecedores RMC
    precificam aquele produto. Inclusive lojas sem nenhuma movimentação
    daquele produto (venda=0, estoque=0), que é a base do status
    "Oportunidade". O preço/desvio de cada fornecedor é anexado depois via
    `anexar_precos_fornecedores()` — não faz parte da grade de linhas, pra
    não duplicar Oportunidade/Ruptura uma vez por fornecedor carregado.
    """
    from modules.matching_engine import variantes_ean_por_produto

    produtos_rmc = rmc_resolvido["produto_unificado"].unique().tolist()
    variantes = variantes_ean_por_produto(base_df, produtos_rmc)  # [ean, produto_unificado]

    # Junta a movimentação da loja (por ean) com o produto_unificado ao qual aquele ean pertence
    mov_com_produto = lojas_df.merge(variantes, on="ean", how="inner")

    # Agrega por loja + produto_unificado + laboratorio_loja (várias variantes
    # de EAN podem cair no mesmo produto; o mesmo produto pode ter sido
    # comprado de mais de um laboratório da loja, cada um em sua própria linha)
    mov_agregada = mov_com_produto.groupby(
        ["uf", "cnpj", "produto_unificado", "laboratorio_loja"], as_index=False
    ).agg(
        faturamento=("faturamento", "sum"),
        custo_total=("custo_total", "sum"),
        quantidade_venda=("quantidade_venda", "sum"),
        estoque=("estoque", "sum"),
    )

    # Universo de lojas conhecido = todo cnpj que aparece em QUALQUER movimentação
    # (não restrito aos produtos RMC) — assim uma loja que não vende nenhum item
    # RMC ainda aparece como "Oportunidade" em todos eles.
    universo_lojas = lojas_df[["uf", "cnpj"]].drop_duplicates()

    # Cross join lojas x produtos RMC resolvidos (um por produto, SEM
    # fornecedor — isso é o que evita duplicar a linha de Oportunidade uma
    # vez por fornecedor quando há mais de uma tabela RMC carregada)
    produtos_unicos = rmc_resolvido[["produto_unificado"]].drop_duplicates()
    universo_lojas = universo_lojas.copy()
    universo_lojas["_key"] = 1
    produtos_unicos = produtos_unicos.copy()
    produtos_unicos["_key"] = 1
    esqueleto = universo_lojas.merge(produtos_unicos, on="_key").drop(columns="_key")

    tabela = esqueleto.merge(
        mov_agregada,
        on=["uf", "cnpj", "produto_unificado"],
        how="left",
    )

    for col in ["faturamento", "custo_total", "quantidade_venda", "estoque"]:
        tabela[col] = tabela[col].fillna(0.0)

    tabela["preco_compra_unitario"] = (tabela["custo_total"] / tabela["quantidade_venda"]).where(
        tabela["quantidade_venda"] > 0, other=pd.NA
    )

    tabela = tabela.rename(columns={
        "produto_unificado": "produto",
        "quantidade_venda": "venda_loja",
        "estoque": "estoque_loja",
    })

    colunas_finais = [
        "uf", "cnpj", "produto", "laboratorio_loja", "venda_loja", "estoque_loja", "preco_compra_unitario",
    ]
    return tabela[colunas_finais]


def anexar_precos_fornecedores(
    tabela: pd.DataFrame,
    rmc_resolvido: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, dict[str, str]]]:
    """
    Anexa, pra cada laboratorio_rmc (fornecedor) presente em `rmc_resolvido`,
    duas colunas na tabela: o preço de referência daquele fornecedor pro
    produto da linha, e o desvio percentual do preço de compra da loja em
    relação a ele.

    Desvio % = (preco_compra_unitario - preco_do_fornecedor) / preco_do_fornecedor * 100.
    Fica NaN (nunca 0, nunca texto de erro) se preco_compra_unitario estiver
    vazio (loja não vende o produto) OU o fornecedor não tiver preço pra
    aquele produto específico — a aritmética com NaN já propaga isso sozinha.

    Devolve (tabela_enriquecida, col_map), onde col_map mapeia
    {nome_do_fornecedor: {"preco": <nome_real_da_coluna>, "desvio": <nome_real_da_coluna>}}.
    O nome do fornecedor pode conter qualquer caractere (é texto livre digitado
    no upload) — por isso os nomes de coluna reais nunca devem ser
    reconstruídos por parsing; sempre usar col_map.
    """
    precos_wide = rmc_resolvido.pivot_table(
        index="produto_unificado", columns="laboratorio_rmc", values="preco_unitario_rmc", aggfunc="first",
    )

    tabela = tabela.copy()
    col_map: dict[str, dict[str, str]] = {}
    for posicao, fornecedor in enumerate(precos_wide.columns):
        preco_col = f"_preco_fornecedor_{posicao}"
        desvio_col = f"_desvio_fornecedor_{posicao}"
        tabela[preco_col] = tabela["produto"].map(precos_wide[fornecedor])
        tabela[desvio_col] = (
            (tabela["preco_compra_unitario"] - tabela[preco_col]) / tabela[preco_col] * 100
        )
        col_map[fornecedor] = {"preco": preco_col, "desvio": desvio_col}

    return tabela, col_map


def classificar_oportunidade_venda(
    tabela: pd.DataFrame,
    col_map: dict[str, dict[str, str]],
) -> pd.DataFrame:
    """
    Classifica cada linha em 1 de 3 estados de oportunidade de venda (página
    "Oportunidades de Venda" — conceito de negócio separado do status
    Oportunidade/Risco de Ruptura/Normal usado no Pedido Sugerido/Dashboard):

      - ESTADO_NAO_COMPRA: venda_loja == 0 E estoque_loja == 0 (loja não
        trabalha o item — mesma regra que já existia como "Oportunidade",
        só renomeada pro contexto desta página).
      - ESTADO_COMPRA_MAIS_CARO: loja compra o produto pagando MAIS que o
        melhor (menor) preço disponível entre os fornecedores RMC
        carregados — a oportunidade de conversão real desta página.
      - ESTADO_JA_OTIMIZADO: loja compra igual ou mais barato que o melhor
        preço disponível.

    Com mais de um fornecedor carregado, compara sempre contra o MELHOR
    (menor) preço entre eles pra aquele produto — é a maior economia que a
    Rede poderia oferecer naquele produto.

    Adiciona as colunas:
      - melhor_preco_fornecedor: menor preço de fornecedor disponível pra
        aquele produto (NaN se nenhum fornecedor tiver preço pra ele).
      - estado_venda: um dos 3 estados acima.
      - desvio_pct_melhor: desvio % do preço de compra em relação ao melhor
        preço (NaN se não houver preço de compra ou de fornecedor pra
        comparar — nunca 0 fingindo comparação, nunca erro).
      - economia_potencial: em R$, arredondada pra BAIXO (floor). Só
        preenchida (não-NaN) quando estado_venda == ESTADO_COMPRA_MAIS_CARO;
        nas outras linhas fica NaN (a tarefa pede o valor só pra essas
        linhas, não 0 disfarçando ausência de oportunidade).
    """
    df = tabela.copy()

    precos_fornecedores_cols = [c["preco"] for c in col_map.values()]
    if precos_fornecedores_cols:
        df["melhor_preco_fornecedor"] = df[precos_fornecedores_cols].min(axis=1, skipna=True)
    else:
        df["melhor_preco_fornecedor"] = pd.NA

    sem_movimento = (df["venda_loja"] == 0) & (df["estoque_loja"] == 0)
    tem_comparacao = df["preco_compra_unitario"].notna() & df["melhor_preco_fornecedor"].notna()

    compra_mais_caro = (
        ~sem_movimento
        & tem_comparacao
        & (df["preco_compra_unitario"] > df["melhor_preco_fornecedor"])
    )

    df["estado_venda"] = ESTADO_JA_OTIMIZADO
    df.loc[compra_mais_caro, "estado_venda"] = ESTADO_COMPRA_MAIS_CARO
    df.loc[sem_movimento, "estado_venda"] = ESTADO_NAO_COMPRA

    df["desvio_pct_melhor"] = np.nan
    df.loc[tem_comparacao, "desvio_pct_melhor"] = (
        (df.loc[tem_comparacao, "preco_compra_unitario"] - df.loc[tem_comparacao, "melhor_preco_fornecedor"])
        / df.loc[tem_comparacao, "melhor_preco_fornecedor"] * 100
    )

    df["economia_potencial"] = np.nan
    economia_bruta = (
        (df.loc[compra_mais_caro, "preco_compra_unitario"] - df.loc[compra_mais_caro, "melhor_preco_fornecedor"])
        * df.loc[compra_mais_caro, "venda_loja"]
    )
    df.loc[compra_mais_caro, "economia_potencial"] = np.floor(economia_bruta)

    return df


def classificar_status(
    tabela: pd.DataFrame,
    dias_cobertura: int,
    margem_seguranca_ruptura: float,
) -> pd.DataFrame:
    """
    Adiciona a coluna `status`:
      - Oportunidade: venda_loja == 0 E estoque_loja == 0 (loja não trabalha o item — possível positivação)
      - Risco de Ruptura: loja vende o item, mas estoque_loja cobre menos que
        (demanda_diária * dias_cobertura * margem_seguranca_ruptura)
      - Normal: os demais casos

    demanda_diária é calculada a partir do período do snapshot carregado —
    quem informa quantos dias o snapshot representa é a camada de UI, pois
    isso depende do corte de datas escolhido no export (não é um dado
    presente no arquivo em si).
    Aqui a função recebe `venda_loja` já como quantidade total do período;
    ver `calcular_demanda_diaria` para a conversão explícita.
    """
    df = tabela.copy()

    sem_movimento = (df["venda_loja"] == 0) & (df["estoque_loja"] == 0)

    demanda_diaria = df["demanda_diaria"] if "demanda_diaria" in df.columns else None
    if demanda_diaria is None:
        raise ValueError(
            "Coluna 'demanda_diaria' ausente — rode calcular_demanda_diaria() antes de classificar_status()."
        )

    cobertura_minima = demanda_diaria * dias_cobertura * margem_seguranca_ruptura
    em_ruptura = (~sem_movimento) & (df["estoque_loja"] < cobertura_minima)

    df["status"] = STATUS_NORMAL
    df.loc[em_ruptura, "status"] = STATUS_RUPTURA
    df.loc[sem_movimento, "status"] = STATUS_OPORTUNIDADE
    return df


def calcular_demanda_diaria(tabela: pd.DataFrame, dias_periodo_snapshot: int) -> pd.DataFrame:
    """
    dias_periodo_snapshot: quantos dias o snapshot de movimentação carregado
    representa (ex: export de Mai+Jun+Jul = ~92 dias). Informado pelo usuário
    no momento do upload/config — não inferido do arquivo.
    """
    if dias_periodo_snapshot <= 0:
        raise ValueError("dias_periodo_snapshot precisa ser maior que zero.")
    df = tabela.copy()
    df["demanda_diaria"] = df["venda_loja"] / dias_periodo_snapshot
    return df


def calcular_pedido_sugerido(tabela: pd.DataFrame, dias_cobertura: int) -> pd.DataFrame:
    """
    Pedido sugerido = demanda_diária * dias_cobertura - estoque_loja, com piso em 0.
    Requer que `demanda_diaria` já exista (ver calcular_demanda_diaria).
    """
    if "demanda_diaria" not in tabela.columns:
        raise ValueError(
            "Coluna 'demanda_diaria' ausente — rode calcular_demanda_diaria() antes de calcular_pedido_sugerido()."
        )
    df = tabela.copy()
    necessidade = df["demanda_diaria"] * dias_cobertura - df["estoque_loja"]
    df["pedido_sugerido"] = necessidade.clip(lower=0).round().astype(int)
    return df
