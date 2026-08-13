"""
Gera dados de exemplo 100% sintéticos (fixtures) para o Cota RMC.

Por quê: o repositório é público. Estes arquivos preservam a estrutura exata
(nomes de coluna, nomes de aba) e os casos-limite reais que o app precisa
tratar — pendências de matching, duplicidade de cadastro, rodapé de export,
outliers de estoque/CMV negativo — mas com CNPJ, produto e valores
inventados. NUNCA um recorte de dado real, nem que seja pequeno.

NÃO usar em produção. Servem só para teste local e validação de fluxo sem
depender dos arquivos reais nem expor dado real no repositório.

Como rodar (da raiz do projeto):
    python tests/fixtures/gerar_dados_exemplo.py

Gera, sobrescrevendo se já existirem, em tests/fixtures/:
    - BASE_COMPLETA_exemplo.xlsx
    - TABELA_RMC_exemplo.xlsx
    - DADOS_LOJAS_exemplo.xlsx

Seed fixo (42): rodar o script duas vezes produz exatamente os mesmos
arquivos (reprodutível, sem timestamp nem aleatoriedade real).
"""
from __future__ import annotations

import random
from pathlib import Path

import pandas as pd

SEED = 42
OUT_DIR = Path(__file__).parent

rng = random.Random(SEED)

# ---------------------------------------------------------------------------
# Vocabulário sintético — nada disso é copiado de um export real
# ---------------------------------------------------------------------------
PRINCIPIOS_ATIVOS = [
    "PARACETAMOL", "AMOXICILINA", "IBUPROFENO", "DIPIRONA SODICA", "OMEPRAZOL",
    "LOSARTANA POTASSICA", "CLORIDRATO DE METFORMINA", "SINVASTATINA",
    "AZITROMICINA DIIDRATADA", "CLORIDRATO DE SERTRALINA", "ATENOLOL",
    "CAPTOPRIL", "HIDROCLOROTIAZIDA", "CETOCONAZOL", "LORATADINA",
    "PREDNISONA", "DEXAMETASONA", "CLORIDRATO DE CIPROFLOXACINO",
    "FLUCONAZOL", "CLONAZEPAM",
]
DOSAGENS = ["10MG", "20MG", "25MG", "50MG", "100MG", "250MG", "500MG", "850MG"]
FORMAS_QTDS = [
    ("COMPRIMIDOS", [10, 12, 14, 20, 21, 24, 30, 60]),
    ("CAPSULAS", [10, 14, 20, 21, 30]),
    ("COMPRIMIDOS REVESTIDOS", [10, 14, 20, 30]),
]
ESTADOS = [
    "São Paulo", "Rio de Janeiro", "Minas Gerais", "Bahia", "Paraná", "Ceará", "Pernambuco",
]
LABORATORIOS_LOJA = [
    "EMS", "GERMED", "MEDLEY", "PRATI DONADUZZI", "TEUTO", "EUROFARMA", "CIMED", "NEO QUIMICA",
]


def _gerar_ean(usados: set[str]) -> str:
    while True:
        ean = "".join(str(rng.randint(0, 9)) for _ in range(13))
        if ean not in usados:
            usados.add(ean)
            return ean


def _gerar_cnpj() -> str:
    d = [str(rng.randint(0, 9)) for _ in range(14)]
    return f"{d[0]}{d[1]}.{d[2]}{d[3]}{d[4]}.{d[5]}{d[6]}{d[7]}/{d[8]}{d[9]}{d[10]}{d[11]}-{d[12]}{d[13]}"


def _gerar_produtos_unificados(n: int) -> list[dict]:
    """Nomes de produto únicos, cada um com sua família (princípio ativo)."""
    produtos = []
    nomes_usados: set[str] = set()
    i = 0
    while len(produtos) < n:
        principio = PRINCIPIOS_ATIVOS[i % len(PRINCIPIOS_ATIVOS)]
        dosagem = DOSAGENS[(i // len(PRINCIPIOS_ATIVOS)) % len(DOSAGENS)]
        forma, qtds = FORMAS_QTDS[i % len(FORMAS_QTDS)]
        qtd = qtds[(i // len(FORMAS_QTDS)) % len(qtds)]
        nome = f"{principio} {dosagem} X {qtd} {forma}"
        i += 1
        if nome in nomes_usados:
            continue
        nomes_usados.add(nome)
        produtos.append({"produto_unificado": nome, "familia": principio})
    return produtos


# ---------------------------------------------------------------------------
# 1. BASE_COMPLETA_exemplo.xlsx
# ---------------------------------------------------------------------------
def gerar_base_completa() -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Devolve o DataFrame pronto pra exportar + um dict {produto_unificado: [eans]}
    pra ser reaproveitado pelos outros dois geradores."""
    produtos = _gerar_produtos_unificados(90)
    eans_usados: set[str] = set()
    produto_para_eans: dict[str, list[str]] = {}

    linhas = []
    for idx, prod in enumerate(produtos):
        n_eans = rng.randint(2, 6)
        eans = [_gerar_ean(eans_usados) for _ in range(n_eans)]
        produto_para_eans[prod["produto_unificado"]] = eans
        for ean in eans:
            linhas.append({
                "FCC": f"FCC{idx + 1:05d}",
                "EAN": ean,
                "DESCRIÇÃO MARCOS": prod["produto_unificado"],
            })

    # 2 linhas com EAN vazio/nulo — caso real já tratado no data_loader
    for extra_idx in range(2):
        prod = produtos[extra_idx]
        linhas.append({
            "FCC": f"FCC{len(produtos) + extra_idx + 1:05d}",
            "EAN": None,
            "DESCRIÇÃO MARCOS": prod["produto_unificado"],
        })

    df = pd.DataFrame(linhas, columns=["FCC", "EAN", "DESCRIÇÃO MARCOS"])
    return df, produto_para_eans


# ---------------------------------------------------------------------------
# 2. TABELA_RMC_exemplo.xlsx
# ---------------------------------------------------------------------------
def gerar_tabela_rmc(produto_para_eans: dict[str, list[str]]) -> pd.DataFrame:
    produtos_base = list(produto_para_eans.keys())
    n_resolvidos = 100
    n_pendentes = 13

    produtos_escolhidos = rng.sample(produtos_base, min(n_resolvidos, len(produtos_base)))

    linhas = []
    for produto in produtos_escolhidos:
        ean = rng.choice(produto_para_eans[produto])
        familia = produto.split()[0]
        bruto = round(rng.uniform(3.0, 150.0), 4)
        desconto = round(rng.uniform(0.05, 0.35), 4)
        liquido = round(bruto * (1 - desconto), 4)
        linhas.append({
            "Família": familia,
            "EAN / DUN": ean,
            "Produto": produto,
            "Quantidade Solicitada": 0,
            "R$ Unitário Bruto": bruto,
            "Desconto": desconto,
            "R$ Total Líquido": liquido,
            "R$ Total Líquido Total": round(liquido * 0, 2),
        })

    # ~10-15 EANs que NÃO existem na base — geram pendência de matching de propósito
    eans_base_todos = {ean for eans in produto_para_eans.values() for ean in eans}
    eans_pendentes: set[str] = set()
    for i in range(n_pendentes):
        while True:
            ean = "".join(str(rng.randint(0, 9)) for _ in range(13))
            if ean not in eans_base_todos and ean not in eans_pendentes:
                eans_pendentes.add(ean)
                break
        principio = PRINCIPIOS_ATIVOS[i % len(PRINCIPIOS_ATIVOS)]
        nome_pendente = f"{principio} {DOSAGENS[i % len(DOSAGENS)]} X {10 + i} COMPRIMIDOS (SEM MATCH)"
        bruto = round(rng.uniform(3.0, 150.0), 4)
        desconto = round(rng.uniform(0.05, 0.35), 4)
        liquido = round(bruto * (1 - desconto), 4)
        linhas.append({
            "Família": principio,
            "EAN / DUN": ean,
            "Produto": nome_pendente,
            "Quantidade Solicitada": 0,
            "R$ Unitário Bruto": bruto,
            "Desconto": desconto,
            "R$ Total Líquido": liquido,
            "R$ Total Líquido Total": 0.0,
        })

    # 1 linha "vazia" no fim (artefato real do export: EAN/preço/produto em
    # branco, só isso já basta pra ser descartada pela regra de negócio).
    # "Quantidade Solicitada" fica 0 (mesmo valor que toda outra linha já
    # tem, não é um valor especial) só pra essa linha não desaparecer
    # silenciosamente no round-trip do openpyxl — uma linha em que TODAS as
    # colunas são None na última posição do arquivo não sobrevive à leitura
    # (o range usado da planilha não a inclui), o que impediria testar o
    # descarte dela de verdade.
    linhas.append({
        "Família": None, "EAN / DUN": None, "Produto": None,
        "Quantidade Solicitada": 0,
        "R$ Unitário Bruto": None, "Desconto": None,
        "R$ Total Líquido": None, "R$ Total Líquido Total": None,
    })

    return pd.DataFrame(linhas, columns=[
        "Família", "EAN / DUN", "Produto", "Quantidade Solicitada",
        "R$ Unitário Bruto", "Desconto", "R$ Total Líquido", "R$ Total Líquido Total",
    ])


# ---------------------------------------------------------------------------
# 3. DADOS_LOJAS_exemplo.xlsx
# ---------------------------------------------------------------------------
def gerar_dados_lojas(produto_para_eans: dict[str, list[str]]) -> pd.DataFrame:
    eans_base_todos = [ean for eans in produto_para_eans.values() for ean in eans]
    eans_base_set = set(eans_base_todos)

    # pool de EANs "órfãos" — não existem em lugar nenhum, simula código de barras não mapeado
    orfaos: set[str] = set()
    while len(orfaos) < 80:
        ean = "".join(str(rng.randint(0, 9)) for _ in range(13))
        if ean not in eans_base_set:
            orfaos.add(ean)
    orfaos = list(orfaos)

    cnpjs = [_gerar_cnpj() for _ in range(50)]
    cnpj_para_estado = {cnpj: ESTADOS[i % len(ESTADOS)] for i, cnpj in enumerate(cnpjs)}

    linhas = []

    def _nova_linha(cnpj, ean, nome_produto, laboratorio, quantidade, estoque, pct_cmv_override=None):
        preco_unit_estimado = round(rng.uniform(5.0, 200.0), 2)
        faturamento = round(preco_unit_estimado * quantidade, 2)
        pct_cmv = pct_cmv_override if pct_cmv_override is not None else round(rng.uniform(0.55, 0.75), 4)
        pct_mlb = round(1 - pct_cmv, 4)
        return {
            "Nome_Estado": cnpj_para_estado[cnpj],
            "cnpj": cnpj,
            "CodigoBarras": ean,
            "NomeProduto": nome_produto,
            "Laboratório": laboratorio,
            "Fat. líquido": faturamento,
            "% CMV": pct_cmv,
            "% MLB": pct_mlb,
            "Quantidade": quantidade,
            "QtdEstoque": estoque,
        }

    TOTAL_LINHAS_ALVO = 2500

    # --- casos gerais (maioria das linhas): mistura de matches reais e órfãos ---
    n_gerais = TOTAL_LINHAS_ALVO - 120  # reserva espaço pros casos propositais abaixo
    for _ in range(n_gerais):
        cnpj = rng.choice(cnpjs)
        laboratorio = rng.choice(LABORATORIOS_LOJA)
        if rng.random() < 0.15:
            ean = rng.choice(orfaos)
            nome_produto = "PRODUTO SEM CADASTRO NA BASE"
        else:
            ean = rng.choice(eans_base_todos)
            nome_produto = f"GENERICO {ean[-4:]}"
        quantidade = rng.randint(0, 60)
        estoque = rng.randint(0, 120)
        linhas.append(_nova_linha(cnpj, ean, nome_produto, laboratorio, quantidade, estoque))

    # --- Oportunidade: quantidade=0 e estoque=0 registrados explicitamente ---
    for _ in range(20):
        cnpj = rng.choice(cnpjs)
        ean = rng.choice(eans_base_todos)
        laboratorio = rng.choice(LABORATORIOS_LOJA)
        linhas.append(_nova_linha(cnpj, ean, f"GENERICO {ean[-4:]}", laboratorio, 0, 0))

    # --- Risco de Ruptura: venda alta, estoque baixíssimo (cobre a margem/dias padrão) ---
    for _ in range(20):
        cnpj = rng.choice(cnpjs)
        ean = rng.choice(eans_base_todos)
        laboratorio = rng.choice(LABORATORIOS_LOJA)
        venda = rng.randint(50, 120)
        estoque = rng.randint(1, 3)
        linhas.append(_nova_linha(cnpj, ean, f"GENERICO {ean[-4:]}", laboratorio, venda, estoque))

    # --- duplicidade cnpj+CodigoBarras com NomeProduto diferente (mesmo laboratório,
    # pra cair no mesmo grupo de agregação e testar o merge de verdade) ---
    duplicados_alvo = []
    for _ in range(4):
        cnpj = rng.choice(cnpjs)
        ean = rng.choice(eans_base_todos)
        laboratorio = rng.choice(LABORATORIOS_LOJA)
        duplicados_alvo.append((cnpj, ean, laboratorio))
        for variante in ("CADASTRO A", "CADASTRO B"):
            venda = rng.randint(1, 30)
            estoque = rng.randint(1, 50)
            linhas.append(_nova_linha(
                cnpj, ean, f"GENERICO {ean[-4:]} ({variante})", laboratorio, venda, estoque
            ))

    # --- outliers: QtdEstoque negativo e % CMV negativo (replica caso real observado) ---
    for _ in range(12):
        cnpj = rng.choice(cnpjs)
        ean = rng.choice(eans_base_todos)
        laboratorio = rng.choice(LABORATORIOS_LOJA)
        venda = rng.randint(1, 20)
        estoque_negativo = -rng.randint(1, 5)
        linhas.append(_nova_linha(cnpj, ean, f"GENERICO {ean[-4:]}", laboratorio, venda, estoque_negativo))

    for _ in range(12):
        cnpj = rng.choice(cnpjs)
        ean = rng.choice(eans_base_todos)
        laboratorio = rng.choice(LABORATORIOS_LOJA)
        venda = rng.randint(1, 20)
        estoque = rng.randint(0, 20)
        linhas.append(_nova_linha(
            cnpj, ean, f"GENERICO {ean[-4:]}", laboratorio, venda, estoque,
            pct_cmv_override=round(rng.uniform(-0.10, -0.02), 4),
        ))

    df = pd.DataFrame(linhas, columns=[
        "Nome_Estado", "cnpj", "CodigoBarras", "NomeProduto", "Laboratório",
        "Fat. líquido", "% CMV", "% MLB", "Quantidade", "QtdEstoque",
    ])

    # --- rodapé real do export: linha "Total", linha vazia, 2 linhas de metadados ---
    linha_total = {col: None for col in df.columns}
    linha_total["Nome_Estado"] = "Total"
    linha_total["Quantidade"] = df["Quantidade"].clip(lower=0).sum()
    linha_total["QtdEstoque"] = df["QtdEstoque"].clip(lower=0).sum()

    linha_vazia = {col: None for col in df.columns}

    linha_filtros = {col: None for col in df.columns}
    linha_filtros["Nome_Estado"] = (
        "Filtros aplicados:\nVENDAS VLR Liquido não está vazio(a). Data >= 01/01/2026."
    )

    linha_excedeu = {col: None for col in df.columns}
    linha_excedeu["Nome_Estado"] = (
        "Exported data exceeded the allowed volume. Some rows may be missing."
    )

    df_rodape = pd.DataFrame([linha_total, linha_vazia, linha_filtros, linha_excedeu], columns=df.columns)
    return pd.concat([df, df_rodape], ignore_index=True)


# ---------------------------------------------------------------------------
def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    base_df, produto_para_eans = gerar_base_completa()
    base_path = OUT_DIR / "BASE_COMPLETA_exemplo.xlsx"
    base_df.to_excel(base_path, index=False, sheet_name="Planilha1")
    print(f"{base_path.name}: {len(base_df)} linhas")

    rmc_df = gerar_tabela_rmc(produto_para_eans)
    rmc_path = OUT_DIR / "TABELA_RMC_exemplo.xlsx"
    rmc_df.to_excel(rmc_path, index=False, sheet_name="Planilha1")
    print(f"{rmc_path.name}: {len(rmc_df)} linhas")

    lojas_df = gerar_dados_lojas(produto_para_eans)
    lojas_path = OUT_DIR / "DADOS_LOJAS_exemplo.xlsx"
    lojas_df.to_excel(lojas_path, index=False, sheet_name="Export")
    print(f"{lojas_path.name}: {len(lojas_df)} linhas")

    print("\nFixtures geradas em:", OUT_DIR)


if __name__ == "__main__":
    main()
