"""全局单例 Redis 客户端 — 业务侧只需 from framework.commons.redis_client import redis_client。"""

from __future__ import annotations

import json
from typing import cast

import redis as redis_lib

from framework.config.settings import settings

# 类型别名：避开 _RedisClient 类内 set 方法对内置 set 的名称遮蔽
_StrSet = set[str]


class _RedisClient:
    """Redis 全局单例 — 延迟初始化，首次访问时创建连接。"""

    _instance: _RedisClient | None = None
    _client: redis_lib.Redis | None = None

    def __new__(cls) -> _RedisClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def client(self) -> redis_lib.Redis:
        """获取 Redis 连接 — 延迟初始化。"""
        if self._client is None:
            self._client = redis_lib.Redis(
                host=settings.REDIS.REDIS_HOST,
                port=settings.REDIS.REDIS_PORT,
                password=settings.REDIS.REDIS_PASSWORD or None,
                db=settings.REDIS.REDIS_DB,
                decode_responses=True,
            )
        return self._client

    def set(self, name: str, value: str | bytes, ex: int | None = None, nx: bool = False) -> bool | None:
        return self.client.set(name, value, ex=ex, nx=nx)  # type: ignore[return-value]

    def delete(self, *names: str | bytes) -> int:
        return self.client.delete(*names)  # type: ignore[return-value]

    def get(self, name: str | bytes) -> str | None:
        return self.client.get(name)  # type: ignore[return-value]

    def ping(self) -> bool:
        return self.client.ping()  # type: ignore[return-value]

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # ==================== Pub/Sub ====================

    def publish(self, channel: str, message: dict) -> int:
        """发布消息到频道。"""
        # redis-py stubs 将同步 Redis 的方法返回类型标注为 Awaitable | Any（兼容 async），
        # 实际同步客户端返回 int，用 cast 显式断言真实返回类型。
        return cast(int, self.client.publish(channel, json.dumps(message, ensure_ascii=False)))

    def pubsub(self) -> redis_lib.client.PubSub:
        """创建PubSub对象。"""
        return cast(redis_lib.client.PubSub, self.client.pubsub())

    # ==================== Set 操作 ====================

    def sadd(self, name: str, *values: str) -> int:
        return cast(int, self.client.sadd(name, *values))

    def srem(self, name: str, *values: str) -> int:
        return cast(int, self.client.srem(name, *values))

    def scard(self, name: str) -> int:
        return cast(int, self.client.scard(name))

    def smembers(self, name: str) -> _StrSet:
        # 注：用模块级 _StrSet 别名，避免 mypy 将 set 误解析为同类内的 set() 方法
        return cast(set[str], self.client.smembers(name))

    def scan(self, cursor: int = 0, match: str | None = None, count: int = 10) -> tuple[int, list[str]]:
        return self.client.scan(cursor=cursor, match=match, count=count)  # type: ignore[return-value]

    # ==================== Hash 操作 ====================

    def hgetall(self, name: str) -> dict[str, str]:
        """返回 hash 中所有字段-值对（decode_responses=True 时值为 str）。"""
        return cast(dict[str, str], self.client.hgetall(name))


# 全局单例
redis_client = _RedisClient()
