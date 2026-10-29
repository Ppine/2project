from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from analysis.infer import load_fees
from ledger.models import ServiceFee


class Command(BaseCommand):
    help = "구독료 CSV(docs/service fee modified.csv)를 ServiceFee 로 다시 불러온다."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=str(settings.SERVICE_FEES_CSV))

    def handle(self, *args, path, **options):
        fees = load_fees(path)
        with transaction.atomic():
            ServiceFee.objects.all().delete()
            ServiceFee.objects.bulk_create(
                ServiceFee(service=f.service, plan=f.plan, price=f.price, currency=f.currency,
                           cycle=f.cycle, note=f.note, cancel_url=f.cancel_url)
                for f in fees
            )
        self.stdout.write(self.style.SUCCESS(f"{len(fees)}개 요금제를 불러왔습니다."))
