"""嵌入服务 — 委托策略后端执行编码。"""

from __future__ import annotations

import logging

from framework.config.settings import settings

from .embedding_backends import EmbeddingBackend, EmbeddingBackendRegistry

logger = logging.getLogger("AGENT.EMBEDDING")


class EmbeddingService:
    """嵌入模型单例服务"""

    _instance: EmbeddingService | None = None
    _backend: EmbeddingBackend | None = None

    def __new__(cls) -> EmbeddingService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> EmbeddingService:
        return cls()

    @classmethod
    def validate_backend(cls) -> None:
        """Worker 启动时校验嵌入后端配置。"""
        cfg = settings.QDRANT
        EmbeddingBackendRegistry.validate_available(cfg.EMBEDDING_BACKEND)

    def _ensure_backend(self) -> EmbeddingBackend:
        if self._backend is None:
            cfg = settings.QDRANT
            self._backend = EmbeddingBackendRegistry.create(
                cfg.EMBEDDING_BACKEND,
                cfg,
            )
        return self._backend

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._ensure_backend().encode(texts)

    def encode_one(self, text: str) -> list[float]:
        return self.encode([text])[0]
