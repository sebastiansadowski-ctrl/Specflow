from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from specflow import __version__
from specflow.settings import Settings
from specflow.web.app import KANBAN_COLUMNS, create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Settings(data_dir=tmp_path), start_workers=False))


def test_health_returns_ok_and_version(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__, "harness": "mock"}


def test_index_renders_chat_and_all_kanban_columns(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'aria-label="Czat"' in html
    for status, label in KANBAN_COLUMNS:
        assert f'data-status="{status.value}"' in html
        assert label in html


def test_static_assets_are_local(client: TestClient) -> None:
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/vendor/htmx-2.0.4.min.js").status_code == 200
    assert "unpkg.com" not in client.get("/").text  # CSP pozwala tylko na własne skrypty
