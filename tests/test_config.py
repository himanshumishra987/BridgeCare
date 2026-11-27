"""Configuration parsing tests."""

from __future__ import annotations

from app.core.config import Settings


def test_allowed_origins_accepts_comma_separated_env(monkeypatch) -> None:
    monkeypatch.setenv(
        "BRIDGECARE_ALLOWED_ORIGINS", "http://localhost:5173, https://app.example.com"
    )
    assert Settings().allowed_origins == (
        "http://localhost:5173",
        "https://app.example.com",
    )


def test_allowed_origins_accepts_json_array_env(monkeypatch) -> None:
    monkeypatch.setenv(
        "BRIDGECARE_ALLOWED_ORIGINS", '["http://localhost:5173", "https://app.example.com"]'
    )
    assert Settings().allowed_origins == (
        "http://localhost:5173",
        "https://app.example.com",
    )


def test_allowed_origins_empty_disables_cors(monkeypatch) -> None:
    monkeypatch.setenv("BRIDGECARE_ALLOWED_ORIGINS", "")
    assert Settings().allowed_origins == ()
