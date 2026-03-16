import os
import re
import json
import numpy as np
from openai import AzureOpenAI
from ai_templates import build_prompt

TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _client() -> AzureOpenAI:
    return AzureOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_version="2024-12-01-preview",
    )


def analyze_notes(notes: str, title: str = "") -> str:
    response = _client().chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        messages=[{"role": "user", "content": build_prompt(notes, title)}],
        max_tokens=1024,
    )
    return response.choices[0].message.content


def generate_description(chunk: str) -> str:
    prompt = (
        "Summarize the following topic from a meeting in 1-2 sentences. "
        "Focus on what was discussed or decided. Do not start with 'This meeting'.\n\n"
        f"{chunk}"
    )
    response = _client().chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        messages=[{"role": "user", "content": prompt}],
        max_tokens=128,
    )
    return response.choices[0].message.content.strip()


def generate_embedding(text: str) -> bytes:
    response = _client().embeddings.create(
        model=os.environ["AZURE_OPENAI_EMBEDDING_DEPLOYMENT"],
        input=text,
    )
    vector = np.array(response.data[0].embedding, dtype=np.float32)
    return vector.tobytes()


def generate_tags(chunk: str, existing_tags: list[str]) -> list[str]:
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
    return [t for t in tags if isinstance(t, str) and TAG_PATTERN.match(t)]
