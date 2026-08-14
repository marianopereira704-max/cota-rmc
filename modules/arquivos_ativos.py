"""
"Arquivo ativo" por tipo de dado de origem — BASE_COMPLETA, tabela RMC (uma
por laboratório) e movimentação de lojas. Cada tipo mantém, dentro de
"Cota RMC/arquivos/{tipo}/", o arquivo Excel bruto vigente + um "ativo.json"
apontando pra ele, e um histórico completo das versões anteriores em
"historico/" — nunca apagadas, é rastreabilidade.

Conceito deliberadamente separado da "_lixeira/" do gerenciador de arquivos
genérico (modules/file_manager.py): aquela é inativação manual de qualquer
item pelo consultor; "historico/" aqui é versionamento automático de um tipo
de dado rastreado pelo sistema — nunca misturar os dois.

Guarda o EXCEL BRUTO (bytes), não o DataFrame processado — o objetivo é
permitir reprocessar no futuro com regras diferentes, diferente do
"snapshot publicado" (modules/storage.py write/read_dataframe_parquet, usado
em app.py `_publicar_snapshot`), que é a tabela final já calculada.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from modules.storage import SpacesClient

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@dataclass(frozen=True)
class ArquivoAtivo:
    nome_arquivo: str
    enviado_em: str  # ISO 8601
    enviado_por: str

    @property
    def enviado_em_fmt(self) -> str:
        return datetime.fromisoformat(self.enviado_em).strftime("%d/%m/%Y %H:%M")


def pasta_base_completa() -> str:
    return "arquivos/base_completa/"


def pasta_lojas() -> str:
    return "arquivos/lojas/"


def pasta_rmc(laboratorio: str) -> str:
    return f"arquivos/rmc/{laboratorio}/"


def _chave_ativo_json(pasta: str) -> str:
    return pasta + "ativo.json"


def ler_ativo(storage: SpacesClient, pasta: str) -> ArquivoAtivo | None:
    dados = storage.read_json(_chave_ativo_json(pasta), default=None)
    if dados is None:
        return None
    return ArquivoAtivo(
        nome_arquivo=dados["nome_arquivo"], enviado_em=dados["enviado_em"], enviado_por=dados["enviado_por"],
    )


def ler_bytes_ativo(storage: SpacesClient, pasta: str, ativo: ArquivoAtivo) -> bytes | None:
    return storage.read_bytes(pasta + ativo.nome_arquivo)


def publicar_nova_versao(
    storage: SpacesClient, pasta: str, nome_arquivo: str, conteudo: bytes, enviado_por: str,
) -> ArquivoAtivo:
    """
    Publica `conteudo` como a nova versão ativa de `pasta`. Se já havia um
    ativo, ele é movido para "historico/" ANTES de escrever o novo — nunca
    apagado. Retorna os metadados da nova versão.
    """
    ativo_anterior = ler_ativo(storage, pasta)
    if ativo_anterior is not None:
        chave_antiga = pasta + ativo_anterior.nome_arquivo
        if storage.object_exists(chave_antiga):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            destino_historico = f"{pasta}historico/{timestamp}_{ativo_anterior.nome_arquivo}"
            storage.move_object(chave_antiga, destino_historico)

    storage.write_bytes(pasta + nome_arquivo, conteudo, content_type=XLSX_CONTENT_TYPE)
    novo_ativo = ArquivoAtivo(nome_arquivo=nome_arquivo, enviado_em=datetime.now().isoformat(), enviado_por=enviado_por)
    storage.write_json(_chave_ativo_json(pasta), {
        "nome_arquivo": novo_ativo.nome_arquivo,
        "enviado_em": novo_ativo.enviado_em,
        "enviado_por": novo_ativo.enviado_por,
    })
    return novo_ativo


def listar_laboratorios_rmc(storage: SpacesClient) -> list[str]:
    """Laboratórios RMC já conhecidos (com pasta própria sob
    'arquivos/rmc/') — cada um tem seu próprio arquivo ativo e histórico,
    independente dos outros."""
    listagem = storage.list_objects("arquivos/rmc")
    return sorted(p.rstrip("/").rsplit("/", 1)[-1] for p in listagem.folders)
