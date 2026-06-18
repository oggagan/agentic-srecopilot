"""Provider agnostic chat model factory.

Nodes ask for a role ("chat" for cheap work, "reasoner" for hard diagnosis) and get a
LangChain chat model back. The provider is selected by config, so swapping DeepSeek for
Claude or Bedrock later is a config change, not a code change.
"""
from langchain_core.language_models.chat_models import BaseChatModel

from app.config import settings


def get_chat_model(role: str = "chat", temperature: float = 0.0) -> BaseChatModel:
    provider = settings.llm_provider.lower()

    if provider == "deepseek":
        from langchain_openai import ChatOpenAI

        model = (
            settings.deepseek_reasoner_model
            if role == "reasoner"
            else settings.deepseek_model
        )
        return ChatOpenAI(
            model=model,
            base_url=settings.deepseek_base_url,
            api_key=settings.deepseek_api_key,
            temperature=temperature,
            timeout=60,
            max_retries=2,
        )

    if provider == "anthropic":
        raise NotImplementedError("anthropic provider is wired in the Product phase")
    if provider == "bedrock":
        raise NotImplementedError("bedrock provider is wired in the Product phase")

    raise ValueError(f"unknown LLM_PROVIDER: {settings.llm_provider}")
