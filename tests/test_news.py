import pytest

from rota_segura.news import NewsItem, NewsSnapshotError, load_news, save_news


def _items():
    return [
        NewsItem(id=i, title=f"Operação PRF {i}", source="Agência Gov", url=f"https://exemplo.gov.br/{i}",
                 published="2026-06-20", snippet="Operação em rodovias federais.", provider="rss")
        for i in (1, 2)
    ]  # fmt: skip


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "noticias.json"
    digest = save_news(_items(), path)
    assert load_news(path) == _items()
    assert len(digest) == 64
    assert save_news(_items(), tmp_path / "outra.json") == digest


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(NewsSnapshotError):
        load_news(tmp_path / "nao_existe.json")


def test_load_invalid_json_raises(tmp_path):
    path = tmp_path / "ruim.json"
    path.write_text('{"items": [{"id": "x"}]}', encoding="utf-8")
    with pytest.raises(NewsSnapshotError):
        load_news(path)
