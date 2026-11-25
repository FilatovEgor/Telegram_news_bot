from __future__ import annotations

import re
from urllib.parse import quote, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from app.sources.base import SourceArticle

MRC_BASE_URL = "https://www.mrc.ru"

_TRANSLITERATION = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}
_TRANSLITERATION.update({key.upper(): value.capitalize() for key, value in list(_TRANSLITERATION.items())})


def transliterate(value: str) -> str:
    return "".join(_TRANSLITERATION.get(character, character) for character in value)


def normalize_article_text(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    replacements = {
        " .": ".", " ,": ",", "годах": "гг", "год.": "г.",
        "год ": "г ", "год)": "г)", "тонн": "тн",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"\s+", " ", text).strip()


def canonical_article_url(href: str, base_url: str = MRC_BASE_URL) -> str | None:
    absolute = urljoin(base_url, href.strip())
    parsed = urlsplit(absolute)
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in {"mrc.ru", "www.mrc.ru"}:
        return None
    if not parsed.path.startswith("/news/") or parsed.path.rstrip("/") == "/news":
        return None
    return absolute


def article_external_id(url: str) -> str:
    segment = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    return quote(unquote(segment), safe="-_.")


def parse_listing_html(html: str, base_url: str = MRC_BASE_URL, limit: int = 50) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        url = canonical_article_url(str(anchor["href"]), base_url)
        if url and url not in seen:
            seen.add(url)
            links.append(url)
            if len(links) >= limit:
                break
    return links


def parse_tags(soup: BeautifulSoup) -> list[str]:
    tags: list[str] = []
    for element in soup.find_all("a", class_="tag-item"):
        raw = element.get_text(" ", strip=True).lstrip("#").strip()
        if not raw:
            continue
        if "mrc" in raw.lower():
            break
        slug = transliterate(raw.lower().replace(" ", "_").replace("-", "_"))
        tag = f"#{slug}"
        if tag not in tags:
            tags.append(tag)
    if "#mrc" not in tags:
        tags.append("#mrc")
    return tags


def parse_article_html(html: str, url: str) -> SourceArticle:
    soup = BeautifulSoup(html, "html.parser")
    title_element = soup.find("h1", class_="h2 news-single-page-header")
    content_element = soup.find("div", class_="post-content")

    title = title_element.get_text(" ", strip=True) if title_element else ""
    if not title:
        title_tag = soup.find("meta", attrs={"property": "og:title"})
        title = str(title_tag.get("content", "")).strip() if title_tag else ""

    if content_element:
        for unwanted in content_element.find_all(["script", "style", "noscript"]):
            unwanted.decompose()
        content = normalize_article_text(content_element.get_text(" ", strip=True))
    else:
        content = ""

    if not title:
        raise ValueError(f"MRC article has no title: {url}")
    if not content:
        raise ValueError(f"MRC article has no article body: {url}")

    return SourceArticle(
        source_key="mrc",
        external_id=article_external_id(url),
        url=url,
        title=title,
        content=content,
        tags=parse_tags(soup),
        metadata={"parser": "mrc-html-v1"},
    )
