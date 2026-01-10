"""OpenAI API client for chat completions."""

import logging

import requests
from pydantic import BaseModel

from config import CONFIG

logger = logging.getLogger(__name__)

COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
REQUEST_TIMEOUT_SECONDS = 30


class ChatMessage(BaseModel):
    """A single message in a chat completion response."""

    role: str
    content: str


class ChatChoice(BaseModel):
    """A completion choice returned by the API."""

    message: ChatMessage


class ChatCompletionResponse(BaseModel):
    """Response from the OpenAI chat completions endpoint."""

    choices: list[ChatChoice]


def openai_completion(user: str, system: str) -> str:
    """Send a chat completion request to OpenAI and return the response content."""
    logger.debug("Calling OpenAI API with model %s", CONFIG.openai_model)

    headers = {
        "Authorization": f"Bearer {CONFIG.openai_api_key}",
        "Content-Type": "application/json",
    }

    data = {
        "model": CONFIG.openai_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }

    response = requests.post(
        COMPLETIONS_URL, headers=headers, json=data, timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()

    result = ChatCompletionResponse.model_validate(response.json())
    logger.debug("OpenAI API response received")
    return result.choices[0].message.content
