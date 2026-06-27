import pytest

from app.connectors.postgres import _build_url


def test_build_url_missing_username_raises_value_error():
    with pytest.raises(ValueError, match="postgres connector missing required config key: username"):
        _build_url({"host": "localhost", "database": "db"})


def test_build_url_valid_config_quotes_credentials():
    url = _build_url(
        {
            "username": "user@example.com",
            "password": "p@ ss",
            "host": "db.local",
            "port": 5433,
            "database": "analytics",
            "ssl_mode": "require",
        }
    )
    assert url == "postgresql+psycopg2://user%40example.com:p%40+ss@db.local:5433/analytics?sslmode=require"
