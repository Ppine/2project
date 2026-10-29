from django.core.management.base import BaseCommand

from ledger.models import AgentToken


class Command(BaseCommand):
    help = "API 토큰을 발급한다. 원문은 지금 한 번만 출력된다. 에이전트는 read, 폰 앱은 --scope app."

    def add_arguments(self, parser):
        parser.add_argument("name", nargs="?", default="claude-desktop")
        parser.add_argument("--scope", choices=[AgentToken.READ, AgentToken.APP], default=AgentToken.READ)

    def handle(self, *args, name, scope, **options):
        _, raw = AgentToken.issue(name, scope)
        self.stdout.write(raw)
