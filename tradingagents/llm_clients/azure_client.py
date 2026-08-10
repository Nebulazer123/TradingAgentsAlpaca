import os
from typing import Any

from langchain_openai import AzureChatOpenAI

from .base_client import BaseLLMClient, normalize_content

_PASSTHROUGH_KWARGS = (
    "timeout", "request_timeout", "max_retries", "api_key", "reasoning_effort",
    "max_tokens",
    "callbacks", "http_client", "http_async_client",
)


def _first_config_value(kwargs: dict[str, Any], *keys: str, env: str | None = None) -> str | None:
    for key in keys:
        value = kwargs.get(key)
        if value:
            return str(value)
    if env:
        value = os.environ.get(env)
        if value:
            return value
    return None


class NormalizedAzureChatOpenAI(AzureChatOpenAI):
    """AzureChatOpenAI with normalized content output."""

    def invoke(self, input, config=None, **kwargs):
        return normalize_content(super().invoke(input, config, **kwargs))


class AzureOpenAIClient(BaseLLMClient):
    """Client for Azure OpenAI deployments.

    Requires environment variables:
        AZURE_OPENAI_API_KEY: API key
        AZURE_OPENAI_ENDPOINT: Endpoint URL (e.g. https://<resource>.openai.azure.com/)
        AZURE_OPENAI_DEPLOYMENT_NAME: Deployment name
        OPENAI_API_VERSION: API version (e.g. 2025-03-01-preview)
    """

    def __init__(self, model: str, base_url: str | None = None, **kwargs):
        super().__init__(model, base_url, **kwargs)

    def get_llm(self) -> Any:
        """Return configured AzureChatOpenAI instance."""
        self.warn_if_unknown_model()

        azure_deployment = _first_config_value(
            self.kwargs,
            "azure_deployment",
            "deployment_name",
            env="AZURE_OPENAI_DEPLOYMENT_NAME",
        ) or self.model
        azure_endpoint = self.base_url or _first_config_value(
            self.kwargs,
            "azure_endpoint",
            "endpoint",
            env="AZURE_OPENAI_ENDPOINT",
        )
        api_version = _first_config_value(
            self.kwargs,
            "api_version",
            "openai_api_version",
            env="OPENAI_API_VERSION",
        )
        missing = []
        if not azure_endpoint:
            missing.append("AZURE_OPENAI_ENDPOINT")
        if not api_version:
            missing.append("OPENAI_API_VERSION")
        if not azure_deployment:
            missing.append("AZURE_OPENAI_DEPLOYMENT_NAME")
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"Azure OpenAI client is missing required configuration: {joined}")

        llm_kwargs = {
            "model": self.model,
            "azure_deployment": azure_deployment,
            "azure_endpoint": azure_endpoint,
            "api_version": api_version,
        }

        for key in _PASSTHROUGH_KWARGS:
            if key in self.kwargs:
                target_key = "request_timeout" if key == "timeout" else key
                llm_kwargs[target_key] = self.kwargs[key]

        return NormalizedAzureChatOpenAI(**llm_kwargs)

    def validate_model(self) -> bool:
        """Azure accepts any deployed model name."""
        return True
