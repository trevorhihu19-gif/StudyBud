import re

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_IMAGE_MARKDOWN = re.compile(r"!\[[^\]]*\]\([^)]*\)")

def clean_text(value: str) -> str:
    value = _CONTROL_CHARS.sub("", value).strip()
    if not value:
        raise ValueError("Text cannot be empty")
    return value

def clean_generated(text: str, limit: int) -> str:
    """Make text written by the AI safe to store and show.

    Removes hidden control characters and markdown images (a trick used to leak
    data through image links), trims spaces, and cuts the text to `limit` characters.

    Args:
        text: Raw text produced by the model.
        limit: Maximum number of characters to keep.

    Returns:
        The cleaned, shortened text. May be empty.
    """
    return _IMAGE_MARKDOWN.sub("", _CONTROL_CHARS.sub("", text)).strip()[:limit]