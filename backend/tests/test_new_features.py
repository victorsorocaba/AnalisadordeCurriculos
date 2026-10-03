import asyncio
import base64
import hashlib

import pytest
from fastapi import HTTPException

from backend import accounts
from backend.services.job_import import import_job, parse_job_html


class FakeConnection:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params):
        self.calls.append((sql, params))
        return self


def test_password_hash_uses_salt_and_verifies():
    first = accounts._password_hash("uma senha longa e privada")
    second = accounts._password_hash("uma senha longa e privada")
    assert first != second
    assert accounts._verify_password("uma senha longa e privada", first)
    assert not accounts._verify_password("senha diferente", first)


def test_registration_moves_existing_profile_to_account(monkeypatch):
    fake = FakeConnection()
    monkeypatch.setattr(accounts, "_database_url", lambda: "postgresql://example")
    monkeypatch.setattr(accounts, "_connect", lambda: fake)
    key = base64.urlsafe_b64encode(b"a" * 32).decode().rstrip("=")
    result = accounts.register(accounts.Credentials(email="Pessoa@Example.com", password="senha bem longa"), key)
    assert result["email"] == "pessoa@example.com"
    assert result["sessionToken"]
    moves = [(sql, values) for sql, values in fake.calls if sql.startswith("UPDATE")]
    assert len(moves) == 4
    assert all(values[1] == hashlib.sha256(key.encode()).hexdigest() for _, values in moves)
    assert len({values[0] for _, values in moves}) == 1


def test_job_html_extracts_structured_description():
    body = '<html><script type="application/ld+json">{"@type":"JobPosting","title":"Dev Backend","hiringOrganization":{"name":"Acme"},"description":"<p>Python e SQL</p>"}</script></html>'
    data = parse_job_html(body, "https://jobs.lever.co/acme/123")
    assert data["role"] == "Dev Backend"
    assert data["company"] == "Acme"
    assert data["jobDescription"] == "Python e SQL"


def test_job_import_rejects_non_allowlisted_host_without_network():
    with pytest.raises(HTTPException) as caught:
        asyncio.run(import_job("https://localhost/internal"))
    assert caught.value.status_code == 422
