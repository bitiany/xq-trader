"""全局单例 Redis 客户端 — 业务侧只需 from framework.commons.redis_client import redis_client。"""

from __future__ import annotations

import redis as redis_lib

from framework.config.settings import settings


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
                decode_responses=False,
            )
        return self._client

    def set(self, name: str, value: str | bytes, ex: int | None = None, nx: bool = False) -> bool | None:
        return self.client.set(name, value, ex=ex, nx=nx)  # type: ignore[return-value]

    def delete(self, *names: str | bytes) -> int:
        return self.client.delete(*names)  # type: ignore[return-value]

    def get(self, name: str | bytes) -> bytes | None:
        return self.client.get(name)  # type: ignore[return-value]

    def ping(self) -> bool:
        return self.client.ping()  # type: ignore[return-value]

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


# 全局单例
redis_client = _RedisClient()
