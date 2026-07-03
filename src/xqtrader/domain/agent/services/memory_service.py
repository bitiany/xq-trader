"""记忆服务 — Qdrant 向量库管理

设计原则:
  - 单例 Qdrant 客户端
  - 经验召回补充层：存论点卡/简报摘要的向量，供语义检索
  - 不承载权威结论，仅辅助「跨标的经验类比」
  - collection 启动时自动创建（if not exists）
"""

import logging
import uuid
from typing import Any

from framework.config.settings import settings

from .embedding_service import EmbeddingService

logger = logging.getLogger("AGENT.MEMORY")


class MemoryService:
    """Qdrant 向量记忆服务单例"""

    _instance: "MemoryService | None" = None
    _client: Any = None
    _initialized: bool = False

    def __new__(cls) -> "MemoryService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> "MemoryService":
        return cls()

    def _ensure_client(self) -> Any:
        """延迟初始化 Qdrant 客户端 + collection"""
        if self._client is None:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            cfg = settings.QDRANT
            self._client = QdrantClient(
                host=cfg.HOST,
                port=cfg.HTTP_PORT,
                grpc_port=cfg.GRPC_PORT,
                prefer_grpc=True,
            )
            collection = cfg.COLLECTION
            if not self._client.collection_exists(collection):
                self._client.create_collection(
                    collection_name=collection,
                    vectors_config=VectorParams(
                        size=cfg.EMBEDDING_DIM,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("Qdrant collection '%s' 已创建, dim=%d", collection, cfg.EMBEDDING_DIM)
            self._initialized = True
            logger.info("Qdrant 客户端已连接 %s:%d", cfg.HOST, cfg.GRPC_PORT)
        return self._client

    def index_memory(
        self,
        text: str,
        payload: dict[str, Any],
    ) -> str:
        """将文本向量化并写入 Qdrant

        Args:
            text: 待索引的文本（论点卡摘要/简报结论）
            payload: 元数据（symbol / as_of / direction / 场景标签等）

        Returns:
            写入的 point ID
        """
        from qdrant_client.models import PointStruct

        client = self._ensure_client()
        embedding = EmbeddingService.get_instance()
        vector = embedding.encode_one(text)
        point_id = str(uuid.uuid4())
        client.upsert(
            collection_name=settings.QDRANT.COLLECTION,
            points=[PointStruct(id=point_id, vector=vector, payload={**payload, "text": text})],
        )
        logger.debug("记忆已索引: id=%s, symbol=%s", point_id, payload.get("symbol"))
        return point_id

    def search_memory(
        self,
        query: str,
        top_k: int = 5,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        """语义检索历史经验

        Args:
            query: 查询文本
            top_k: 返回条数
            symbol: 可选标的过滤

        Returns:
            匹配结果列表，每条含 score / text / payload
        """
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        client = self._ensure_client()
        embedding = EmbeddingService.get_instance()
        query_vector = embedding.encode_one(query)

        query_filter: Filter | None = None
        if symbol:
            query_filter = Filter(
                must=[FieldCondition(key="symbol", match=MatchValue(value=symbol))]
            )

        result = client.query_points(
            collection_name=settings.QDRANT.COLLECTION,
            query=query_vector,
            limit=top_k,
            query_filter=query_filter,
        )
        return [
            {"score": p.score, "text": p.payload.get("text", ""), "payload": p.payload}
            for p in result.points
        ]
