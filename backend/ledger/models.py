import hashlib
import secrets

from django.db import models

from analysis.infer import Fee
from analysis.parsers import Transaction as ParsedTransaction


class Statement(models.Model):
    """업로드한 명세서. MVP 는 데모 사용자 1명이라 마지막 명세서를 분석 대상으로 쓴다."""

    filename = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def latest(cls):
        return cls.objects.order_by("-uploaded_at", "-id").first()

    def parsed_transactions(self) -> list[ParsedTransaction]:
        return [
            ParsedTransaction(date=t.date, merchant=t.merchant, amount=t.amount, approval_no=t.approval_no)
            for t in self.transactions.all()
        ]


class Transaction(models.Model):
    """카드번호·계좌번호는 저장하지 않는다. 날짜·가맹점명·금액만 둔다."""

    statement = models.ForeignKey(Statement, on_delete=models.CASCADE, related_name="transactions")
    date = models.DateField()
    merchant = models.CharField(max_length=255)
    cleaned_merchant = models.CharField(max_length=255)
    amount = models.IntegerField()
    approval_no = models.CharField(max_length=32, blank=True)

    class Meta:
        ordering = ["date", "id"]


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
    """사용자가 확인해 준 가맹점 표기 -> 서비스 매핑."""

    cleaned_merchant = models.CharField(max_length=255, unique=True)
    service = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def as_dict(cls) -> dict[str, str]:
        return dict(cls.objects.values_list("cleaned_merchant", "service"))


class AgentToken(models.Model):
    """에이전트용 읽기 전용 토큰. 원문은 발급 때 한 번만 보여주고 해시만 저장한다."""

    name = models.CharField(max_length=100)
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked = models.BooleanField(default=False)

    @staticmethod
    def hash(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def issue(cls, name: str) -> tuple["AgentToken", str]:
        raw = "sdn_" + secrets.token_urlsafe(32)
        return cls.objects.create(name=name, token_hash=cls.hash(raw)), raw

    @classmethod
    def verify(cls, raw: str) -> "AgentToken | None":
        return cls.objects.filter(token_hash=cls.hash(raw), revoked=False).first()
