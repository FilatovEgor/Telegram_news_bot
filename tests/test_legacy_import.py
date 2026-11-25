import sqlite3

from scripts.import_legacy_sqlite import (
    inspect_legacy_rows,
    map_legacy_status,
    read_legacy_rows,
)


def test_legacy_database_read_preserves_original_row_id(tmp_path):
    path = tmp_path / "storage.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE motor (id INTEGER PRIMARY KEY AUTOINCREMENT, news_id TEXT, "
        "title TEXT, link TEXT, status TEXT, date TEXT)"
    )
    connection.execute(
        "INSERT INTO motor (news_id,title,link,status,date) VALUES (?,?,?,?,?)",
        ("123-story", "Title", "https://www.mrc.ru/news/123-story", "Send", "2025-01-01"),
    )
    connection.commit()
    connection.close()

    rows = read_legacy_rows(path)
    assert rows == [
        (1, "123-story", "Title", "https://www.mrc.ru/news/123-story", "Send", "2025-01-01")
    ]
    assert inspect_legacy_rows(rows) == {"Send": 1}


def test_legacy_status_mapping_keeps_review_separate_from_publication():
    assert map_legacy_status("Send") == "SUMMARIZED"
    assert map_legacy_status("Del") == "REJECTED"
    assert map_legacy_status("Can't del - more 48H") == "REJECTED"
    assert map_legacy_status(None) == "DISCOVERED"
