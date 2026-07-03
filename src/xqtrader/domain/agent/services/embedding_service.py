"""嵌入服务 — BGE-large-zh-v1.5 本地模型单例

设计原则:
  - 单例模式，模型只加载一次（BGE-large ~1.3GB）
  - 延迟初始化，首次调用 encode 时才加载模型
  - 线程安全（模型加载后只读，encode 可并发）
"""

import logging
from typing import Any, cast

from framework.config.settings import settings

logger = logging.getLogger("AGENT.EMBEDDING")


class EmbeddingService:
    """BGE 嵌入模型单例服务"""

    _instance: "EmbeddingService | None" = None
    _model: Any = None

    def __new__(cls) -> "EmbeddingService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> "EmbeddingService":
        """获取单例实例"""
        return cls()

    def _ensure_model(self) -> Any:
        """延迟加载嵌入模型"""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            model_path = settings.QDRANT.EMBEDDING_MODEL_PATH
            logger.info("加载嵌入模型: %s", model_path)
            self._model = SentenceTransformer(model_path)
            logger.info("嵌入模型加载完成, dim=%d", settings.QDRANT.EMBEDDING_DIM)
        return self._model

    def encode(self, texts: list[str]) -> list[list[float]]:
        """将文本列表编码为向量列表

        Args:
            texts: 待编码文本列表

        Returns:
            向量列表，每个向量维度为 EMBEDDING_DIM
        """
        model = self._ensure_model()
        vectors = model.encode(texts, normalize_embeddings=True)
        return cast(list[list[float]], vectors.tolist())

    def encode_one(self, text: str) -> list[float]:
        """编码单条文本为向量"""
        return self.encode([text])[0]
