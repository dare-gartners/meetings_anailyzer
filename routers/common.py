"""Shared utilities used across multiple routers."""

import re
import numpy as np
from database import Tag, MeetingTag


TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")

_STOP_WORDS = {
    # articles / determiners
    "a", "an", "the",
    # prepositions
    "about", "above", "across", "after", "against", "along", "among", "around",
    "at", "before", "behind", "below", "beneath", "beside", "between", "beyond",
    "by", "down", "during", "except", "for", "from", "in", "inside", "into",
    "near", "of", "off", "on", "onto", "out", "outside", "over", "past", "re",
    "since", "through", "throughout", "till", "to", "toward", "under", "until",
    "up", "upon", "with", "within", "without",
    # conjunctions
    "and", "as", "because", "but", "either", "if", "nor", "once", "or", "since",
    "so", "than", "that", "though", "unless", "until", "when", "where",
    "whether", "while", "yet",
    # pronouns
    "all", "any", "both", "each", "few", "he", "her", "him", "his", "how",
    "i", "it", "its", "me", "more", "most", "my", "neither", "no", "none",
    "not", "nothing", "one", "other", "our", "ours", "she", "some", "such",
    "them", "these", "they", "this", "those", "us", "we", "what", "which",
    "who", "whom", "whose", "why", "you", "your",
    # auxiliary verbs
    "am", "are", "be", "been", "being", "can", "could", "did", "do", "does",
    "doing", "done", "had", "has", "have", "having", "is", "may", "might",
    "must", "shall", "should", "was", "were", "will", "would",
    # common adverbs / fillers
    "again", "also", "always", "already", "away", "back", "else", "even",
    "ever", "here", "just", "maybe", "never", "now", "often", "only",
    "perhaps", "quite", "rather", "really", "same", "still", "then", "there",
    "too", "very", "well",
    # domain fillers specific to this app
    "meeting", "meetings", "regarding", "related", "concerning", "tell",
    "show", "find", "get", "give", "list", "search",
}


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom else 0.0


def _meeting_tags(db, meeting_id: int) -> list[str]:
    rows = (
        db.query(Tag.name)
        .join(MeetingTag, MeetingTag.tag_id == Tag.id)
        .filter(MeetingTag.meeting_id == meeting_id)
        .all()
    )
    return [r.name for r in rows]
