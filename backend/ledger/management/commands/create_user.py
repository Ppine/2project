import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ("웹 대시보드 계정을 만들거나 비밀번호를 바꾼다 (발표용 데모 계정 등). "
            "비밀번호는 입력받거나 DONGGUMA_PASSWORD 환경변수로 준다.")

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, *args, username, **options):
        import os

        password = os.environ.get("DONGGUMA_PASSWORD") or getpass.getpass("비밀번호: ")
        User = get_user_model()
        user = User.objects.filter(username=username).first() or User(username=username)
        try:
            validate_password(password, user=user)
        except ValidationError as e:
            raise CommandError(" ".join(e.messages))
        created = user.pk is None
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS(f"'{username}' 계정을 {'만들었습니다' if created else '갱신했습니다'}."))
