import os
import re
import json
import time
import logging
import numpy as np
from openai import AzureOpenAI
from ai_templates import build_prompt

TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
logger = logging.getLogger(__name__)


def _client() -> AzureOpenAI:
    return AzureOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_version="2024-12-01-preview",
    )


def analyze_notes(notes: str, title: str = "") -> str:
    t0 = time.perf_counter()
    response = _client().chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        messages=[{"role": "user", "content": build_prompt(notes, title)}],
        max_tokens=1024,
    )
    logger.info("llm:analyze_notes done %.0fms", (time.perf_counter() - t0) * 1000)
    return response.choices[0].message.content


def generate_description(chunk: str) -> str:
    t0 = time.perf_counter()
    prompt = (
        "In up to 3 sentences, describe the specific problem or decision addressed in this topic. "
        "Focus on what is being solved or decided, not the product area or domain it belongs to. "
        "Do not start with 'This meeting', 'This topic', 'The team', or any similar preamble — "
        "start directly with the subject matter. Avoid product names unless essential to the meaning.\n\n"
        f"{chunk}"
    )
    response = _client().chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        messages=[{"role": "user", "content": prompt}],
        max_tokens=192,
    )
    logger.info("llm:generate_description done %.0fms", (time.perf_counter() - t0) * 1000)
    return response.choices[0].message.content.strip()


def verify_match(desc_a: str, desc_b: str) -> bool:
    t0 = time.perf_counter()
    prompt = (
        "Two meeting topics were flagged as semantically similar by an embedding model. "
        "Your job is to decide whether they genuinely discuss the same subject matter — "
        "not merely the same product, team, or domain.\n\n"
        f"Topic A: {desc_a}\n\n"
        f"Topic B: {desc_b}\n\n"
        "Do these two topics discuss the same subject? Answer with only 'yes' or 'no'."
    )
    response = _client().chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        messages=[{"role": "user", "content": prompt}],
        max_tokens=5,
    )
    result = response.choices[0].message.content.strip().lower().startswith("yes")
    logger.info("llm:verify_match done %.0fms result=%s", (time.perf_counter() - t0) * 1000, result)
    return result


def explain_match(source_chunk: str, matched_chunk: str) -> str:
    t0 = time.perf_counter()
    prompt = (
        "Two meeting topics were found to be semantically similar. "
        "In 1-2 sentences, describe what subject matter they had in common. "
        "Start with 'Both meetings discussed...' and focus on the shared topic, not on specific people or names.\n\n"
        f"Topic A:\n{source_chunk}\n\nTopic B:\n{matched_chunk}"
    )
    response = _client().chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        messages=[{"role": "user", "content": prompt}],
        max_tokens=100,
    )
    logger.info("llm:explain_match done %.0fms", (time.perf_counter() - t0) * 1000)
    return response.choices[0].message.content.strip()


def generate_embedding(text: str) -> bytes:
    t0 = time.perf_counter()
    response = _client().embeddings.create(
        model=os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"],
        input=text,
    )
    vector = np.array(response.data[0].embedding, dtype=np.float32)
    logger.info("embedding:generate done %.0fms", (time.perf_counter() - t0) * 1000)
    return vector.tobytes()


def generate_tags(chunk: str, existing_tags: list[str]) -> list[str]:
    t0 = time.perf_counter()
    existing_hint = (
        f"Existing tags (reuse if semantically similar): {', '.join(existing_tags)}"
        if existing_tags
        else "No existing tags yet."
    )
    prompt = f"""Generate up to 3 tags for the following meeting topic chunk.

Rules:
- Lowercase only
- Single words strongly preferred (e.g. "roadmap", "budget", "hiring")
- Hyphenated compound only when a single word is too vague (e.g. "ai-adoption")
- No spaces, no special characters
- Each tag must match: ^[a-z0-9][a-z0-9-]*$
- {existing_hint}
- Prefer reusing an existing tag over creating a near-synonym

Return a JSON array of tag strings only. Example: ["roadmap", "hiring", "ai-adoption"]

Chunk:
{chunk}"""

    response = _client().chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        messages=[{"role": "user", "content": prompt}],
        max_tokens=64,
    )
    raw = response.choices[0].message.content.strip()
    # Strip markdown code fences if present
    raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("` \n")
    tags = json.loads(raw)
    result = [t for t in tags if isinstance(t, str) and TAG_PATTERN.match(t)]
    logger.info("llm:generate_tags done %.0fms tags=%s", (time.perf_counter() - t0) * 1000, result)
    return result
