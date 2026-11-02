from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from ledger.models import AgentToken


class Command(BaseCommand):
    help = ("API 토큰을 발급한다. 원문은 지금 한 번만 출력된다. 에이전트는 read, 폰 앱은 --scope app. "
            "토큰은 --user 계정의 데이터만 읽고 쓴다.")

    def add_arguments(self, parser):
        parser.add_argument("name", nargs="?", default="claude-desktop")
        parser.add_argument("--scope", choices=[AgentToken.READ, AgentToken.APP], default=AgentToken.READ)
        parser.add_argument("--user", required=True, help="토큰 주인 계정 (아이디)")

    def handle(self, *args, name, scope, user, **options):
        try:
            owner = get_user_model().objects.get(username=user)
        except get_user_model().DoesNotExist:
            raise CommandError(f"'{user}' 계정이 없습니다. 먼저 create_user 로 만드세요.")
        _, raw = AgentToken.issue(owner, name, scope)
        self.stdout.write(raw)
