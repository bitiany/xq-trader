"""SPI基类与注册中心"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class TopicSpi(ABC):
    """精确 topic 匹配 SPI 基类

    一个 topic_name 对应一个 SPI 类，scheduler 为每个被订阅的 topic 启动独立 job。
    """

    @property
    @abstractmethod
    def topic_name(self) -> str:
        pass

    @abstractmethod
    def execute(self) -> Any:
        pass


class PrefixTopicSpi(ABC):
    """前缀匹配 Topic SPI 基类

    用于一个 SPI 类处理多个同前缀 topic 的场景（如 ws.market.stock_quotes.{symbol}）。
    scheduler 对同一前缀只启动一个单例 job，execute_for_topics 批量处理所有被订阅的 topic，
    返回 {topic: data} 后由 scheduler 分别 publish 到对应 topic channel。
    """

    @property
    @abstractmethod
    def topic_prefix(self) -> str:
        """topic 前缀，如 'ws.market.stock_quotes.'"""

    @abstractmethod
    def execute_for_topics(self, topics: list[str]) -> dict[str, Any]:
        """批量执行，返回 {topic: data}，由 scheduler 分别 publish"""


class SpiRegistry:
    """SPI注册中心"""

    _spis: dict[str, type[TopicSpi]] = {}
    _prefix_spis: dict[str, type[PrefixTopicSpi]] = {}

    @classmethod
    def register(cls, spi_class: type[TopicSpi]) -> None:
        instance = spi_class()
        cls._spis[instance.topic_name] = spi_class

    @classmethod
    def register_prefix(cls, spi_class: type[PrefixTopicSpi]) -> None:
        instance = spi_class()
        cls._prefix_spis[instance.topic_prefix] = spi_class

    @classmethod
    def get(cls, topic: str) -> type[TopicSpi] | type[PrefixTopicSpi] | None:
        # 精确匹配
        spi = cls._spis.get(topic)
        if spi is not None:
            return spi
        # 前缀匹配
        for prefix, spi_class in cls._prefix_spis.items():
            if topic.startswith(prefix):
                return spi_class
        return None

    @classmethod
    def get_job_key(cls, topic: str) -> str | None:
        """返回 job 调度用的 key：精确 topic 用 topic 本身，前缀匹配用 prefix

        scheduler 用此 key 实现「前缀 SPI 单例 job」——同一前缀下所有 topic 共用一个 job。
        """
        if topic in cls._spis:
            return topic
        for prefix in cls._prefix_spis:
            if topic.startswith(prefix):
                return prefix
        return None

    @classmethod
    def get_prefix_spi(cls, prefix: str) -> type[PrefixTopicSpi] | None:
        return cls._prefix_spis.get(prefix)

    @classmethod
    def get_all(cls) -> list[type[TopicSpi] | type[PrefixTopicSpi]]:
        return list(cls._spis.values()) + list(cls._prefix_spis.values())

    @classmethod
    def get_spi_names(cls) -> list[str]:
        return list(cls._spis.keys()) + list(cls._prefix_spis.keys())


def register_spi(spi_class: type[TopicSpi]) -> type[TopicSpi]:
    """精确 SPI 装饰器，直接 @register_spi 使用"""
    SpiRegistry.register(spi_class)
    return spi_class


def register_prefix_spi(spi_class: type[PrefixTopicSpi]) -> type[PrefixTopicSpi]:
    """前缀 SPI 装饰器，直接 @register_prefix_spi 使用"""
    SpiRegistry.register_prefix(spi_class)
    return spi_class
