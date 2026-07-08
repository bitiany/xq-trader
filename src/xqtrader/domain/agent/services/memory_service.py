"""记忆服务 — Qdrant 向量库管理

设计原则:
  - 单例 Qdrant 客户端
  - 经验召回补充层：存论点卡/简报摘要的向量，供语义检索
  - 不承载权威结论，仅辅助「跨标的经验类比」
  - collection 启动时自动创建（if not exists）
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
)

from framework.config.settings import settings

from .embedding_service import EmbeddingService

logger = logging.getLogger("AGENT.MEMORY")


class MemoryService:
    """Qdrant 向量记忆服务单例"""

    _instance: MemoryService | None = None
    _client: Any = None
    _initialized: bool = False
    _types_backfilled: bool = False

    def __new__(cls) -> MemoryService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> MemoryService:
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

    def ensure_payload_types(self) -> None:
        """为缺少 type 字段的历史向量补全类型，完成后方可按 type 精确过滤。"""
        if self._types_backfilled:
            return
        client = self._ensure_client()
        collection = settings.QDRANT.COLLECTION
        offset: Any = None
        updated = 0
        while True:
            records, offset = client.scroll(
                collection_name=collection,
                limit=100,
                offset=offset,
                with_payload=True,
            )
            for point in records:
                payload = point.payload or {}
                if payload.get("type"):
                    continue
                inferred = "thesis" if payload.get("direction") else "brief"
                client.set_payload(
                    collection_name=collection,
                    payload={"type": inferred},
                    points=[point.id],
                )
                updated += 1
            if offset is None:
                break
        self._types_backfilled = True
        if updated:
            logger.info("Qdrant 向量 type 回填完成: updated=%d", updated)

    def index_memory(
        self,
        text: str,
        payload: dict[str, Any],
    ) -> str:
        """将文本向量化并写入 Qdrant

        Args:
            text: 待索引的文本（论点卡摘要/简报结论）
            payload: 元数据（symbol / as_of / direction / type 等）

        Returns:
            写入的 point ID
        """
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
        memory_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """语义检索历史经验

        Args:
            query: 查询文本
            top_k: 返回条数
            symbol: 可选标的过滤
            memory_types: 可选记忆类型过滤（如 brief / thesis）

        Returns:
            匹配结果列表，每条含 score / text / payload
        """
        client = self._ensure_client()
        embedding = EmbeddingService.get_instance()
        query_vector = embedding.encode_one(query)

        must: list[Any] = []
        if symbol:
            must.append(FieldCondition(key="symbol", match=MatchValue(value=symbol)))
        if memory_types:
            must.append(
                FieldCondition(key="type", match=MatchAny(any=memory_types)),
            )
        query_filter = Filter(must=must) if must else None

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
