import re


def chunk_text(notes: str) -> list[str]:
    # Strip follow-up tasks section
    notes = re.split(r"(?im)^follow-up tasks:", notes)[0]

    lines = notes.splitlines()

    # Detect topic headers: lines with NO leading whitespace that end with ":"
    # (lines with leading whitespace ending with ":" are content, not headers)
    # "Meeting notes:" is excluded — it is a document-level label, not a topic
    def is_topic_header(line: str) -> bool:
        stripped = line.rstrip()
        if stripped.lower() == "meeting notes:":
            return False
        return bool(line) and not line[0].isspace() and stripped.endswith(":")

    topic_indices = [i for i, line in enumerate(lines) if is_topic_header(line)]

    if not topic_indices:
        return [notes.strip()]

    chunks = []
    for pos, start in enumerate(topic_indices):
        end = topic_indices[pos + 1] if pos + 1 < len(topic_indices) else len(lines)
        chunk = "\n".join(lines[start:end]).strip()
        if chunk:
            chunks.append(chunk)

    return chunks
