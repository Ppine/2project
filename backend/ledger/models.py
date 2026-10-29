import hashlib
import secrets

from django.db import models

from analysis.clean import clean_merchant
from analysis.infer import Fee
from analysis.parsers import Transaction as ParsedTransaction


class Statement(models.Model):
    """업로드한 명세서. MVP 는 데모 사용자 1명이라 새 명세서가 이전 업로드 거래를 대체한다."""

    filename = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)


class Transaction(models.Model):
    """카드번호·계좌번호는 저장하지 않는다. 날짜·가맹점명·금액만 둔다.

    거래는 명세서 업로드와 카드사 앱 결제 알림 두 경로로 쌓인다.
    """

    UPLOAD = "upload"
    NOTIFICATION = "notification"
    SOURCES = [(UPLOAD, "명세서 업로드"), (NOTIFICATION, "결제 알림")]

    statement = models.ForeignKey(Statement, on_delete=models.CASCADE, related_name="transactions", null=True)
    source = models.CharField(max_length=20, choices=SOURCES, default=UPLOAD)
    date = models.DateField()
    merchant = models.CharField(max_length=255)
    cleaned_merchant = models.CharField(max_length=255)
    amount = models.IntegerField()
    approval_no = models.CharField(max_length=32, blank=True)
    # 같은 알림을 두 번 보내도 한 건만 저장한다 (앱이 재전송하는 경우)
    notification_id = models.CharField(max_length=255, unique=True, null=True)

    class Meta:
        ordering = ["date", "id"]

    @classmethod
    def from_parsed(cls, t: ParsedTransaction, **fields) -> "Transaction":
        return cls(date=t.date, merchant=t.merchant, cleaned_merchant=clean_merchant(t.merchant),
                   amount=t.amount, approval_no=t.approval_no, **fields)

    def to_parsed(self) -> ParsedTransaction:
        return ParsedTransaction(date=self.date, merchant=self.merchant, amount=self.amount,
                                 approval_no=self.approval_no)

    @classmethod
    def all_parsed(cls) -> list[ParsedTransaction]:
        """분석 대상 전체. 명세서에 이미 있는 결제의 알림은 빼서 같은 결제가 두 번 세지지 않게 한다."""
        rows = list(cls.objects.all())
        uploaded = {(t.date, t.cleaned_merchant, t.amount) for t in rows if t.source == cls.UPLOAD}
        return [
            t.to_parsed()
            for t in rows
            if t.source == cls.UPLOAD or (t.date, t.cleaned_merchant, t.amount) not in uploaded
        ]


class ServiceFee(models.Model):
    service = models.CharField(max_length=100)
    plan = models.CharField(max_length=200)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    cycle = models.CharField(max_length=10)  # monthly | yearly
    note = models.TextField(blank=True)
    cancel_url = models.URLField(max_length=500, blank=True)

    def to_fee(self) -> Fee:
        price = int(self.price) if self.price == int(self.price) else float(self.price)
        return Fee(self.service, self.plan, price, self.currency, self.cycle, self.note, self.cancel_url)

    @classmethod
    def all_fees(cls) -> list[Fee]:
        return [f.to_fee() for f in cls.objects.all()]


class MerchantAlias(models.Model):
    """사용자가 확인해 준 가맹점 표기 -> 서비스 매핑.

    amount 가 있으면 그 금액의 결제에만 적용한다. PG사 표기 하나에 여러 서비스가 섞이기 때문이다.
    """

    cleaned_merchant = models.CharField(max_length=255)
    amount = models.IntegerField(null=True, blank=True)
    service = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["cleaned_merchant", "amount"], name="unique_alias")]

    @classmethod
    def as_dict(cls) -> dict:
        return {
            (merchant, amount) if amount is not None else merchant: service
            for merchant, amount, service in cls.objects.values_list("cleaned_merchant", "amount", "service")
        }


class AgentToken(models.Model):
    """API 토큰. 원문은 발급 때 한 번만 보여주고 해시만 저장한다.

    read: AI 에이전트(MCP)용 읽기 전용. app: 폰 앱용 — 읽기 + 결제 알림 전송.
    """

    READ = "read"
    APP = "app"
    SCOPES = [(READ, "읽기 전용"), (APP, "앱 (읽기 + 알림 전송)")]

    name = models.CharField(max_length=100)
    scope = models.CharField(max_length=10, choices=SCOPES, default=READ)
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked = models.BooleanField(default=False)

    @staticmethod
    def hash(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def issue(cls, name: str, scope: str = READ) -> tuple["AgentToken", str]:
        raw = "sdn_" + secrets.token_urlsafe(32)
        return cls.objects.create(name=name, scope=scope, token_hash=cls.hash(raw)), raw

    @classmethod
    def verify(cls, raw: str) -> "AgentToken | None":
        return cls.objects.filter(token_hash=cls.hash(raw), revoked=False).first()
