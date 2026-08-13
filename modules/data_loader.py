"""
Leitura e limpeza dos arquivos de origem:
  - BASE_COMPLETA (unificação de EAN de genéricos)
  - Tabela RMC (uma por laboratório)
  - Dados de movimentação das lojas (export GPS Farma, snapshot de um período)

Cada função devolve um DataFrame limpo + um relatório de qualidade (dict) —
o relatório existe para a UI poder mostrar ao usuário o que foi descartado
e por quê, em vez de silenciosamente sumir com linhas.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from config import SchemaConfig


def _norm_ean(series: pd.Series) -> pd.Series:
    """Normaliza EAN para string sem sufixo '.0' vindo de leitura como float."""
    return (
        series.dropna()
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
        .reindex(series.index)
    )


@dataclass
class LoadReport:
    fonte: str
    linhas_originais: int
    linhas_validas: int
    linhas_descartadas: int
    motivos_descarte: dict[str, int] = field(default_factory=dict)

    @property
    def resumo(self) -> str:
        return (
            f"{self.fonte}: {self.linhas_validas}/{self.linhas_originais} linhas válidas "
            f"({self.linhas_descartadas} descartadas)"
        )


def load_base_completa(file, schema: SchemaConfig) -> tuple[pd.DataFrame, LoadReport]:
    """
    Lê a planilha de unificação de EAN.
    Saída: colunas [ean, codigo_interno, produto_unificado]
    Linhas sem EAN são descartadas do matching (não têm como ser localizadas
    via código de barras) mas isso é reportado, nunca silencioso.
    """
    df = pd.read_excel(file)
    original = len(df)

    missing_cols = {schema.base_col_ean, schema.base_col_codigo_interno, schema.base_col_produto_unificado} - set(df.columns)
    if missing_cols:
        raise ValueError(f"BASE_COMPLETA: colunas esperadas não encontradas: {missing_cols}")

    df = df.rename(columns={
        schema.base_col_ean: "ean",
        schema.base_col_codigo_interno: "codigo_interno",
        schema.base_col_produto_unificado: "produto_unificado",
    })

    sem_ean = df["ean"].isna().sum()
    df["ean"] = _norm_ean(df["ean"])
    df_validos = df[df["ean"].notna()].copy()

    report = LoadReport(
        fonte="BASE_COMPLETA",
        linhas_originais=original,
        linhas_validas=len(df_validos),
        linhas_descartadas=original - len(df_validos),
        motivos_descarte={"sem_ean": int(sem_ean)},
    )
    return df_validos, report


def load_rmc_table(file, laboratorio: str, schema: SchemaConfig) -> tuple[pd.DataFrame, LoadReport]:
    """
    Lê uma tabela de preço RMC de UM laboratório.
    `laboratorio` é fornecido pelo usuário no momento do upload (não vem do
    arquivo em si) — é o que permite suportar múltiplos laboratórios sem
    depender do nome do arquivo.
    Saída: colunas [ean, familia, produto_rmc, preco_unitario_rmc, laboratorio_rmc]
    """
    df = pd.read_excel(file)
    original = len(df)

    required = {schema.rmc_col_ean, schema.rmc_col_produto, schema.rmc_col_preco_liquido}
    missing_cols = required - set(df.columns)
    if missing_cols:
        raise ValueError(f"Tabela RMC ({laboratorio}): colunas esperadas não encontradas: {missing_cols}")

    df = df.rename(columns={
        schema.rmc_col_familia: "familia",
        schema.rmc_col_ean: "ean",
        schema.rmc_col_produto: "produto_rmc",
        schema.rmc_col_preco_liquido: "preco_unitario_rmc",
    })

    sem_ean = df["ean"].isna().sum()
    df["ean"] = _norm_ean(df["ean"])
    df_validos = df[df["ean"].notna() & df["preco_unitario_rmc"].notna()].copy()
    df_validos["laboratorio_rmc"] = laboratorio

    cols = ["ean", "familia", "produto_rmc", "preco_unitario_rmc", "laboratorio_rmc"]
    df_validos = df_validos[[c for c in cols if c in df_validos.columns]]

    report = LoadReport(
        fonte=f"RMC · {laboratorio}",
        linhas_originais=original,
        linhas_validas=len(df_validos),
        linhas_descartadas=original - len(df_validos),
        motivos_descarte={"sem_ean_ou_preco": int(original - len(df_validos))},
    )
    return df_validos, report


def load_lojas_movimento(file, schema: SchemaConfig) -> tuple[pd.DataFrame, LoadReport]:
    """
    Lê o export GPS Farma de movimentação por CNPJ (snapshot de um período).
    Remove: linhas totalmente vazias, linha "Total" agregada, linhas de
    rodapé com texto de metadados de filtro/aviso de export.
    Agrega por (cnpj, ean): soma quantidade/estoque/faturamento e recalcula
    % CMV ponderado — necessário porque o mesmo cnpj+EAN pode aparecer em
    mais de uma linha com NomeProduto diferente (cadastro duplicado no GPS Farma).
    Saída: colunas [uf, cnpj, ean, laboratorio_loja, faturamento, custo_total,
                     quantidade_venda, estoque]
    """
    df = pd.read_excel(file)
    original = len(df)

    required = {
        schema.lojas_col_uf, schema.lojas_col_cnpj, schema.lojas_col_ean,
        schema.lojas_col_laboratorio, schema.lojas_col_faturamento,
        schema.lojas_col_pct_cmv, schema.lojas_col_quantidade, schema.lojas_col_estoque,
    }
    missing_cols = required - set(df.columns)
    if missing_cols:
        raise ValueError(f"Dados de loja: colunas esperadas não encontradas: {missing_cols}")

    df = df.rename(columns={
        schema.lojas_col_uf: "uf",
        schema.lojas_col_cnpj: "cnpj",
        schema.lojas_col_ean: "ean",
        schema.lojas_col_nome_produto: "nome_produto_loja",
        schema.lojas_col_laboratorio: "laboratorio_loja",
        schema.lojas_col_faturamento: "faturamento",
        schema.lojas_col_pct_cmv: "pct_cmv",
        schema.lojas_col_quantidade: "quantidade_venda",
        schema.lojas_col_estoque: "estoque",
    })

    motivos: dict[str, int] = {}

    # 1) linha agregada "Total"
    is_total = df["uf"].astype(str).str.strip().eq(schema.lojas_total_row_value)
    motivos["linha_total"] = int(is_total.sum())

    # 2) linhas de rodapé com texto de metadados de export
    marker_pattern = "|".join(schema.lojas_footer_markers)
    is_footer = df["uf"].astype(str).str.contains(marker_pattern, case=False, na=False, regex=True)
    motivos["rodape_export"] = int(is_footer.sum())

    # 3) linhas sem cnpj (registro quebrado)
    is_no_cnpj = df["cnpj"].isna()
    motivos["sem_cnpj"] = int((is_no_cnpj & ~is_total & ~is_footer).sum())

    df_clean = df[~is_total & ~is_footer & ~is_no_cnpj].copy()
    df_clean["ean"] = _norm_ean(df_clean["ean"])
    sem_ean = df_clean["ean"].isna().sum()
    motivos["sem_ean"] = int(sem_ean)
    df_clean = df_clean[df_clean["ean"].notna()]

    df_clean["custo_total"] = df_clean["faturamento"] * df_clean["pct_cmv"]

    agg = df_clean.groupby(["uf", "cnpj", "ean", "laboratorio_loja"], as_index=False).agg(
        faturamento=("faturamento", "sum"),
        custo_total=("custo_total", "sum"),
        quantidade_venda=("quantidade_venda", "sum"),
        estoque=("estoque", "sum"),
    )

    report = LoadReport(
        fonte="Movimentação das lojas",
        linhas_originais=original,
        linhas_validas=len(agg),
        linhas_descartadas=original - len(df_clean),
        motivos_descarte=motivos,
    )
    return agg, report
