import re

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(value: str) -> str:
    value = _CONTROL_CHARS.sub("", value).strip()
    if not value:
        raise ValueError("Text cannot be empty")
    return value