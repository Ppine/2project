from django.core.management.base import BaseCommand

from ledger.models import AgentToken


class Command(BaseCommand):
    help = "AI 에이전트용 읽기 전용 토큰을 발급한다. 원문은 지금 한 번만 출력된다."

    def add_arguments(self, parser):
        parser.add_argument("name", nargs="?", default="claude-desktop")

    def handle(self, *args, name, **options):
        _, raw = AgentToken.issue(name)
        self.stdout.write(raw)
