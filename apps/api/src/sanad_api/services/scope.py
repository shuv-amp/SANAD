SCOPE_NONE = "__none__"


def normalize_scope(value: str | None) -> str:
    cleaned = (value or "").strip()
    return cleaned if cleaned else SCOPE_NONE


def display_scope(value: str | None) -> str | None:
    return None if value in (None, SCOPE_NONE, "") else value

