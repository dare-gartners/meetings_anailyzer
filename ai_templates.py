def build_prompt(notes: str, title: str = "") -> str:
    return f"""You are an assistant that processes meeting notes.

Given the following meeting notes (which may be in any language), return a JSON object in English with:
- summary: a short summary of the meeting
- action_items: a list of action items
- tags: a list of relevant tags

Respond with valid JSON only.

Meeting title: {title}
Meeting notes:
{notes}"""
