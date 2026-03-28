"""
Resilient OpenAI-compatible client with aggressive retry logic.
Handles 500, 502, 503, 429 with exponential backoff + jitter.

Supports automatic response completion when finish_reason == "length":
    client.chat(..., complete=True)

Supports cross-encoder reranking via /rerank endpoint:
    client.rerank(query, documents, model=...)
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
        complete: bool = False,
        max_completion_attempts: int = 5,
        **kwargs,
    ) -> str:
        """
        Send a chat completion with retries and optional model fallback.

        Args:
            complete: If True, automatically continue the request when the model
                      stops due to max_tokens (finish_reason == "length"), until
                      the response is naturally complete or max_completion_attempts
                      is reached. Useful for long document generation tasks.
            max_completion_attempts: Maximum number of continuation rounds when
                                     complete=True (default: 5).
        """
        models_to_try = [model] + (fallback_models or [])

        total_chars = sum(len(m.get("content", "")) for m in messages)
        logger.info(
            f"[Chat] model={model}, messages={len(messages)}, "
            f"total_chars={total_chars}, temperature={temperature}, complete={complete}"
        )

        for i, current_model in enumerate(models_to_try):
            try:
                content, finish_reason = self._chat_with_retry(
                    messages=messages,
                    model=current_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )

                if complete and finish_reason == "length":
                    content = self._complete_response(
                        messages=messages,
                        model=current_model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        partial=content,
                        max_attempts=max_completion_attempts,
                        **kwargs,
                    )

                return content

            except Exception as e:
                if i < len(models_to_try) - 1:
                    logger.warning(
                        f"[Chat] Model {current_model} failed: {_format_error(e)}. "
                        f"Falling back to {models_to_try[i+1]}"
                    )
                else:
                    logger.error(f"[Chat] All models exhausted. Last error: {_format_error(e)}")
                    raise

    def _complete_response(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
        partial: str,
        max_attempts: int,
        **kwargs,
    ) -> str:
        """
        Continue a truncated response (finish_reason == "length") until the model
        stops naturally or max_attempts is exhausted.
        """
        full_content = partial

        for attempt in range(max_attempts):
            logger.warning(
                f"[Chat] Response truncated (finish_reason=length) — "
                f"continuation {attempt + 1}/{max_attempts} "
                f"(accumulated: {len(full_content)} chars)"
            )

            continuation_messages = list(messages) + [
                {"role": "assistant", "content": full_content},
                {
                    "role": "user",
                    "content": (
                        "Continue your response from where you left off. "
                        "Do not repeat or summarize what you have already written, "
                        "just continue seamlessly."
                    ),
                },
            ]

            chunk, finish_reason = self._chat_with_retry(
                messages=continuation_messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

            full_content += chunk

            if finish_reason != "length":
                logger.info(
                    f"[Chat] Response completed after {attempt + 1} continuation(s) "
                    f"(finish_reason={finish_reason}, total={len(full_content)} chars)"
                )
                break
        else:
            logger.warning(
                f"[Chat] Response still incomplete after {max_attempts} continuations "
                f"(total={len(full_content)} chars). Consider increasing max_tokens."
            )

        return full_content

    def _chat_with_retry(
        self,
        messages: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs,
    ) -> tuple[str, str]:
        """
        Send a single chat request with exponential-backoff retry.

        Returns:
            (content, finish_reason) — finish_reason is "stop", "length",
            "tool_calls", "content_filter", or "stop" when unknown.
        """
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
                finish_reason = resp.choices[0].finish_reason or "stop"

                if finish_reason == "length":
                    logger.warning(
                        f"[Chat] finish_reason=length — response cut at {len(content)} chars "
                        f"(max_tokens={max_tokens}). Use complete=True to continue automatically."
                    )
                else:
                    logger.debug(f"[Chat] OK: {len(content)} chars, finish_reason={finish_reason}")

                return content, finish_reason

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

        # Truncate texts for embedding models (~750 tokens ~ 3000 chars)
        MAX_CHARS = 3000
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

    # ── Reranking ──────────────────────────────────────────────────────

    def rerank(
        self,
        query: str,
        documents: list[str],
        model: Optional[str] = None,
        top_k: int = 8,
    ) -> list[dict]:
        """
        Rerank documents using a cross-encoder model via /v1/rerank.

        - Caps at 10 documents (cross-encoders OOM with too many).
        - Truncates each doc to 800 chars.
        - Tries "texts" field first (vLLM/TEI), then "documents" (Cohere) on 400.
        - Falls back IMMEDIATELY on 500 (no retry — it's server OOM, not transient).
        - Returns list of {index, score} sorted by score descending.
        """
        model = model or ""
        if not model:
            return [{"index": i, "score": 1.0} for i in range(len(documents))]

        # Hard caps to prevent server OOM
        MAX_DOCS = 10
        MAX_CHARS = 800
        capped = documents[:MAX_DOCS]
        truncated = [d[:MAX_CHARS] for d in capped]

        logger.info(
            f"[Rerank] model={model}, query_len={len(query)}, "
            f"docs={len(truncated)}/{len(documents)}, top_k={top_k}"
        )

        url = f"{self.base_url}/rerank"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Try both field names: vLLM/TEI uses "texts", Cohere uses "documents"
        for field_name in ("texts", "documents"):
            payload = {
                "model": model,
                "query": query[:MAX_CHARS],
                field_name: truncated,
                "top_n": min(top_k, len(truncated)),
            }

            try:
                with httpx.Client(timeout=30.0, verify=False) as http:
                    resp = http.post(url, json=payload, headers=headers)

                # 400 = wrong field name, try the other one
                if resp.status_code == 400:
                    logger.debug(
                        f"[Rerank] '{field_name}' rejected (400), trying next format"
                    )
                    continue

                # 500+ = server OOM or crash — DON'T retry, fall back immediately
                if resp.status_code >= 500:
                    logger.warning(
                        f"[Rerank] Server error {resp.status_code} with "
                        f"{len(truncated)} docs — falling back to embedding scores"
                    )
                    return [
                        {"index": i, "score": 1.0}
                        for i in range(min(len(documents), top_k))
                    ]

                resp.raise_for_status()
                data = resp.json()

                # Parse — vLLM: {"data": [...]}, Cohere: {"results": [...]}
                results = data.get("results", data.get("data", []))
                ranked = []
                for item in results:
                    idx = item.get("index", item.get("document_index", 0))
                    score = item.get("relevance_score", item.get("score", 0.0))
                    ranked.append({"index": idx, "score": score})

                ranked.sort(key=lambda x: x["score"], reverse=True)
                if ranked:
                    logger.info(
                        f"[Rerank] OK ({field_name}): {len(ranked)} results, "
                        f"top={ranked[0]['score']:.3f}"
                    )
                return ranked[:top_k]

            except httpx.HTTPStatusError:
                # Already handled 400/500 above
                continue
            except Exception as e:
                logger.warning(f"[Rerank] Error with '{field_name}': {e}")
                continue

        # All field formats failed
        logger.warning("[Rerank] All formats failed, using embedding scores")
        return [
            {"index": i, "score": 1.0}
            for i in range(min(len(documents), top_k))
        ]
