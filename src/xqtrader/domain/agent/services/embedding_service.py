"""嵌入服务 — 本地 SentenceTransformer 或 TEI HTTP 后端。

设计原则:
  - 单例模式，后端只初始化一次
  - local：延迟加载本地 BGE 模型（开发机 Windows 路径）
  - tei：调用 Text Embeddings Inference /embed（Docker 部署推荐）
"""

from __future__ import annotations

import logging
import math
from typing import Any, Literal, cast

import httpx

from framework.config.settings import QdrantSettings, settings

logger = logging.getLogger("AGENT.EMBEDDING")

EmbeddingBackend = Literal["local", "tei"]


def _l2_normalize(vectors: list[list[float]]) -> list[list[float]]:
    normalized: list[list[float]] = []
    for vector in vectors:
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            normalized.append(vector)
            continue
        normalized.append([v / norm for v in vector])
    return normalized


class EmbeddingService:
    """嵌入模型单例服务"""

    _instance: EmbeddingService | None = None
    _local_model: Any = None
    _tei_client: httpx.Client | None = None

    def __new__(cls) -> EmbeddingService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> EmbeddingService:
        return cls()

    @property
    def _cfg(self) -> QdrantSettings:
        return settings.QDRANT

    def _backend(self) -> EmbeddingBackend:
        return self._cfg.EMBEDDING_BACKEND

    def _ensure_local_model(self) -> Any:
        if self._local_model is None:
            from sentence_transformers import SentenceTransformer

            model_path = self._cfg.EMBEDDING_MODEL_PATH
            logger.info("加载本地嵌入模型: %s", model_path)
            self._local_model = SentenceTransformer(model_path)
            logger.info("本地嵌入模型加载完成, dim=%d", self._cfg.EMBEDDING_DIM)
        return self._local_model

    def _ensure_tei_client(self) -> httpx.Client:
        if self._tei_client is None:
            base_url = self._cfg.EMBEDDING_TEI_BASE_URL.rstrip("/")
            timeout = self._cfg.EMBEDDING_TEI_TIMEOUT_S
            logger.info("连接 TEI 嵌入服务: %s", base_url)
            self._tei_client = httpx.Client(
                base_url=base_url,
                timeout=timeout,
            )
            response = self._tei_client.get("/info")
            response.raise_for_status()
            logger.info("TEI 嵌入服务已连接")
        return self._tei_client

    def _encode_local(self, texts: list[str]) -> list[list[float]]:
        model = self._ensure_local_model()
        vectors = model.encode(texts, normalize_embeddings=True)
        return cast(list[list[float]], vectors.tolist())

    def _encode_tei(self, texts: list[str]) -> list[list[float]]:
        client = self._ensure_tei_client()
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
                raise ValueError(f"TEI 向量维度 {len(vector)} 与配置 EMBEDDING_DIM={dim} 不一致")
        return _l2_normalize(vectors)

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        backend = self._backend()
        if backend == "tei":
            return self._encode_tei(texts)
        if backend == "local":
            return self._encode_local(texts)
        raise ValueError(f"不支持的嵌入后端: {backend}")

    def encode_one(self, text: str) -> list[float]:
        return self.encode([text])[0]
