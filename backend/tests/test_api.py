import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from rest_framework.test import APIClient

from ledger.models import AgentToken, Transaction

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


@pytest.fixture
def app_auth():
    _, raw = AgentToken.issue("phone", AgentToken.APP)
    return {"HTTP_AUTHORIZATION": f"Bearer {raw}"}


def notify(client, auth, text, id="n1", posted_at=1792052580000):  # 2026-10-15 14:23 KST
    payload = {"id": id, "posted_at": posted_at, "title": "[데모카드] 승인", "text": text}
    return client.post("/api/notifications/", payload, format="json", **auth)


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


def test_subscriptions_include_cancel(client, token):
    upload(client, DEMO_CSV.name, DEMO_CSV.read_bytes())
    subs = client.get("/api/subscriptions/", HTTP_AUTHORIZATION=f"Bearer {token}").json()["subscriptions"]
    assert next(s for s in subs if s["service"] == "Speak")["cancel"]["via"] == "google_play"


# --- 결제 알림 수집 ---


def test_notification_saved_and_deduplicated(client, app_auth):
    text = "본인3381 14,900원 일시불 10/15 14:22 토스페이먼츠 누적1,234,000원"
    first = notify(client, app_auth, text)
    assert first.status_code == 201
    assert first.json()["charge"] == {"date": "2026-10-15", "merchant": "토스페이먼츠", "amount": 14900}
    assert notify(client, app_auth, text).json() == {"saved": False, "reason": "duplicate"}
    assert Transaction.objects.filter(source=Transaction.NOTIFICATION).count() == 1


def test_notification_extends_subscription(client, app_auth):
    """명세서 다음 달 결제가 알림으로 들어오면 같은 구독으로 묶이고 다음 결제일이 밀린다."""
    upload(client, DEMO_CSV.name, DEMO_CSV.read_bytes())
    body = notify(client, app_auth, "본인3381 4,900원 일시불 11/01 08:00 네이버플러스멤버십",
                  posted_at=1793491200000).json()  # 2026-11-01 KST
    assert body["subscription"]["service"] == "Naver Plus Membership"
    assert body["subscription"]["next_payment_date"] == "2026-12-01"


def test_notification_already_in_statement_not_double_counted(client, app_auth, token):
    upload(client, DEMO_CSV.name, DEMO_CSV.read_bytes())
    last_naver = Transaction.objects.filter(merchant="네이버플러스멤버십").last()
    d = last_naver.date
    notify(client, app_auth, f"본인3381 4,900원 일시불 {d.month}/{d.day} 08:00 네이버플러스멤버십",
           posted_at=1792052580000)
    body = client.get("/api/subscriptions/", HTTP_AUTHORIZATION=f"Bearer {token}").json()
    assert len(body["subscriptions"]) == 8
    assert body["monthly_total"] == 99980


def test_notification_ignores_non_charge(client, app_auth):
    assert notify(client, app_auth, "10월 캐시백 이벤트").json() == {"saved": False, "reason": "not_a_charge"}
    assert notify(client, app_auth, "x", id="").status_code == 400


def test_read_token_cannot_send_notifications(client, token):
    response = notify(client, {"HTTP_AUTHORIZATION": f"Bearer {token}"}, "본인 1,000원 일시불 10/15 14:22 A")
    assert response.status_code == 403
    assert client.post("/api/notifications/", {}, format="json").status_code == 401


# --- 불분명 결제 확인 ---


def test_confirm_alias_makes_charge_cancellable(client):
    upload(client, DEMO_CSV.name, DEMO_CSV.read_bytes())
    response = client.post("/api/merchant-aliases/", {"merchant": "NICE페이", "amount": 9900, "service": "Disney+"},
                           format="json")
    assert response.status_code == 200
    disney = next(s for s in response.json()["subscriptions"] if s["merchant"] == "NICE페이")
    assert (disney["service"], disney["confidence"]) == ("Disney+", "high")
    assert disney["cancel"]["via"] == "web"
    assert client.post("/api/merchant-aliases/", {"merchant": "NICE페이"}, format="json").status_code == 400


def test_reset_aliases_clears_confirmed_services(client):
    upload(client, DEMO_CSV.name, DEMO_CSV.read_bytes())
    client.post("/api/merchant-aliases/", {"merchant": "NICE페이", "amount": 9900, "service": "Disney+"},
                format="json")
    response = client.delete("/api/merchant-aliases/")
    assert response.status_code == 200
    assert response.json() == {"deleted": 1}
    subs = upload(client, DEMO_CSV.name, DEMO_CSV.read_bytes()).json()["subscriptions"]
    nice = next(s for s in subs if s["merchant"] == "NICE페이")
    assert nice["confidence"] != "high"


def test_off_cycle_notification_keeps_subscription(client, app_auth, token):
    upload(client, DEMO_CSV.name, DEMO_CSV.read_bytes())
    body = notify(client, app_auth, "본인3381 9,900원 일시불 10/29 14:22 NICE페이",
                  posted_at=1793251200000).json()  # 2026-10-29 KST
    assert body["saved"] is True
    assert body["subscription"] is None  # 정기 결제가 아닌 일회성 결제
    subs = client.get("/api/subscriptions/", HTTP_AUTHORIZATION=f"Bearer {token}").json()["subscriptions"]
    assert len(subs) == 8


# --- 명세서 누적·관리 ---


def _csv(rows):
    lines = ["이용일자,이용카드,가맹점명,이용금액,승인번호"] + [",".join(r) for r in rows]
    return "\n".join(lines).encode()


def test_statements_accumulate_without_duplicates(client):
    first = upload(client, DEMO_CSV.name, DEMO_CSV.read_bytes()).json()
    again = upload(client, "again.csv", DEMO_CSV.read_bytes()).json()
    assert again["statement"]["added"] == 0
    assert again["statement"]["skipped"] == first["statement"]["transactions"]
    assert again["transactions"] == first["transactions"]
    assert len(again["statements"]) == 1  # 새 거래가 없는 업로드는 목록에 남기지 않는다


def test_dashboard_get_returns_statements_and_analysis(client):
    assert client.get("/api/statements/").json() == {"statements": []}
    upload(client, DEMO_CSV.name, DEMO_CSV.read_bytes())
    body = client.get("/api/statements/").json()
    assert len(body["statements"]) == 1 and len(body["subscriptions"]) == 8


def test_row_with_extra_columns_is_rejected(client):
    response = upload(client, "bad.csv", _csv([("2026-10-01", "카드", "GS25", "1,000", "")]))
    assert response.status_code == 400


def test_same_day_same_amount_charges_kept(client):
    rows = [("2026-10-01", "카드", "GS25", "1000", ""), ("2026-10-01", "카드", "GS25", "1000", "")]
    body = upload(client, "a.csv", _csv(rows)).json()
    assert body["statement"]["added"] == 2
    more = rows + [("2026-10-01", "카드", "GS25", "1000", "")]
    assert upload(client, "b.csv", _csv(more)).json()["statement"]["added"] == 1


def test_delete_one_statement_keeps_others(client):
    upload(client, DEMO_CSV.name, DEMO_CSV.read_bytes())
    extra = upload(client, "extra.csv", _csv([("2026-10-27", "카드", "올리브영", "12000", "999")])).json()
    statements = client.get("/api/statements/").json()["statements"]
    assert statements[0]["filename"] == "extra.csv"  # 최근 업로드부터
    assert statements[1]["period_start"] and statements[1]["period_end"]

    response = client.delete(f"/api/statements/{statements[0]['id']}/")
    assert response.status_code == 200
    body = response.json()
    assert body["transactions"] == extra["transactions"] - 1
    assert len(body["statements"]) == 1
    assert client.delete(f"/api/statements/{statements[0]['id']}/").status_code == 404


def test_delete_all_statements(client):
    upload(client, DEMO_CSV.name, DEMO_CSV.read_bytes())
    assert client.delete("/api/statements/").status_code == 200
    assert not Transaction.objects.exists()


# --- 구독 상태 표시 ---


def test_mark_cancelled_survives_reupload(client):
    upload(client, DEMO_CSV.name, DEMO_CSV.read_bytes())
    body = client.post("/api/subscriptions/state/", {"merchant": "NETFLIX.COM", "amount": 17000,
                                                    "status": "cancelled"}, format="json").json()
    netflix = next(s for s in body["subscriptions"] if s["service"] == "Netflix")
    assert netflix["status"] == "cancelled"
    assert body["monthly_total"] == 99980 - 17000

    again = upload(client, "again.csv", DEMO_CSV.read_bytes()).json()
    assert next(s for s in again["subscriptions"] if s["service"] == "Netflix")["status"] == "cancelled"

    body = client.post("/api/subscriptions/state/", {"merchant": "NETFLIX.COM", "status": "active"},
                       format="json").json()
    assert body["monthly_total"] == 99980


def test_pg_cancel_is_per_amount(client):
    upload(client, DEMO_CSV.name, DEMO_CSV.read_bytes())
    body = client.post("/api/subscriptions/state/", {"merchant": "토스페이먼츠", "amount": 14900,
                                                    "status": "cancelled"}, format="json").json()
    toss = [s for s in body["subscriptions"] if s["merchant"] == "토스페이먼츠"]
    assert [s["status"] for s in toss] == ["cancelled"]


def test_subscription_state_validation(client):
    bad = [{"merchant": "NETFLIX.COM", "status": "paused"}, {"status": "cancelled"},
           {"merchant": "NETFLIX.COM", "status": "cancelled", "amount": "abc"}]
    for payload in bad:
        assert client.post("/api/subscriptions/state/", payload, format="json").status_code == 400


def test_notifications_do_not_mark_others_lapsed(client, app_auth, token):
    upload(client, DEMO_CSV.name, DEMO_CSV.read_bytes())
    # 명세서 이후 한참 뒤의 알림 한 건이 다른 구독을 '결제 확인 안 됨'으로 만들지 않는다
    notify(client, app_auth, "본인3381 5,000원 일시불 12/20 14:22 GS25", posted_at=1797744000000)  # 2026-12-20
    subs = client.get("/api/subscriptions/", HTTP_AUTHORIZATION=f"Bearer {token}").json()["subscriptions"]
    assert {s["status"] for s in subs} == {"active"}
