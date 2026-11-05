from fastapi.testclient import TestClient

from specflow import __version__
from specflow.web.app import KANBAN_COLUMNS, app

client = TestClient(app)


def test_health_returns_ok_and_version() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_index_renders_chat_and_all_kanban_columns() -> None:
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'aria-label="Czat"' in html
    for status, label in KANBAN_COLUMNS:
        assert f'data-status="{status.value}"' in html
        assert label in html


def test_static_css_is_served() -> None:
    response = client.get("/static/app.css")
    assert response.status_code == 200
