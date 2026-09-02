from unittest.mock import MagicMock, patch

from src.api.main import build_openai_client, resolve_embedding_dimensions


def test_build_openai_client_uses_azure_endpoint():
    credential = MagicMock()
    credential.get_token.return_value.token = "token"

    with patch("src.api.main.AsyncAzureOpenAI") as mock_client:
        build_openai_client("https://example.openai.azure.com/", credential)

    kwargs = mock_client.call_args.kwargs
    assert kwargs["azure_endpoint"] == "https://example.openai.azure.com"
    assert "base_url" not in kwargs
    assert kwargs["api_version"] == "2024-10-21"
    assert callable(kwargs["azure_ad_token_provider"])


def test_resolve_embedding_dimensions_matches_text_embedding_3_small():
    assert resolve_embedding_dimensions("text-embedding-3-small", None) == 1536
    assert resolve_embedding_dimensions("text-embedding-3-small", "100") == 100
