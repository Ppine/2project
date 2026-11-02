from collections import Counter
from datetime import datetime, timezone

from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from analysis.clean import clean_merchant, describe_merchant
from analysis.infer import analyze, explain_charge
from analysis.llm import ClaudeInferer
from analysis.notifications import parse_notification
from analysis.parsers import UnsupportedFormat, parse_statement

from .models import AgentToken, MerchantAlias, ServiceFee, Statement, SubscriptionState, Transaction

NO_TRANSACTIONS = {"error": "no_transactions", "detail": "아직 수집된 결제 내역이 없습니다."}


def _engine_inputs():
    return ServiceFee.all_fees(), MerchantAlias.as_dict(), ClaudeInferer.from_env()


def _analysis() -> dict:
    fees, aliases, llm = _engine_inputs()
    transactions = Transaction.all_parsed()
    result = analyze(transactions, fees, aliases, llm, states=SubscriptionState.as_dict(),
                     as_of=Transaction.coverage_end())
    return {"transactions": len(transactions), **result}


def _statements() -> list[dict]:
    return [s.summary() for s in Statement.objects.all()]


class DemoUserView(APIView):
    """웹 대시보드용. MVP 는 로그인 없이 데모 사용자 1명으로 쓴다."""

    authentication_classes = []
    permission_classes = [AllowAny]


class IsAppToken(BasePermission):
    """결제 알림 전송은 폰 앱 토큰만. 에이전트(read) 토큰은 읽기만 한다."""

    def has_permission(self, request, view):
        return isinstance(request.auth, AgentToken) and request.auth.scope == AgentToken.APP


class StatementUploadView(DemoUserView):
    """명세서 업로드·목록·전체 삭제. 새 명세서는 이전 명세서에 더해 쌓인다 (1년치 이력을 모으기 위해)."""

    parser_classes = [MultiPartParser]

    def get(self, request):
        """웹 대시보드가 처음 열릴 때 쓴다: 올린 명세서 목록과 (거래가 있으면) 분석 결과."""
        body = {"statements": _statements()}
        if Transaction.objects.exists():
            body.update(_analysis())
        return Response(body)

    def post(self, request):
        upload = request.FILES.get("file")
        if not upload:
            return Response({"error": "no_file", "detail": "명세서 파일을 선택해 주세요."}, status.HTTP_400_BAD_REQUEST)
        try:
            parsed = parse_statement(upload.name, upload.read())
        except UnsupportedFormat as e:
            return Response(
                {"error": "unsupported_format", "detail": str(e), "reason": e.reason}, status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            # 이미 올린 명세서와 기간이 겹치면 겹치는 거래는 건너뛴다. 같은 날 같은 금액의 결제가 실제로 여러 건일 수
            # 있어 건수로 비교한다: 이미 2건 있고 새 명세서에 3건 있으면 1건만 더한다.
            existing = Counter(t.dedupe_key() for t in Transaction.objects.filter(source=Transaction.UPLOAD))
            statement = Statement.objects.create(filename=upload.name)
            new_rows = []
            for t in parsed:
                row = Transaction.from_parsed(t, statement=statement, source=Transaction.UPLOAD)
                key = row.dedupe_key()
                if existing[key] > 0:
                    existing[key] -= 1
                else:
                    new_rows.append(row)
            Transaction.objects.bulk_create(new_rows)
            if not new_rows:  # 이미 올린 내용뿐이면 목록에 빈 명세서를 남기지 않는다
                statement.delete()

        result = _analysis()
        summary = {"filename": upload.name, "transactions": len(parsed), "added": len(new_rows),
                   "skipped": len(parsed) - len(new_rows)}
        return Response({"statement": summary, "statements": _statements(), **result}, status.HTTP_201_CREATED)

    def delete(self, request):
        """처음부터 다시 볼 수 있도록 올린 명세서를 모두 지운다. 결제 알림으로 쌓인 거래는 남긴다."""
        deleted, _ = Statement.objects.all().delete()
        return Response({"deleted": deleted})


class StatementDetailView(DemoUserView):
    """잘못 올린 명세서 하나와 그 거래만 지운다."""

    def delete(self, request, statement_id):
        deleted, _ = Statement.objects.filter(id=statement_id).delete()
        if not deleted:
            return Response({"error": "not_found", "detail": "명세서를 찾지 못했습니다."}, status.HTTP_404_NOT_FOUND)
        body = {"statements": _statements()}
        if Transaction.objects.exists():
            body.update(_analysis())
        return Response(body)


class SubscriptionStateView(DemoUserView):
    """사용자가 '해지했어요' / '다시 구독 중' 을 표시한다. 결제 이력과 따로 저장한다."""

    parser_classes = [JSONParser]

    def post(self, request):
        merchant = str(request.data.get("merchant", "")).strip()
        state = str(request.data.get("status", "")).strip()
        amount = request.data.get("amount")
        try:
            amount = int(str(amount).replace(",", "")) if amount is not None else None
        except ValueError:
            amount = "invalid"
        valid = {SubscriptionState.ACTIVE, SubscriptionState.CANCELLED}
        if not merchant or state not in valid or amount == "invalid":
            return Response({"error": "bad_request",
                             "detail": "merchant, status(active|cancelled) 와 amount(정수, 선택)가 필요합니다."},
                            status.HTTP_400_BAD_REQUEST)

        info = describe_merchant(merchant)
        # 직접 결제 가맹점은 요금이 바뀌어도 같은 구독이라 금액 없이 저장한다.
        key_amount = amount if info.intermediary else None
        if state == SubscriptionState.ACTIVE:
            SubscriptionState.objects.filter(cleaned_merchant=info.cleaned, amount=key_amount).delete()
        else:
            SubscriptionState.objects.update_or_create(
                cleaned_merchant=info.cleaned, amount=key_amount, defaults={"status": state}
            )
        return Response(_analysis())

    def delete(self, request):
        deleted, _ = SubscriptionState.objects.all().delete()
        return Response({"deleted": deleted})


class NotificationIngestView(APIView):
    """폰 앱이 카드사 결제 알림을 보낸다. 승인 알림만 거래로 저장하고, 원문은 저장하지 않는다."""

    permission_classes = [IsAppToken]
    parser_classes = [JSONParser]

    def post(self, request):
        data = request.data
        notification_id = str(data.get("id", "")).strip()
        try:
            posted_at = datetime.fromtimestamp(int(data["posted_at"]) / 1000, tz=timezone.utc).astimezone()
        except (KeyError, TypeError, ValueError):
            posted_at = None
        if not notification_id or posted_at is None:
            return Response({"error": "bad_request", "detail": "id 와 posted_at(밀리초)이 필요합니다."},
                            status.HTTP_400_BAD_REQUEST)

        parsed = parse_notification(str(data.get("title", "")), str(data.get("text", "")), posted_at)
        if parsed is None:
            return Response({"saved": False, "reason": "not_a_charge"})
        try:
            with transaction.atomic():
                Transaction.from_parsed(
                    parsed, source=Transaction.NOTIFICATION, notification_id=notification_id
                ).save()
        except IntegrityError:
            return Response({"saved": False, "reason": "duplicate"})

        result = _analysis()
        # 이 결제가 구독의 정기 결제로 묶였을 때만 구독을 돌려준다 (주기 밖 일회성 결제는 None)
        cleaned = clean_merchant(parsed.merchant)
        subscription = next(
            (s for s in result["subscriptions"]
             if clean_merchant(s["merchant"]) == cleaned and s["amount"] == parsed.amount
             and s["last_charge_date"] == parsed.date.isoformat()),
            None,
        )
        charge = {"date": parsed.date.isoformat(), "merchant": parsed.merchant, "amount": parsed.amount}
        return Response({"saved": True, "charge": charge, "subscription": subscription}, status.HTTP_201_CREATED)


class MerchantAliasView(DemoUserView):
    """사용자가 불분명 결제의 실제 서비스를 확인해 준다. 다음 분석부터 그 서비스로 확정된다."""

    parser_classes = [JSONParser]

    def post(self, request):
        merchant = str(request.data.get("merchant", "")).strip()
        service = str(request.data.get("service", "")).strip()
        amount = request.data.get("amount")
        if amount is not None:
            try:
                amount = int(str(amount).replace(",", ""))
            except ValueError:
                amount = "invalid"
        if not merchant or not service or amount == "invalid":
            return Response({"error": "bad_request", "detail": "merchant, service 와 amount(정수, 선택)가 필요합니다."},
                            status.HTTP_400_BAD_REQUEST)

        MerchantAlias.objects.update_or_create(
            cleaned_merchant=clean_merchant(merchant), amount=amount, defaults={"service": service}
        )
        return Response(_analysis())

    def delete(self, request):
        """데모를 처음부터 다시 볼 수 있도록 사용자가 확인한 매핑을 모두 지운다."""
        deleted, _ = MerchantAlias.objects.all().delete()
        return Response({"deleted": deleted})


class SubscriptionListView(APIView):
    def get(self, request):
        if not Transaction.objects.exists():
            return Response(NO_TRANSACTIONS, status.HTTP_404_NOT_FOUND)
        return Response(_analysis())


class ExplainChargeView(APIView):
    def get(self, request):
        merchant = request.query_params.get("merchant", "").strip()
        try:
            amount = int(request.query_params.get("amount", "").replace(",", ""))
        except ValueError:
            amount = None
        if not merchant or amount is None:
            return Response({"error": "bad_request", "detail": "merchant 와 amount(정수)가 필요합니다."},
                            status.HTTP_400_BAD_REQUEST)

        if not Transaction.objects.exists():
            return Response(NO_TRANSACTIONS, status.HTTP_404_NOT_FOUND)
        fees, aliases, llm = _engine_inputs()
        return Response(explain_charge(merchant, amount, Transaction.all_parsed(), fees, aliases, llm))
