"""
Configuração central do Cota RMC.

Princípio: nenhuma regra de negócio (dias de cobertura, margem de segurança,
nomes de coluna esperados, caminhos de storage) fica hardcoded dentro dos
módulos de lógica. Tudo flui a partir daqui ou do estado de sessão do usuário
(quando é um parâmetro ajustável em tela, ex: dias de cobertura).

Segredos (chaves de acesso) NUNCA ficam neste arquivo nem em nenhum outro
arquivo versionado. Eles vêm de variáveis de ambiente ou de
`.streamlit/secrets.toml` (ver `.streamlit/secrets.toml.example`).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def _env_float(key: str, default: float) -> float:
    val = os.environ.get(key)
    return float(val) if val else default


def _env_int(key: str, default: int) -> int:
    val = os.environ.get(key)
    return int(val) if val else default


def _secret(section: str, key: str) -> str | None:
    """Lê `st.secrets[section][key]`. Retorna None (sem levantar) se o
    Streamlit não estiver disponível, não houver secrets.toml, ou a chave
    não existir — quem chamar decide o fallback."""
    try:
        import streamlit as st
        return st.secrets.get(section, {}).get(key)
    except Exception:
        return None


def _spaces_value(secret_key: str, env_key: str, default: str | None = None) -> str | None:
    """st.secrets["spaces"] primeiro (mesmo padrão de modules/auth.py com
    st.secrets["auth"]); se ausente, cai para variável de ambiente — mantém
    os testes fora do Streamlit funcionando sem secrets.toml."""
    val = _secret("spaces", secret_key)
    if val:
        return val
    return _env(env_key, default)


@dataclass(frozen=True)
class SpacesConfig:
    """Credenciais e localização do bucket DigitalOcean Spaces (ou compatível S3)."""

    endpoint_url: str | None = field(default_factory=lambda: _spaces_value("endpoint_url", "SPACES_ENDPOINT_URL"))
    region: str | None = field(default_factory=lambda: _spaces_value("region", "SPACES_REGION"))
    access_key: str | None = field(default_factory=lambda: _spaces_value("access_key", "SPACES_ACCESS_KEY"))
    secret_key: str | None = field(default_factory=lambda: _spaces_value("secret_key", "SPACES_SECRET_KEY"))
    bucket: str | None = field(default_factory=lambda: _spaces_value("bucket", "SPACES_BUCKET"))
    # Pasta raiz deste projeto dentro do bucket compartilhado — separa do
    # Mapa da Farmácia, PEX 2.0 etc, que usam o mesmo bucket.
    project_prefix: str = field(
        default_factory=lambda: _spaces_value("project_prefix", "SPACES_PROJECT_PREFIX", "Cota RMC")
    )

    def is_configured(self) -> bool:
        return all([self.endpoint_url, self.access_key, self.secret_key, self.bucket])


@dataclass(frozen=True)
class BusinessDefaults:
    """
    Valores PADRÃO de regras de negócio — todos editáveis em tempo de execução
    pela aba de Configurações e guardados no estado de sessão / storage.
    Nunca referenciar estes valores diretamente dentro da lógica de cálculo;
    sempre passar o valor efetivo (vindo da config do usuário) como parâmetro
    explícito da função.
    """

    dias_cobertura_padrao: int = field(default_factory=lambda: _env_int("DIAS_COBERTURA_PADRAO", 7))
    margem_seguranca_ruptura: float = field(default_factory=lambda: _env_float("MARGEM_SEGURANCA_RUPTURA", 0.85))
    dias_cobertura_min: int = 1
    dias_cobertura_max: int = 90


@dataclass(frozen=True)
class SchemaConfig:
    """
    Nomes de coluna esperados nos arquivos de origem. Centralizados aqui para
    que uma mudança no export do GPS Farma ou na planilha RMC exija editar um
    só lugar, não procurar strings soltas pelo código.
    """

    # BASE_COMPLETA.xlsx (planilha de unificação de EAN)
    base_col_ean: str = "EAN"
    base_col_codigo_interno: str = "FCC"
    base_col_produto_unificado: str = "DESCRIÇÃO MARCOS"

    # DADOS_LOJAS (export GPS Farma)
    lojas_col_uf: str = "Nome_Estado"
    lojas_col_cnpj: str = "cnpj"
    lojas_col_ean: str = "CodigoBarras"
    lojas_col_nome_produto: str = "NomeProduto"
    lojas_col_laboratorio: str = "Laboratório"
    lojas_col_faturamento: str = "Fat. líquido"
    lojas_col_pct_cmv: str = "% CMV"
    lojas_col_pct_mlb: str = "% MLB"
    lojas_col_quantidade: str = "Quantidade"
    lojas_col_estoque: str = "QtdEstoque"

    # Tabela RMC (por laboratório)
    rmc_col_familia: str = "Família"
    rmc_col_ean: str = "EAN / DUN"
    rmc_col_produto: str = "Produto"
    rmc_col_preco_bruto: str = "R$ Unitário Bruto"
    rmc_col_desconto: str = "Desconto"
    rmc_col_preco_liquido: str = "R$ Total Líquido"

    # Linhas de rodapé/lixo de export a descartar (match por substring, case-insensitive)
    lojas_footer_markers: tuple[str, ...] = ("Filtros aplicados", "Exported data exceeded")
    lojas_total_row_value: str = "Total"


@dataclass(frozen=True)
class AppConfig:
    spaces: SpacesConfig = field(default_factory=SpacesConfig)
    business: BusinessDefaults = field(default_factory=BusinessDefaults)
    schema: SchemaConfig = field(default_factory=SchemaConfig)
    app_name: str = "Cota RMC"

    # Chaves de objeto dentro do prefixo do projeto no Spaces
    key_alias_table: str = "matching/aliases_confirmados.json"
    key_pending_table: str = "matching/pendencias.json"
    key_rmc_catalog: str = "rmc/catalogo_laboratorios.json"


def load_config() -> AppConfig:
    return AppConfig()
