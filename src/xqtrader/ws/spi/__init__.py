"""SPI基类与注册中心"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class TopicSpi(ABC):
    """Topic SPI基类"""

    @property
    @abstractmethod
    def topic_name(self) -> str:
        pass

    @abstractmethod
    def execute(self) -> Any:
        pass


class SpiRegistry:
    """SPI注册中心"""

    _spis: dict[str, type[TopicSpi]] = {}

    @classmethod
    def register(cls, spi_class: type[TopicSpi]) -> None:
        instance = spi_class()
        cls._spis[instance.topic_name] = spi_class

    @classmethod
    def get(cls, topic: str) -> type[TopicSpi] | None:
        return cls._spis.get(topic)

    @classmethod
    def get_all(cls) -> list[type[TopicSpi]]:
        return list(cls._spis.values())

    @classmethod
    def get_spi_names(cls) -> list[str]:
        return list(cls._spis.keys())


def register_spi(spi_class: type[TopicSpi]) -> type[TopicSpi]:
    """SPI装饰器，直接 @register_spi 使用"""
    SpiRegistry.register(spi_class)
    return spi_class
