"""
Regras específicas do Gerenciador de Arquivos (página "Arquivos", perfil
consultor) — formatação de exibição e a convenção de "_lixeira/" (inativação
reversível, padrão já usado no PEX 2.0: mover pro lugar de origem espelhado
dentro de uma subpasta "_lixeira/", nunca apagar de verdade).

As primitivas de Spaces (listar, copiar, apagar, renomear pasta) ficam em
modules/storage.py — este módulo só decide QUAIS caminhos usar para cada
ação, não fala com o Spaces diretamente.
"""
from __future__ import annotations

from datetime import datetime

from modules.storage import SpacesClient

LIXEIRA_PREFIX = "_lixeira/"


def formatar_tamanho(tamanho_bytes: int) -> str:
    tamanho = float(tamanho_bytes)
    for unidade in ("B", "KB", "MB", "GB"):
        if tamanho < 1024 or unidade == "GB":
            return f"{tamanho:.0f} {unidade}" if unidade == "B" else f"{tamanho:.1f} {unidade}"
        tamanho /= 1024
    return f"{tamanho:.1f} GB"


def formatar_data(dt: datetime) -> str:
    return dt.strftime("%d/%m/%Y %H:%M")


def esta_na_lixeira(caminho_relativo: str) -> bool:
    return caminho_relativo.startswith(LIXEIRA_PREFIX)


def caminho_para_lixeira(caminho_original: str) -> str:
    """Preserva a estrutura relativa de onde veio — restaurar é só tirar o
    prefixo "_lixeira/" de novo, o caminho em si já carrega a origem."""
    return LIXEIRA_PREFIX + caminho_original


def caminho_original_da_lixeira(caminho_na_lixeira: str) -> str:
    if not esta_na_lixeira(caminho_na_lixeira):
        raise ValueError(f"Caminho não está na lixeira: '{caminho_na_lixeira}'")
    return caminho_na_lixeira[len(LIXEIRA_PREFIX):]


def validar_nome_pasta(nome: str) -> str | None:
    """Retorna a mensagem de erro (ou None se válido). Só 1 segmento — quem
    quiser pasta aninhada cria uma de cada vez, navegando entre elas."""
    nome = nome.strip()
    if not nome:
        return "Informe um nome."
    if "/" in nome:
        return "Nome de pasta não pode conter '/'. Crie uma pasta de cada vez."
    if nome in (".", ".."):
        return f"Nome '{nome}' não é permitido."
    return None


def listar_todas_pastas(storage: SpacesClient) -> list[str]:
    """
    Lista recursiva de todos os prefixos de pasta sob "Cota RMC/" — usado só
    pelo seletor de pasta de destino ao mover um arquivo. O volume esperado
    aqui é pequeno (dezenas de pastas, não milhares), então uma varredura
    recursiva completa é barata; não usar este helper para a navegação
    normal (essa é por nível, via SpacesClient.list_objects).
    """
    pastas: list[str] = [""]

    def _recursivo(prefixo: str) -> None:
        listagem = storage.list_objects(prefixo)
        for pasta in listagem.folders:
            pastas.append(pasta)
            _recursivo(pasta)

    _recursivo("")
    return pastas
