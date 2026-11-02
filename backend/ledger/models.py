import hashlib
import secrets

from django.conf import settings
from django.db import models

from analysis.clean import clean_merchant
from analysis.infer import Fee
from analysis.parsers import Transaction as ParsedTransaction


class Statement(models.Model):
    """업로드한 명세서. 여러 달 치를 쌓아 두고, 잘못 올린 명세서는 하나씩 지울 수 있다.

    이미 저장된 거래와 겹치는 거래는 다시 저장하지 않으므로 기간이 겹치는 명세서를 올려도 된다.
    """

    # 데이터 주인. 모든 조회는 owner 로 걸러서 다른 사용자의 데이터가 섞이지 않게 한다.
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    filename = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]

    def summary(self) -> dict:
        span = self.transactions.aggregate(start=models.Min("date"), end=models.Max("date"),
                                           count=models.Count("id"))
        return {
            "id": self.id,
            "filename": self.filename,
            "uploaded_at": self.uploaded_at.isoformat(),
            "transactions": span["count"],
            "period_start": span["start"].isoformat() if span["start"] else None,
            "period_end": span["end"].isoformat() if span["end"] else None,
        }


class Transaction(models.Model):
    """카드번호·계좌번호는 저장하지 않는다. 날짜·가맹점명·금액만 둔다.

    거래는 명세서 업로드와 카드사 앱 결제 알림 두 경로로 쌓인다.
    """

    UPLOAD = "upload"
    NOTIFICATION = "notification"
    SOURCES = [(UPLOAD, "명세서 업로드"), (NOTIFICATION, "결제 알림")]

    # 데이터 주인. 모든 조회는 owner 로 걸러서 다른 사용자의 데이터가 섞이지 않게 한다.
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    statement = models.ForeignKey(Statement, on_delete=models.CASCADE, related_name="transactions", null=True)
    source = models.CharField(max_length=20, choices=SOURCES, default=UPLOAD)
    date = models.DateField()
    merchant = models.CharField(max_length=255)
    cleaned_merchant = models.CharField(max_length=255)
    amount = models.IntegerField()
    approval_no = models.CharField(max_length=32, blank=True)
    # 같은 알림을 두 번 보내도 한 건만 저장한다 (앱이 재전송하는 경우)
    notification_id = models.CharField(max_length=255, null=True)

    class Meta:
        ordering = ["date", "id"]
        constraints = [models.UniqueConstraint(fields=["owner", "notification_id"], name="unique_notification")]

    @classmethod
    def from_parsed(cls, t: ParsedTransaction, **fields) -> "Transaction":
        return cls(date=t.date, merchant=t.merchant, cleaned_merchant=clean_merchant(t.merchant),
                   amount=t.amount, approval_no=t.approval_no, **fields)

    def to_parsed(self) -> ParsedTransaction:
        return ParsedTransaction(date=self.date, merchant=self.merchant, amount=self.amount,
                                 approval_no=self.approval_no)

    def dedupe_key(self) -> tuple:
        return (self.date, self.cleaned_merchant, self.amount, self.approval_no)

    @classmethod
    def coverage_end(cls, owner):
        """명세서가 덮는 마지막 날짜. 결제가 끊겼는지는 이 날짜까지만 판단한다.

        결제 알림은 일부 카드만 들어오므로 알림 날짜로는 다른 구독의 결제 누락을 판단하지 않는다.
        """
        return cls.objects.filter(owner=owner, source=cls.UPLOAD).aggregate(end=models.Max("date"))["end"]

    @classmethod
    def all_parsed(cls, owner) -> list[ParsedTransaction]:
        """사용자의 분석 대상 전체. 명세서에 이미 있는 결제의 알림은 빼서 같은 결제가 두 번 세지지 않게 한다."""
        rows = list(cls.objects.filter(owner=owner))
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

    # 데이터 주인. 모든 조회는 owner 로 걸러서 다른 사용자의 데이터가 섞이지 않게 한다.
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    cleaned_merchant = models.CharField(max_length=255)
    amount = models.IntegerField(null=True, blank=True)
    service = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "cleaned_merchant", "amount"], name="unique_alias")]

    @classmethod
    def as_dict(cls, owner) -> dict:
        return {
            (merchant, amount) if amount is not None else merchant: service
            for merchant, amount, service in cls.objects.filter(owner=owner).values_list(
                "cleaned_merchant", "amount", "service")
        }


class SubscriptionState(models.Model):
    """사용자가 표시한 구독 상태. 결제 이력과 따로 저장해, 명세서를 다시 올려도 해지 표시가 유지된다.

    직접 결제 가맹점은 요금이 바뀌어도 같은 구독이므로 amount 없이 가맹점으로만,
    PG사·앱마켓은 한 표기 아래 여러 서비스가 섞이므로 가맹점+금액으로 저장한다 (MerchantAlias 와 같은 방식).
    """

    ACTIVE = "active"
    CANCELLED = "cancelled"
    STATUSES = [(ACTIVE, "구독 중"), (CANCELLED, "해지함")]

    # 데이터 주인. 모든 조회는 owner 로 걸러서 다른 사용자의 데이터가 섞이지 않게 한다.
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    cleaned_merchant = models.CharField(max_length=255)
    amount = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUSES)
    changed_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "cleaned_merchant", "amount"],
                                               name="unique_subscription_state")]

    @classmethod
    def as_dict(cls, owner) -> dict:
        """analyze() 가 받는 형태: 키 -> (status, 표시한 날짜)."""
        return {
            (s.cleaned_merchant, s.amount) if s.amount is not None else s.cleaned_merchant:
                (s.status, s.changed_at.astimezone().date())
            for s in cls.objects.filter(owner=owner)
        }


class AgentToken(models.Model):
    """API 토큰. 원문은 발급 때 한 번만 보여주고 해시만 저장한다.

    read: AI 에이전트(MCP)용 읽기 전용. app: 폰 앱용 — 읽기 + 결제 알림 전송.
    토큰은 발급한 사용자(owner)의 데이터만 읽고 쓴다.
    """

    READ = "read"
    APP = "app"
    SCOPES = [(READ, "읽기 전용"), (APP, "앱 (읽기 + 알림 전송)")]

    # 데이터 주인. 모든 조회는 owner 로 걸러서 다른 사용자의 데이터가 섞이지 않게 한다.
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    name = models.CharField(max_length=100)
    scope = models.CharField(max_length=10, choices=SCOPES, default=READ)
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked = models.BooleanField(default=False)

    @staticmethod
    def hash(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def issue(cls, owner, name: str, scope: str = READ) -> tuple["AgentToken", str]:
        raw = "sdn_" + secrets.token_urlsafe(32)
        return cls.objects.create(owner=owner, name=name, scope=scope, token_hash=cls.hash(raw)), raw

    @classmethod
    def verify(cls, raw: str) -> "AgentToken | None":
        return cls.objects.select_related("owner").filter(
            token_hash=cls.hash(raw), revoked=False, owner__is_active=True).first()
