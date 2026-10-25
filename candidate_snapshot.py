#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

AI_CANDIDATE_MIN_SCORE = 4
AI_CANDIDATE_LIMIT_PER_MARKET = 30
AI_CANDIDATE_EXCERPT_CHARS = 600

_TITLE_RULES = (
    ("llm", re.compile(r"\b(?:llm|large language model)s?\b", re.IGNORECASE), 5),
    ("genai", re.compile(r"\b(?:genai|generative ai|generative artificial intelligence)\b", re.IGNORECASE), 5),
    ("ai", re.compile(r"\b(?:ai|artificial intelligence)\b", re.IGNORECASE), 4),
    ("ml", re.compile(r"\b(?:machine learning|ml)\b", re.IGNORECASE), 4),
    ("agent", re.compile(r"\b(?:agentic|ai agent|llm agent|agent engineer|agent researcher|agent scientist)\b", re.IGNORECASE), 4),
    ("nlp", re.compile(r"\b(?:nlp|natural language processing)\b", re.IGNORECASE), 4),
    ("deep_learning", re.compile(r"\bdeep learning\b", re.IGNORECASE), 4),
    ("computer_vision", re.compile(r"\b(?:computer vision|vision language|vision-language)\b", re.IGNORECASE), 4),
    ("applied_scientist", re.compile(r"\bapplied scientist\b", re.IGNORECASE), 4),
    ("research", re.compile(r"\b(?:research engineer|research scientist|ai researcher|ml researcher|machine learning researcher)\b", re.IGNORECASE), 2),
    ("data_science", re.compile(r"\bdata scientist\b", re.IGNORECASE), 2),
)

_JD_RULES = (
    ("llm", re.compile(r"\b(?:llm|large language model)s?\b", re.IGNORECASE)),
    ("genai", re.compile(r"\b(?:genai|generative ai|generative artificial intelligence)\b", re.IGNORECASE)),
    ("machine_learning", re.compile(r"\bmachine learning\b", re.IGNORECASE)),
    ("deep_learning", re.compile(r"\bdeep learning\b", re.IGNORECASE)),
    ("agent", re.compile(r"\b(?:agentic|ai agents?|llm agents?|multi-agent|tool calling)\b", re.IGNORECASE)),
    ("rag", re.compile(r"\b(?:rag|retrieval[- ]augmented generation)\b", re.IGNORECASE)),
    ("retrieval", re.compile(r"\b(?:semantic search|vector search|retrieval|rerank(?:er|ing)?)\b", re.IGNORECASE)),
    ("nlp", re.compile(r"\b(?:nlp|natural language processing)\b", re.IGNORECASE)),
    ("multimodal", re.compile(r"\bmultimodal\b", re.IGNORECASE)),
    ("computer_vision", re.compile(r"\bcomputer vision\b", re.IGNORECASE)),
    ("pytorch", re.compile(r"\bpytorch\b", re.IGNORECASE)),
    ("tensorflow", re.compile(r"\btensorflow\b", re.IGNORECASE)),
    ("transformer", re.compile(r"\btransformers?\b", re.IGNORECASE)),
    ("fine_tuning", re.compile(r"\b(?:fine[- ]tun(?:e|ing)|sft|lora|qlora)\b", re.IGNORECASE)),
    ("model_training", re.compile(r"\b(?:model training|train(?:ing)? models?|post[- ]training)\b", re.IGNORECASE)),
    ("evaluation", re.compile(r"\b(?:llm evaluation|model evaluation|agent evaluation|evals?|benchmarking)\b", re.IGNORECASE)),
    ("vector_db", re.compile(r"\b(?:vector database|vector db|embeddings?)\b", re.IGNORECASE)),
)


def _norm(value: object) -> str:
    return " ".join(str(value or "").split())


def ai_relevance(job: dict) -> tuple[int, list[str]]:
    title = _norm(job.get("title"))
    description = _norm(job.get("description"))
    category = str(job.get("category") or "").strip().lower()

    score = 0
    signals: list[str] = []
    for name, pattern, weight in _TITLE_RULES:
        if pattern.search(title):
            score += weight
            signals.append(f"title:{name}")

    if category in {"ai_engineering", "ml_ai"}:
        score += 2
        signals.append(f"category:{category}")
    elif category == "data_science":
        score += 1
        signals.append("category:data_science")

    jd_hits = 0
    for name, pattern in _JD_RULES:
        if pattern.search(description):
            jd_hits += 1
            signals.append(f"jd:{name}")
    score += min(jd_hits, 6)
    return score, signals


def _identity(job: dict) -> str:
    slug = _norm(job.get("public_slug")).lower()
    if slug:
        return slug
    raw = "|".join(
        _norm(value).lower()
        for value in (
            job.get("company_name") or job.get("company"),
            job.get("title"),
            job.get("location"),
            job.get("external_id") or job.get("source_job_id") or job.get("source_url"),
        )
    )
    return "fallback:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _source_url(job: dict) -> object:
    return job.get("url") or job.get("source_url") or job.get("apply_url") or job.get("application_url")


def _candidate(job: dict, market: str, score: int, signals: list[str]) -> dict:
    enrichment = job.get("enrichment") if isinstance(job.get("enrichment"), dict) else {}
    description = _norm(job.get("description"))
    slug = job.get("public_slug")
    return {
        "identity": _identity(job),
        "market": market,
        "public_slug": slug,
        "company": job.get("company_name") or job.get("company"),
        "title": job.get("title"),
        "location": job.get("location"),
        "source": job.get("source"),
        "external_id": job.get("external_id") or job.get("source_job_id"),
        "source_url": _source_url(job),
        "freehire_url": f"https://freehire.me/jobs/{slug}" if slug else None,
        "created_at": job.get("created_at"),
        "posted_at": job.get("posted_at"),
        "employment_type": enrichment.get("employment_type") or job.get("employment_type"),
        "flags": list(job.get("_flags") or []),
        "ai_score": score,
        "ai_signals": signals,
        "description_excerpt": description[:AI_CANDIDATE_EXCERPT_CHARS],
    }


def build_candidate_snapshot(
    market_jobs: dict[str, list[dict]],
    generated_at: str,
    mode: str,
    limit_per_market: int = AI_CANDIDATE_LIMIT_PER_MARKET,
) -> dict:
    if limit_per_market < 1:
        raise ValueError("limit_per_market must be >= 1")

    candidates: list[dict] = []
    counts: dict[str, int] = {}
    matched_counts: dict[str, int] = {}
    for market in ("SG", "CN", "MY"):
        matched: list[dict] = []
        seen: set[str] = set()
        for job in market_jobs.get(market, []):
            identity = _identity(job)
            if identity in seen:
                continue
            seen.add(identity)
            score, signals = ai_relevance(job)
            if score < AI_CANDIDATE_MIN_SCORE:
                continue
            matched.append(_candidate(job, market, score, signals))

        matched.sort(
            key=lambda item: (
                int(item.get("ai_score") or 0),
                str(item.get("posted_at") or item.get("created_at") or ""),
            ),
            reverse=True,
        )
        matched_counts[market] = len(matched)
        selected = matched[:limit_per_market]
        counts[market] = len(selected)
        candidates.extend(selected)

    return {
        "generated_at": generated_at,
        "mode": mode,
        "min_score": AI_CANDIDATE_MIN_SCORE,
        "limit_per_market": limit_per_market,
        "count": len(candidates),
        "counts": counts,
        "matched_counts": matched_counts,
        "candidates": candidates,
    }


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def write_candidate_snapshot(root: Path, snapshot: dict) -> None:
    _atomic_write_text(
        root / "feed" / "candidates.json",
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
    )
