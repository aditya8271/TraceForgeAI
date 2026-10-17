import pytest

@pytest.fixture(autouse=True)
def isolate_database_for_tests(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
