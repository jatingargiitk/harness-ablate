import re
import unicodedata


def slugify(text: str) -> str:
    """'Hello, World!' -> 'hello-world'."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "-", text.lower())
