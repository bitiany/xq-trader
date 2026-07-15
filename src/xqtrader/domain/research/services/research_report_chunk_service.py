"""研报全文 RAG 服务 — chunk 切分 + 向量化入库 Qdrant + 向量检索。

架构文档 §14.4 研报全文 RAG 检索。

设计原则:
  - 独立 collection `research_report_chunks`，不复用 `research_memory`，
    避免 chunk 级文本污染论点卡/简报级语义召回
  - 复用 EmbeddingService（bge-large-zh-v1.5）和 Qdrant 客户端
  - chunk 切分：800 字/片，150 字重叠
  - 增量检测：ResearchReport.vector_indexed 字段
  - Qdrant 客户端同步调用经 asyncio.to_thread 桥接
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from typing import Any

from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from framework.commons.logger import get_logger
from framework.config.settings import settings
from xqtrader.domain.agent.services.embedding_service import EmbeddingService
from xqtrader.domain.research.models.research_report import ResearchReport

logger = get_logger("RESEARCH.RAG")

_CHUNK_SIZE = 800
_CHUNK_OVERLAP = 150
_COLLECTION = "research_report_chunks"
_BATCH_UPSERT_SIZE = 64


def _split_content(content: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """将研报正文切分为重叠 chunks。

    Args:
        content: 研报全文
        chunk_size: 单片字数
        overlap: 相邻片重叠字数

    Returns:
        chunk 文本列表
    """
    if not content or not content.strip():
        return []
    text = content.strip()
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    step = chunk_size - overlap
    if step <= 0:
        step = chunk_size
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        if end >= len(text):
            break
        start += step
    return chunks


class ResearchReportChunkService:
    """研报全文 RAG 服务 — chunk 切分 + 向量化 + 检索。"""

    def __init__(self) -> None:
        self._client: Any = None
        self._collection_ready = False

    # ── Qdrant 客户端管理 ────────────────────────────────────────────────

    def _ensure_client(self) -> Any:
        """懒加载 Qdrant 客户端 + 创建 collection（若不存在）。"""
        if self._client is not None:
            return self._client
        from qdrant_client import QdrantClient

        cfg = settings.QDRANT
        self._client = QdrantClient(
            host=cfg.HOST,
            port=cfg.HTTP_PORT,
            grpc_port=cfg.GRPC_PORT,
            prefer_grpc=True,
        )
        if not self._client.collection_exists(_COLLECTION):
            self._client.create_collection(
                collection_name=_COLLECTION,
                vectors_config=VectorParams(
                    size=cfg.EMBEDDING_DIM,
                    distance=Distance.COSINE,
                ),
            )
            logger.info(
                "Qdrant collection '%s' 已创建, dim=%d",
                _COLLECTION,
                cfg.EMBEDDING_DIM,
            )
        self._collection_ready = True
        logger.info("研报 RAG Qdrant 客户端已连接 %s:%d", cfg.HOST, cfg.GRPC_PORT)
        return self._client

    # ── 索引 ────────────────────────────────────────────────────────────

    async def index_report(self, info_code: str) -> int:
        """将指定研报全文切分 + 向量化入库 Qdrant。

        Args:
            info_code: 研报唯一标识

        Returns:
            索引的 chunk 数量（0 表示研报无正文或不存在）
        """
        reports = await ResearchReport.filter(limit=1, info_code=info_code)
        if not reports:
            logger.warning("研报不存在: info_code=%s", info_code)
            return 0
        report = reports[0]
        content = report.content or ""
        chunks = _split_content(content)
        if not chunks:
            logger.info("研报无正文可索引: info_code=%s title=%s", info_code, report.title)
            await self._mark_indexed(info_code)
            return 0

        payload_base = self._build_payload_base(report)
        count = await self._upsert_chunks(chunks, payload_base)
        await self._mark_indexed(info_code)
        logger.info(
            "研报向量化完成: info_code=%s title=%s chunks=%d",
            info_code,
            report.title[:60],
            count,
        )
        return count

    async def index_pending_reports(self, limit: int = 50) -> int:
        """批量索引 vector_indexed=false 的研报。

        Args:
            limit: 单次处理上限

        Returns:
            成功索引的研报数量
        """
        reports = await ResearchReport.filter(
            limit=limit,
            vector_indexed=False,
            content__isnull=False,
        )
        if not reports:
            logger.info("无待索引研报")
            return 0

        total_chunks = 0
        indexed_count = 0
        for report in reports:
            content = report.content or ""
            chunks = _split_content(content)
            if not chunks:
                await self._mark_indexed(report.info_code)
                continue
            payload_base = self._build_payload_base(report)
            count = await self._upsert_chunks(chunks, payload_base)
            await self._mark_indexed(report.info_code)
            total_chunks += count
            indexed_count += 1

        logger.info(
            "批量研报向量化完成: reports=%d chunks=%d",
            indexed_count,
            total_chunks,
        )
        return indexed_count

    async def _upsert_chunks(self, chunks: list[str], payload_base: dict[str, Any]) -> int:
        """批量向量化 + upsert chunks 到 Qdrant。"""
        client = self._ensure_client()
        embedding = EmbeddingService.get_instance()

        # 批量向量化（分批避免单次过大）
        all_points: list[PointStruct] = []
        for i in range(0, len(chunks), _BATCH_UPSERT_SIZE):
            batch = chunks[i : i + _BATCH_UPSERT_SIZE]
            vectors = await asyncio.to_thread(embedding.encode, batch)
            for j, (chunk_text, vector) in enumerate(zip(batch, vectors, strict=True)):
                chunk_index = i + j
                point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{payload_base['info_code']}:{chunk_index}"))
                payload = {
                    **payload_base,
                    "chunk_index": chunk_index,
                    "text": chunk_text,
                }
                all_points.append(PointStruct(id=point_id, vector=vector, payload=payload))

        # 批量 upsert（同步调用经 to_thread 桥接）
        await asyncio.to_thread(client.upsert, collection_name=_COLLECTION, points=all_points)
        return len(all_points)

    @staticmethod
    def _build_payload_base(report: ResearchReport) -> dict[str, Any]:
        """构建 chunk payload 基础元数据。"""
        publish_date = report.publish_date
        return {
            "info_code": report.info_code,
            "symbol": report.symbol or "",
            "source": report.org_name or "",
            "publish_date": publish_date.isoformat() if isinstance(publish_date, date) else "",
            "rating": report.rating or "",
            "title": report.title or "",
        }

    @staticmethod
    async def _mark_indexed(info_code: str) -> None:
        """标记研报为已向量化。"""
        await ResearchReport.update_by(
            {"vector_indexed": True},
            info_code=info_code,
        )

    # ── 检索 ────────────────────────────────────────────────────────────

    async def search_chunks(
        self,
        query: str,
        symbol: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """向量检索研报 chunks。

        Args:
            query: 查询文本
            symbol: 可选标的过滤
            top_k: 返回条数

        Returns:
            匹配结果列表，每条含 chunk_text / source / publish_date / score
        """
        client = self._ensure_client()
        embedding = EmbeddingService.get_instance()
        query_vector = await asyncio.to_thread(embedding.encode_one, query)

        must: list[Any] = []
        if symbol:
            must.append(FieldCondition(key="symbol", match=MatchValue(value=symbol)))
        query_filter = Filter(must=must) if must else None

        result = await asyncio.to_thread(
            client.query_points,
            collection_name=_COLLECTION,
            query=query_vector,
            limit=top_k,
            query_filter=query_filter,
        )

        return [
            {
                "chunk_text": p.payload.get("text", ""),
                "info_code": p.payload.get("info_code", ""),
                "symbol": p.payload.get("symbol", ""),
                "source": p.payload.get("source", ""),
                "publish_date": p.payload.get("publish_date", ""),
                "rating": p.payload.get("rating", ""),
                "title": p.payload.get("title", ""),
                "chunk_index": p.payload.get("chunk_index", 0),
                "score": float(p.score) if p.score is not None else 0.0,
            }
            for p in result.points
        ]
