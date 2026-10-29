from django.db import transaction
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from analysis.clean import clean_merchant
from analysis.infer import analyze, explain_charge
from analysis.llm import ClaudeInferer
from analysis.parsers import UnsupportedFormat, parse_statement

from .models import MerchantAlias, ServiceFee, Statement, Transaction

NO_STATEMENT = {"error": "no_statement", "detail": "업로드된 명세서가 없습니다."}


def _engine_inputs():
    return ServiceFee.all_fees(), MerchantAlias.as_dict(), ClaudeInferer.from_env()


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
            Statement.objects.all().delete()  # 데모 사용자 1명: 새 명세서로 교체
            statement = Statement.objects.create(filename=upload.name)
            Transaction.objects.bulk_create(
                Transaction(
                    statement=statement,
                    date=t.date,
                    merchant=t.merchant,
                    cleaned_merchant=clean_merchant(t.merchant),
                    amount=t.amount,
                    approval_no=t.approval_no,
                )
                for t in parsed
            )

        fees, aliases, llm = _engine_inputs()
        result = analyze(parsed, fees, aliases, llm)
        return Response({"statement": {"filename": upload.name, "transactions": len(parsed)}, **result},
                        status.HTTP_201_CREATED)


class SubscriptionListView(APIView):
    def get(self, request):
        statement = Statement.latest()
        if not statement:
            return Response(NO_STATEMENT, status.HTTP_404_NOT_FOUND)
        fees, aliases, llm = _engine_inputs()
        return Response(analyze(statement.parsed_transactions(), fees, aliases, llm))


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

        statement = Statement.latest()
        if not statement:
            return Response(NO_STATEMENT, status.HTTP_404_NOT_FOUND)
        fees, aliases, llm = _engine_inputs()
        return Response(explain_charge(merchant, amount, statement.parsed_transactions(), fees, aliases, llm))
