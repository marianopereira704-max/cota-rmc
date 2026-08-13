"""
Camada de persistência em DigitalOcean Spaces (compatível S3).

Isola tudo deste projeto dentro de `{project_prefix}/...` no bucket
compartilhado — não mistura com Mapa da Farmácia, PEX 2.0 etc.

Nunca instanciar boto3 client fora desta classe; nunca ler/escrever chave de
objeto fora daqui — assim, se o esquema de pastas mudar, é um só lugar a
editar.
"""
from __future__ import annotations

import json
from typing import Any

import pandas as pd

from config import SpacesConfig


class SpacesStorageError(RuntimeError):
    pass


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

    def _full_key(self, key: str) -> str:
        prefix = self._cfg.project_prefix.strip("/")
        return f"{prefix}/{key.lstrip('/')}"

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
