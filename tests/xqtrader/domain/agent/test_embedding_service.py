"""EmbeddingService 单元测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from xqtrader.domain.agent.services.embedding_service import EmbeddingService


@pytest.fixture(autouse=True)
def _reset_embedding_singleton() -> None:
    EmbeddingService._instance = None
    EmbeddingService._local_model = None
    if EmbeddingService._tei_client is not None:
        EmbeddingService._tei_client.close()
    EmbeddingService._tei_client = None


def test_encode_tei_single_vector() -> None:
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = [[1.0, 0.0, 0.0]]

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.return_value = mock_response
    mock_client.post.return_value = mock_response

    with (
        patch("xqtrader.domain.agent.services.embedding_service.settings") as mock_settings,
        patch(
            "xqtrader.domain.agent.services.embedding_service.httpx.Client",
            return_value=mock_client,
        ),
    ):
        mock_settings.QDRANT.EMBEDDING_BACKEND = "tei"
        mock_settings.QDRANT.EMBEDDING_TEI_BASE_URL = "http://tei.test"
        mock_settings.QDRANT.EMBEDDING_TEI_TIMEOUT_S = 5.0
        mock_settings.QDRANT.EMBEDDING_DIM = 3

        vector = EmbeddingService.get_instance().encode_one("测试文本")

    assert vector == [1.0, 0.0, 0.0]
    mock_client.post.assert_called_once_with("/embed", json={"inputs": ["测试文本"]})


def test_encode_tei_rejects_dim_mismatch() -> None:
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = [[1.0, 0.0]]

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.return_value = mock_response
    mock_client.post.return_value = mock_response

    with (
        patch("xqtrader.domain.agent.services.embedding_service.settings") as mock_settings,
        patch(
            "xqtrader.domain.agent.services.embedding_service.httpx.Client",
            return_value=mock_client,
        ),
    ):
        mock_settings.QDRANT.EMBEDDING_BACKEND = "tei"
        mock_settings.QDRANT.EMBEDDING_TEI_BASE_URL = "http://tei.test"
        mock_settings.QDRANT.EMBEDDING_TEI_TIMEOUT_S = 5.0
        mock_settings.QDRANT.EMBEDDING_DIM = 3

        with pytest.raises(ValueError, match="向量维度"):
            EmbeddingService.get_instance().encode_one("测试")
