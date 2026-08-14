"""
Camada de persistência em DigitalOcean Spaces (compatível S3).

Isola tudo deste projeto dentro de `{project_prefix}/...` no bucket
compartilhado — não mistura com Mapa da Farmácia, PEX 2.0 etc.

Nunca instanciar boto3 client fora desta classe; nunca ler/escrever chave de
objeto fora daqui — assim, se o esquema de pastas mudar, é um só lugar a
editar.
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from config import SpacesConfig


class SpacesStorageError(RuntimeError):
    pass


class SpacesPathError(SpacesStorageError):
    """Tentativa de operar fora do prefixo do projeto (ex: '..' na chave,
    caminho absoluto). Bloqueado, nunca sanitizado silenciosamente — decisão
    de segurança deliberada, ver CLAUDE.md / regra permanente do projeto."""


@dataclass(frozen=True)
class SpacesFileInfo:
    key: str  # relativo ao prefixo do projeto (nunca inclui "Cota RMC/")
    name: str
    size: int
    last_modified: datetime


@dataclass(frozen=True)
class SpacesListing:
    """Conteúdo de uma "pasta" (prefixo) — só o nível imediato, não
    recursivo (delimiter="/" é o padrão S3 pra isso). `folders` vem como
    caminhos relativos terminados em '/'."""
    folders: list[str] = field(default_factory=list)
    files: list[SpacesFileInfo] = field(default_factory=list)


class SpacesClient:
    def __init__(self, cfg: SpacesConfig):
        if not cfg.is_configured():
            raise SpacesStorageError(
                "Credenciais do Spaces não configuradas. Defina SPACES_ENDPOINT_URL, "
                "SPACES_ACCESS_KEY, SPACES_SECRET_KEY e SPACES_BUCKET em "
                ".streamlit/secrets.toml ou variáveis de ambiente."
            )
        self._cfg = cfg
        self._client = self._build_client()

    def _build_client(self):
        import boto3
        return boto3.client(
            "s3",
            endpoint_url=self._cfg.endpoint_url,
            region_name=self._cfg.region,
            aws_access_key_id=self._cfg.access_key,
            aws_secret_access_key=self._cfg.secret_key,
        )

    def _validar_caminho_relativo(self, caminho: str) -> str:
        """
        Bloqueia (não sanitiza) qualquer tentativa de escapar do prefixo do
        projeto: caminho absoluto (começa com '/') ou qualquer segmento '..'
        / '.'. Levanta SpacesPathError — quem chamar decide se mostra isso
        na tela ou deixa subir; nunca deve ser ignorado silenciosamente.
        """
        caminho = caminho or ""
        if caminho.startswith("/"):
            raise SpacesPathError(f"Caminho absoluto não permitido: '{caminho}'")
        for segmento in caminho.split("/"):
            if segmento in ("..", "."):
                raise SpacesPathError(f"Segmento de caminho não permitido ('{segmento}') em: '{caminho}'")
        return caminho

    def _full_key(self, key: str) -> str:
        key = self._validar_caminho_relativo(key)
        prefix = self._cfg.project_prefix.strip("/")
        full = f"{prefix}/{key}" if key else f"{prefix}/"
        # cinto e suspensório: mesmo depois de montada, a chave final precisa
        # começar exatamente pelo prefixo do projeto — nunca deixa uma
        # operação "escapar" pra outra pasta do bucket compartilhado.
        if not full.startswith(f"{prefix}/"):
            raise SpacesPathError(f"Chave final fora do prefixo do projeto: '{full}'")
        return full

    def read_json(self, key: str, default: Any = None) -> Any:
        try:
            obj = self._client.get_object(Bucket=self._cfg.bucket, Key=self._full_key(key))
            return json.loads(obj["Body"].read().decode("utf-8"))
        except self._client.exceptions.NoSuchKey:
            return default
        except Exception as exc:  # noqa: BLE001 - queremos degradar graciosamente
            if "NoSuchKey" in str(exc) or "404" in str(exc):
                return default
            raise SpacesStorageError(f"Falha ao ler '{key}' do Spaces: {exc}") from exc

    def write_json(self, key: str, data: Any) -> None:
        try:
            self._client.put_object(
                Bucket=self._cfg.bucket,
                Key=self._full_key(key),
                Body=json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
                ContentType="application/json",
            )
        except Exception as exc:  # noqa: BLE001
            raise SpacesStorageError(f"Falha ao gravar '{key}' no Spaces: {exc}") from exc

    def read_dataframe_json(self, key: str, columns: list[str]) -> pd.DataFrame:
        data = self.read_json(key, default=[])
        if not data:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame(data)

    def write_dataframe_json(self, key: str, df: pd.DataFrame) -> None:
        self.write_json(key, df.to_dict(orient="records"))

    def read_bytes(self, key: str) -> bytes | None:
        try:
            obj = self._client.get_object(Bucket=self._cfg.bucket, Key=self._full_key(key))
            return obj["Body"].read()
        except self._client.exceptions.NoSuchKey:
            return None
        except Exception as exc:  # noqa: BLE001 - queremos degradar graciosamente
            if "NoSuchKey" in str(exc) or "404" in str(exc):
                return None
            raise SpacesStorageError(f"Falha ao ler '{key}' do Spaces: {exc}") from exc

    def write_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        try:
            self._client.put_object(
                Bucket=self._cfg.bucket, Key=self._full_key(key), Body=data, ContentType=content_type,
            )
        except Exception as exc:  # noqa: BLE001
            raise SpacesStorageError(f"Falha ao gravar '{key}' no Spaces: {exc}") from exc

    def read_dataframe_parquet(self, key: str) -> pd.DataFrame | None:
        """
        Usado especificamente para o snapshot publicado da tabela final
        (~61 mil linhas nos dados reais) — medido: ~33MB em JSON contra
        ~0.7MB em Parquet para o mesmo volume. Como esse snapshot é baixado
        em TODO login de qualquer perfil, a diferença de tamanho vira custo
        de rede+parsing recorrente; aliases/pendências continuam em JSON
        porque são pequenos (dezenas de linhas). Retorna None se a chave não
        existir (nunca publicado ainda) — quem chama decide o estado vazio.
        """
        raw = self.read_bytes(key)
        if raw is None:
            return None
        return pd.read_parquet(io.BytesIO(raw))

    def write_dataframe_parquet(self, key: str, df: pd.DataFrame) -> None:
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        self.write_bytes(key, buf.getvalue())

    # -----------------------------------------------------------------
    # Gerenciador de arquivos genérico (usado pela página "Arquivos",
    # perfil consultor) — navega, cria pasta, renomeia, move e inativa
    # SEMPRE dentro do prefixo do projeto. `_full_key`/
    # `_validar_caminho_relativo` já bloqueiam qualquer tentativa de
    # escapar disso; os métodos abaixo não duplicam essa checagem, apenas
    # confiam nela por já rotearem toda chave por `_full_key`.
    # -----------------------------------------------------------------

    def list_objects(self, prefix: str = "") -> SpacesListing:
        """
        Lista pastas (CommonPrefixes) e arquivos (Contents) diretamente
        dentro de `prefix` (relativo ao prefixo do projeto) — não recursivo,
        via delimiter="/", o padrão S3 pra simular navegação de pastas.
        Chaves retornadas já vêm relativas (sem o prefixo do projeto) — quem
        usa este método nunca precisa saber o prefixo real.
        """
        prefix = self._validar_caminho_relativo(prefix)
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        full_prefix = self._full_key(prefix)
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            folders: list[str] = []
            files: list[SpacesFileInfo] = []
            for page in paginator.paginate(Bucket=self._cfg.bucket, Prefix=full_prefix, Delimiter="/"):
                for common_prefix in page.get("CommonPrefixes", []):
                    folders.append(common_prefix["Prefix"][len(full_prefix):])
                for obj in page.get("Contents", []):
                    key_completo = obj["Key"]
                    if key_completo == full_prefix:
                        continue  # marcador de pasta (objeto de 0 bytes representando a própria pasta)
                    key_relativo = key_completo[len(full_prefix):]
                    files.append(SpacesFileInfo(
                        key=prefix + key_relativo,
                        name=key_relativo,
                        size=obj["Size"],
                        last_modified=obj["LastModified"],
                    ))
            return SpacesListing(folders=[prefix + f for f in folders], files=files)
        except SpacesPathError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SpacesStorageError(f"Falha ao listar '{prefix}': {exc}") from exc

    def object_exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._cfg.bucket, Key=self._full_key(key))
            return True
        except SpacesPathError:
            raise
        except Exception:
            return False

    def create_folder_marker(self, prefix: str) -> None:
        """
        S3 não tem pasta de verdade — sem pelo menos 1 objeto sob o prefixo,
        ela nem aparece na listagem. Cria um objeto de 0 bytes terminado em
        '/' só pra pasta existir e navegar mesmo vazia.
        """
        prefix = prefix.rstrip("/") + "/"
        try:
            self._client.put_object(Bucket=self._cfg.bucket, Key=self._full_key(prefix), Body=b"")
        except SpacesPathError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SpacesStorageError(f"Falha ao criar pasta '{prefix}': {exc}") from exc

    def copy_object(self, src_key: str, dst_key: str) -> None:
        src_full = self._full_key(src_key)
        dst_full = self._full_key(dst_key)
        try:
            self._client.copy_object(
                Bucket=self._cfg.bucket,
                CopySource={"Bucket": self._cfg.bucket, "Key": src_full},
                Key=dst_full,
            )
        except SpacesPathError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SpacesStorageError(f"Falha ao copiar '{src_key}' para '{dst_key}': {exc}") from exc

    def delete_object(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._cfg.bucket, Key=self._full_key(key))
        except SpacesPathError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SpacesStorageError(f"Falha ao apagar '{key}': {exc}") from exc

    def move_object(self, src_key: str, dst_key: str) -> None:
        """Copia + apaga — S3 não tem "mover" nativo pra um único objeto."""
        self.copy_object(src_key, dst_key)
        self.delete_object(src_key)

    def rename_folder(self, old_prefix: str, new_prefix: str) -> int:
        """
        "Renomeia" uma pasta — S3 não tem rename nativo de prefixo. Copia
        cada objeto sob `old_prefix` para o mesmo caminho relativo sob
        `new_prefix`, depois apaga os originais. Retorna a quantidade de
        objetos movidos.

        NÃO é atômico — S3 não oferece transação multi-objeto. Se cair no
        meio (rede, permissão), pode sobrar objetos duplicados nos dois
        prefixos; quem chama decide se tenta de novo ou avisa o usuário.
        Também NÃO é paralelo — cada objeto é uma chamada HTTP própria de
        copy e outra de delete, então o tempo cresce linearmente com a
        quantidade de arquivos dentro da pasta. Para o volume esperado desta
        página (dezenas de arquivos, não milhares) isso é imperceptível; se
        um dia a pasta "Cota RMC/" acumular centenas/milhares de objetos,
        vale revisitar (paralelizar ou usar operação em lote do provedor).
        """
        old_prefix = old_prefix.rstrip("/") + "/"
        new_prefix = new_prefix.rstrip("/") + "/"
        old_full = self._full_key(old_prefix)
        new_full = self._full_key(new_prefix)
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            chaves_antigas: list[str] = []
            for page in paginator.paginate(Bucket=self._cfg.bucket, Prefix=old_full):
                for obj in page.get("Contents", []):
                    chaves_antigas.append(obj["Key"])

            for chave_antiga in chaves_antigas:
                chave_nova = new_full + chave_antiga[len(old_full):]
                self._client.copy_object(
                    Bucket=self._cfg.bucket,
                    CopySource={"Bucket": self._cfg.bucket, "Key": chave_antiga},
                    Key=chave_nova,
                )
            for chave_antiga in chaves_antigas:
                self._client.delete_object(Bucket=self._cfg.bucket, Key=chave_antiga)

            return len(chaves_antigas)
        except SpacesPathError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SpacesStorageError(f"Falha ao renomear '{old_prefix}' para '{new_prefix}': {exc}") from exc
