from datetime import datetime, timezone

from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from analysis.clean import clean_merchant
from analysis.infer import analyze, explain_charge
from analysis.llm import ClaudeInferer
from analysis.notifications import parse_notification
from analysis.parsers import UnsupportedFormat, parse_statement

from .models import AgentToken, MerchantAlias, ServiceFee, Statement, Transaction

NO_TRANSACTIONS = {"error": "no_transactions", "detail": "아직 수집된 결제 내역이 없습니다."}


def _engine_inputs():
    return ServiceFee.all_fees(), MerchantAlias.as_dict(), ClaudeInferer.from_env()


def _analysis() -> dict:
    fees, aliases, llm = _engine_inputs()
    transactions = Transaction.all_parsed()
    return {"transactions": len(transactions), **analyze(transactions, fees, aliases, llm)}


class IsAppToken(BasePermission):
    """결제 알림 전송은 폰 앱 토큰만. 에이전트(read) 토큰은 읽기만 한다."""

    def has_permission(self, request, view):
        return isinstance(request.auth, AgentToken) and request.auth.scope == AgentToken.APP


class StatementUploadView(APIView):
    """웹 대시보드용 업로드. MVP 는 로그인 없이 데모 사용자 1명으로 쓴다."""

    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser]

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
            Statement.objects.all().delete()  # 데모 사용자 1명: 새 명세서로 교체. 알림으로 쌓인 거래는 남긴다
            statement = Statement.objects.create(filename=upload.name)
            Transaction.objects.bulk_create(
                Transaction.from_parsed(t, statement=statement, source=Transaction.UPLOAD) for t in parsed
            )

        result = _analysis()
        return Response({"statement": {"filename": upload.name, "transactions": len(parsed)}, **result},
                        status.HTTP_201_CREATED)


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


class MerchantAliasView(APIView):
    """사용자가 불분명 결제의 실제 서비스를 확인해 준다. 다음 분석부터 그 서비스로 확정된다.

    웹 대시보드에서도 쓰므로 업로드처럼 데모 사용자 1명 기준으로 로그인 없이 받는다.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
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
