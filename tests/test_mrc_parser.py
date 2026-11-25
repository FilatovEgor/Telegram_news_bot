from app.sources.mrc.parser import (
    article_external_id,
    normalize_article_text,
    parse_article_html,
    parse_listing_html,
    transliterate,
)


def test_listing_extracts_only_unique_mrc_news_urls():
    html = (
        '<a href="/news/123-test-story">one</a>'
        '<a href="https://www.mrc.ru/news/123-test-story">duplicate</a>'
        '<a href="https://example.com/news/not-mrc">external</a>'
    )
    assert parse_listing_html(html) == ["https://www.mrc.ru/news/123-test-story"]


def test_article_external_id_preserves_encoded_slug():
    assert article_external_id(
        "https://www.mrc.ru/news/411245-lotte-chemical-%E2%84%961"
    ) == "411245-lotte-chemical-%E2%84%961"


def test_transliteration_and_text_normalization():
    assert transliterate("Привет мир") == "Privet mir"
    assert normalize_article_text("В 2024 годах выпустили 10 тонн .") == (
        "В 2024 гг выпустили 10 тн."
    )


def test_article_parser_extracts_title_body_and_tags():
    html = (
        '<h1 class="h2 news-single-page-header">Заголовок новости</h1>'
        '<div class="post-content"><p>Основной текст новости.</p>'
        '<script>ignored()</script></div>'
        '<a class="tag-item">Полиэтилен</a><a class="tag-item">MRC</a>'
    )
    article = parse_article_html(html, "https://www.mrc.ru/news/123-test")
    assert article.title == "Заголовок новости"
    assert article.content == "Основной текст новости."
    assert article.tags == ["#polietilen", "#mrc"]
