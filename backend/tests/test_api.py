import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from rest_framework.test import APIClient

from ledger.models import AgentToken

from .conftest import DEMO_CSV

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    call_command("load_service_fees", verbosity=0)
    return APIClient()


@pytest.fixture
def token():
    _, raw = AgentToken.issue("test")
    return raw


def upload(client, name, data):
    return client.post("/api/statements/", {"file": SimpleUploadedFile(name, data)}, format="multipart")


def test_upload_demo_statement_returns_subscriptions(client):
    response = upload(client, DEMO_CSV.name, DEMO_CSV.read_bytes())
    assert response.status_code == 201
    body = response.json()
    assert len(body["subscriptions"]) == 8
    assert body["monthly_total"] == 99980
    assert not any(s["merchant"].startswith("GS25") for s in body["subscriptions"])


@pytest.mark.parametrize("name, data", [("sample.pdf", b"%PDF"), ("x.csv", "이용일자,가맹점명\n".encode())])
def test_upload_unsupported_format(client, name, data):
    response = upload(client, name, data)
    assert response.status_code == 400
    assert response.json()["detail"] == "지원하지 않는 명세서 형식입니다"


def test_subscriptions_require_token(client):
    upload(client, DEMO_CSV.name, DEMO_CSV.read_bytes())
    for headers in ({}, {"HTTP_AUTHORIZATION": "Bearer wrong"}):
        response = client.get("/api/subscriptions/", **headers)
        assert response.status_code == 401
        assert response.json()["error"] == "invalid_token"
        assert "subscriptions" not in response.json()


def test_revoked_token_rejected(client, token):
    AgentToken.objects.update(revoked=True)
    assert client.get("/api/subscriptions/", HTTP_AUTHORIZATION=f"Bearer {token}").status_code == 401


def test_subscriptions_with_token(client, token):
    upload(client, DEMO_CSV.name, DEMO_CSV.read_bytes())
    response = client.get("/api/subscriptions/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert response.status_code == 200
    assert len(response.json()["subscriptions"]) == 8


def test_explain_charge_api(client, token):
    upload(client, DEMO_CSV.name, DEMO_CSV.read_bytes())
    auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
    body = client.get("/api/charges/explain/", {"merchant": "토스페이먼츠", "amount": "14,900"}, **auth).json()
    assert body["candidates"][0]["service"] == "YouTube Premium"
    assert client.get("/api/charges/explain/", {"merchant": "x"}, **auth).status_code == 400


def test_no_statement_yet(client, token):
    response = client.get("/api/subscriptions/", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert response.status_code == 404
