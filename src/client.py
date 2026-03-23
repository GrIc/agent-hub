"""
Resilient OpenAI-compatible client with aggressive retry logic.
Handles 500, 502, 503, 429 with exponential backoff + jitter.
"""

import os
import time
import random
import logging
from typing import Optional

import httpx
from openai import OpenAI

logger = logging.getLogger(__name__)


def _is_retryable(exc: Exception) -> bool:
    """Determine if an exception is retryable."""
    exc_str = str(exc).lower()
    for code in ("500", "502", "503", "429", "timeout", "connection", "remoteprotocol"):
        if code in exc_str:
            return True
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError)):
        return True
    return False


def _format_error(e: Exception) -> str:
    """Extract maximum detail from an exception."""
    parts = [f"{type(e).__name__}: {e}"]

    if hasattr(e, "status_code"):
        parts.append(f"HTTP status: {e.status_code}")
    if hasattr(e, "response") and e.response is not None:
        try:
            parts.append(f"Response body: {e.response.text[:500]}")
        except Exception:
            pass
    if hasattr(e, "request") and e.request is not None:
        try:
            parts.append(f"Request URL: {e.request.url}")
            parts.append(f"Request method: {e.request.method}")
        except Exception:
            pass

    if isinstance(e, httpx.HTTPStatusError):
        parts.append(f"Response: {e.response.status_code} {e.response.text[:300]}")

    return " | ".join(parts)


class ResilientClient:
    """OpenAI client wrapper with built-in retry & fallback model logic."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_retries: int = 8,
        base_delay: float = 2.0,
        max_delay: float = 120.0,
        timeout: float = 180.0,
    ):
        self.api_key = api_key or os.getenv("API_KEY", "")
        self.base_url = base_url or os.getenv("API_BASE_URL", "")
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

        masked_key = self.api_key[:8] + "..." if len(self.api_key) > 8 else "***"
        logger.info(f"[Client] base_url = {self.base_url}")
        logger.info(f"[Client] api_key  = {masked_key}")
        logger.info(f"[Client] timeout  = {timeout}s, max_retries = {max_retries}")

        http_client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=30.0),
            limits=httpx.Limits(max_connections=5),
            verify=False,  # For internal APIs with self-signed certs
        )

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            http_client=http_client,
            max_retries=0,  # We handle retries ourselves
        )

        logger.info(f"[Client] OpenAI client initialized -> {self.base_url}")

    def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.5,
        max_tokens: int = 4096,
        fallback_models: Optional[list[str]] = None,
        **kwargs,
    ) -> str:
        """Send a chat completion with retries and optional model fallback."""
        models_to_try = [model] + (fallback_models or [])

        total_chars = sum(len(m.get("content", "")) for m in messages)
        logger.info(
            f"[Chat] model={model}, messages={len(messages)}, "
            f"total_chars={total_chars}, temperature={temperature}"
        )

        for i, current_model in enumerate(models_to_try):
            try:
                return self._chat_with_retry(
                    messages=messages,
                    model=current_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            except Exception as e:
                if i < len(models_to_try) - 1:
                    logger.warning(
                        f"[Chat] Model {current_model} failed: {_format_error(e)}. "
                        f"Falling back to {models_to_try[i+1]}"
                    )
                else:
                    logger.error(f"[Chat] All models exhausted. Last error: {_format_error(e)}")
                    raise

    def _chat_with_retry(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs,
    ) -> str:
        last_exc = None
        for attempt in range(self.max_retries):
            try:
                logger.debug(
                    f"[Chat] Attempt {attempt+1}/{self.max_retries} -> "
                    f"POST {self.base_url}/chat/completions model={model}"
                )
                resp = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
                content = resp.choices[0].message.content or ""
                logger.debug(f"[Chat] OK: {len(content)} chars")
                return content
            except Exception as e:
                last_exc = e
                retryable = _is_retryable(e)
                detail = _format_error(e)

                if not retryable:
                    logger.error(
                        f"[Chat] Non-retryable error on attempt {attempt+1}: {detail}"
                    )
                    raise

                delay = min(
                    self.base_delay * (2 ** attempt) + random.uniform(0, 1),
                    self.max_delay,
                )
                logger.warning(
                    f"[Chat] Attempt {attempt+1}/{self.max_retries} failed: {detail} "
                    f"-- retrying in {delay:.1f}s"
                )
                time.sleep(delay)

        raise RuntimeError(
            f"All {self.max_retries} attempts failed for model {model}: {_format_error(last_exc)}"
        ) from last_exc

    def embed(
        self,
        texts: list[str],
        model: Optional[str] = None,
    ) -> list[list[float]]:
        """Get embeddings with retry logic."""
        model = model or os.getenv("MODEL_EMBED", "")
        if not model:
            raise ValueError("No embedding model configured. Set 'models.embed' in config.yaml or MODEL_EMBED env var.")

        # Truncate texts for 512-token context models (~1800 chars ~ 450 tokens)
        MAX_CHARS = 1800
        truncated = [t[:MAX_CHARS] if len(t) > MAX_CHARS else t for t in texts]

        total_chars = sum(len(t) for t in truncated)
        logger.info(
            f"[Embed] model={model}, texts={len(truncated)}, "
            f"total_chars={total_chars}, "
            f"avg_chars={total_chars // max(len(truncated), 1)}"
        )

        all_embeddings = []
        batch_size = 8
        for i in range(0, len(truncated), batch_size):
            batch = truncated[i : i + batch_size]
            batch_chars = sum(len(t) for t in batch)
            logger.debug(
                f"[Embed] Batch {i//batch_size + 1}: {len(batch)} texts, {batch_chars} chars"
            )
            emb = self._embed_with_retry(batch, model)
            all_embeddings.extend(emb)

        logger.info(f"[Embed] OK: {len(all_embeddings)} embeddings")
        return all_embeddings

    def _embed_with_retry(
        self, texts: list[str], model: str
    ) -> list[list[float]]:
        last_exc = None
        for attempt in range(self.max_retries):
            try:
                logger.debug(
                    f"[Embed] Attempt {attempt+1}/{self.max_retries} -> "
                    f"POST {self.base_url}/embeddings model={model} "
                    f"texts={len(texts)} chars={sum(len(t) for t in texts)}"
                )
                resp = self.client.embeddings.create(
                    model=model,
                    input=texts,
                )
                dims = len(resp.data[0].embedding) if resp.data else 0
                logger.debug(
                    f"[Embed] OK: {len(resp.data)} embeddings, dim={dims}"
                )
                return [item.embedding for item in resp.data]
            except Exception as e:
                last_exc = e
                retryable = _is_retryable(e)
                detail = _format_error(e)

                if not retryable:
                    logger.error(
                        f"[Embed] Non-retryable error on attempt {attempt+1}: {detail}"
                    )
                    raise

                delay = min(
                    self.base_delay * (2 ** attempt) + random.uniform(0, 1),
                    self.max_delay,
                )
                logger.warning(
                    f"[Embed] Attempt {attempt+1}/{self.max_retries} failed: {detail} "
                    f"-- retrying in {delay:.1f}s"
                )
                time.sleep(delay)

        logger.error(
            f"[Embed] All {self.max_retries} attempts failed: {_format_error(last_exc)}"
        )
        raise RuntimeError(
            f"Embedding failed after {self.max_retries} retries: {_format_error(last_exc)}"
        ) from last_exc
