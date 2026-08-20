"""Presentation rules for Plugin Studio's Codex activity stream."""


HIDDEN_CODEX_LOG_CATEGORIES = frozenset({"COMMAND", "PROPOSED CHANGES"})


def should_display_codex_log(category):
    """Return whether an activity category belongs in the user-facing log."""
    normalized = str(category).strip().upper()
    return normalized not in HIDDEN_CODEX_LOG_CATEGORIES
