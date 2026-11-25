import hashlib
import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_TRACKING_KEYS = {
    "fbclid",
    "gclid",
    "yclid",
    "mc_cid",
    "mc_eid",
    "_ga",
    "_gl",
}


def canonicalize_url(value: str) -> str | None:
    """Normalize a web URL while retaining meaningful query parameters."""
    try:
        parsed = urlsplit(value.strip())
        hostname = parsed.hostname
        port = parsed.port
    except (AttributeError, ValueError):
        return None

    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not hostname:
        return None

    host = hostname.encode("idna").decode("ascii").lower()
    if host.startswith("www."):
        host = host[4:]
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"

    query_items = []
    for key, item_value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in _TRACKING_KEYS:
            continue
        query_items.append((key, item_value))
    query_items.sort(key=lambda pair: (pair[0].casefold(), pair[1]))
    path = parsed.path or "/"
    return urlunsplit((scheme, host, path, urlencode(query_items, doseq=True), ""))


def normalized_content_hash(value: str) -> str | None:
    normalized = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE).split())


def title_similarity(left: str, right: str) -> float:
    first = normalize_title(left)
    second = normalize_title(right)
    if not first or not second:
        return 0.0
    return SequenceMatcher(None, first, second, autojunk=False).ratio()
