import os
from openai import AzureOpenAI
from ai_templates import build_prompt


def analyze_notes(notes: str) -> str:
    client = AzureOpenAI(
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_version="2024-12-01-preview",
    )

    response = client.chat.completions.create(
        model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        messages=[{"role": "user", "content": build_prompt(notes)}],
        max_tokens=1024,
    )

    return response.choices[0].message.content
