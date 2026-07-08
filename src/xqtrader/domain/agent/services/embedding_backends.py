"""嵌入后端策略 — local SentenceTransformer 与 TEI HTTP。"""

from __future__ import annotations

import importlib.util
import logging
import math
from typing import Any, Protocol, cast

import httpx

from framework.config.settings import QdrantSettings

logger = logging.getLogger("AGENT.EMBEDDING")


def _l2_normalize(vectors: list[list[float]]) -> list[list[float]]:
    normalized: list[list[float]] = []
    for vector in vectors:
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            normalized.append(vector)
            continue
        normalized.append([v / norm for v in vector])
    return normalized


class EmbeddingBackend(Protocol):
    """嵌入编码后端协议。"""

    def encode(self, texts: list[str]) -> list[list[float]]: ...


class LocalEmbeddingBackend:
    """本地 SentenceTransformer 后端。"""

    def __init__(self, cfg: QdrantSettings) -> None:
        self._cfg = cfg
        self._model: Any = None

    def _ensure_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            model_path = self._cfg.EMBEDDING_MODEL_PATH
            logger.info("加载本地嵌入模型: %s", model_path)
            self._model = SentenceTransformer(model_path)
            logger.info("本地嵌入模型加载完成, dim=%d", self._cfg.EMBEDDING_DIM)
        return self._model

    def encode(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure_model()
        vectors = model.encode(texts, normalize_embeddings=True)
        return cast(list[list[float]], vectors.tolist())


class TeiEmbeddingBackend:
    """Text Embeddings Inference HTTP 后端。"""

    def __init__(self, cfg: QdrantSettings) -> None:
        self._cfg = cfg
        self._client: httpx.Client | None = None

    def _ensure_client(self) -> httpx.Client:
        if self._client is None:
            base_url = self._cfg.EMBEDDING_TEI_BASE_URL.rstrip("/")
            timeout = self._cfg.EMBEDDING_TEI_TIMEOUT_S
            logger.info("连接 TEI 嵌入服务: %s", base_url)
            self._client = httpx.Client(base_url=base_url, timeout=timeout)
            response = self._client.get("/info")
            response.raise_for_status()
            logger.info("TEI 嵌入服务已连接")
        return self._client

    def encode(self, texts: list[str]) -> list[list[float]]:
        client = self._ensure_client()
        response = client.post("/embed", json={"inputs": texts})
        response.raise_for_status()
        vectors = cast(list[list[float]], response.json())
        if len(vectors) != len(texts):
            raise ValueError(
                f"TEI 返回向量数 {len(vectors)} 与输入数 {len(texts)} 不一致",
            )
        dim = self._cfg.EMBEDDING_DIM
        for vector in vectors:
            if len(vector) != dim:
                raise ValueError(
                    f"TEI 向量维度 {len(vector)} 与配置 EMBEDDING_DIM={dim} 不一致",
                )
        return _l2_normalize(vectors)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


class EmbeddingBackendRegistry:
    """按配置名创建嵌入后端。"""

    _BACKENDS: dict[str, type[LocalEmbeddingBackend | TeiEmbeddingBackend]] = {
        "local": LocalEmbeddingBackend,
        "tei": TeiEmbeddingBackend,
    }

    @classmethod
    def create(cls, backend: str, cfg: QdrantSettings) -> EmbeddingBackend:
        factory = cls._BACKENDS.get(backend)
        if factory is None:
            raise ValueError(f"不支持的嵌入后端: {backend}")
        return factory(cfg)

    @classmethod
    def validate_available(cls, backend: str) -> None:
        """启动时校验后端依赖可达。"""
        if backend == "local":
            if importlib.util.find_spec("sentence_transformers") is None:
                raise RuntimeError(
                    "EMBEDDING_BACKEND=local 需要安装 sentence-transformers；"
                    "Docker 部署请设置 QDRANT_EMBEDDING_BACKEND=tei",
                )
            return
        if backend == "tei":
            return
        raise ValueError(f"不支持的嵌入后端: {backend}")
