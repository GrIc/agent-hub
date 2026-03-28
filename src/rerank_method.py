def rerank(
        self,
        query: str,
        documents: list[str],
        model: Optional[str] = None,
        top_k: int = 8,
    ) -> list[dict]:
        """
        Rerank documents using a cross-encoder model via the API.

        Tries /v1/rerank (vLLM/TEI/LiteLLM). Uses "texts" field first,
        falls back to "documents" on 400.

        Cross-encoder models have strict limits (~512 tokens per doc).
        We cap at 10 documents to avoid server OOM/500 errors.

        Returns list of {index, score} sorted by score descending.
        Falls back gracefully to identity ranking on any failure.
        """
        model = model or ""
        if not model:
            logger.debug("[Rerank] No rerank model configured, skipping")
            return [{"index": i, "score": 1.0} for i in range(len(documents))]

        # Hard cap: cross-encoder models choke on too many documents
        MAX_RERANK_DOCS = 10
        MAX_RERANK_CHARS = 800  # Shorter to stay within model context
        capped = documents[:MAX_RERANK_DOCS]
        truncated = [d[:MAX_RERANK_CHARS] for d in capped]

        logger.info(
            f"[Rerank] model={model}, query_len={len(query)}, "
            f"docs={len(truncated)}/{len(documents)}, top_k={top_k}"
        )

        url = f"{self.base_url}/rerank"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Try "texts" first (vLLM/TEI), then "documents" (Cohere)
        for field_name in ("texts", "documents"):
            payload = {
                "model": model,
                "query": query[:MAX_RERANK_CHARS],
                field_name: truncated,
                "top_n": min(top_k, len(truncated)),
            }

            try:
                with httpx.Client(timeout=30.0, verify=False) as http:
                    resp = http.post(url, json=payload, headers=headers)

                    if resp.status_code == 400:
                        logger.debug(
                            f"[Rerank] '{field_name}' rejected (400), trying next format"
                        )
                        continue  # Try next field name

                    if resp.status_code >= 500:
                        # Server error — don't retry, just fall back
                        logger.warning(
                            f"[Rerank] Server error {resp.status_code} "
                            f"with {len(truncated)} docs, falling back. "
                            f"Body: {resp.text[:200]}"
                        )
                        return [
                            {"index": i, "score": 1.0}
                            for i in range(min(len(documents), top_k))
                        ]

                    resp.raise_for_status()
                    data = resp.json()

                # Parse response
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
                # Already handled above for 400/500
                continue
            except Exception as e:
                logger.warning(f"[Rerank] Error with '{field_name}': {e}")
                continue

        # All formats failed — graceful fallback
        logger.warning("[Rerank] All formats failed, using embedding scores")
        return [
            {"index": i, "score": 1.0}
            for i in range(min(len(documents), top_k))
        ]