"""웹 대시보드 로그인 (Django 세션).

- 세션 쿠키는 HttpOnly 라 스크립트가 읽을 수 없다.
- 상태를 바꾸는 요청(회원가입·로그인·로그아웃 포함)은 CSRF 토큰(X-CSRFToken 헤더)을 확인한다.
  me 를 먼저 호출하면 csrftoken 쿠키가 내려온다.
- 회원가입·로그인은 IP 당 분당 횟수를 제한해 비밀번호 대입을 막는다.
- 로그인 실패 메시지는 아이디가 없는지 비밀번호가 틀렸는지 구분하지 않는다.
"""

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

User = get_user_model()


def _user_body(user) -> dict:
    return {"user": {"username": user.username}}


def _enforce_csrf(request):
    """로그인 전 요청에도 CSRF 를 확인한다 (DRF 는 로그인한 세션 요청에만 확인한다).

    로그인 CSRF: 공격자가 피해자 브라우저를 공격자 계정으로 로그인시켜, 피해자가 올린 명세서를 가로채는 것을 막는다.
    """
    SessionAuthentication().enforce_csrf(request)


def _credentials(request):
    username = str(request.data.get("username", "")).strip()
    password = str(request.data.get("password", ""))
    return username, password


class MeView(APIView):
    """현재 로그인한 사용자. 대시보드가 처음 열릴 때 부르며 csrftoken 쿠키도 이때 받는다."""

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        if request.user and request.user.is_authenticated:
            return Response(_user_body(request.user))
        return Response({"user": None})


class AuthFormView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        _enforce_csrf(request)


class SignupView(AuthFormView):
    def post(self, request):
        username, password = _credentials(request)
        errors = {}
        try:
            User.username_validator(username)
            if not 3 <= len(username) <= 30:
                raise ValidationError("아이디는 3~30자로 정해 주세요.")
        except ValidationError as e:
            errors["username"] = [str(m) for m in e.messages]
        candidate = User(username=username)
        try:
            validate_password(password, user=candidate)
        except ValidationError as e:
            errors["password"] = list(e.messages)
        if errors:
            return Response({"error": "invalid", "detail": "입력을 확인해 주세요.", "fields": errors},
                            status.HTTP_400_BAD_REQUEST)
        try:
            with transaction.atomic():
                user = User.objects.create_user(username=username, password=password)
        except IntegrityError:
            return Response({"error": "taken", "detail": "이미 쓰고 있는 아이디예요.",
                             "fields": {"username": ["이미 쓰고 있는 아이디예요."]}}, status.HTTP_400_BAD_REQUEST)
        login(request._request, user)
        return Response(_user_body(user), status.HTTP_201_CREATED)


class LoginView(AuthFormView):
    def post(self, request):
        username, password = _credentials(request)
        user = authenticate(request._request, username=username, password=password)
        if user is None:
            return Response({"error": "invalid_credentials", "detail": "아이디 또는 비밀번호가 맞지 않아요."},
                            status.HTTP_400_BAD_REQUEST)
        login(request._request, user)  # 세션 키와 CSRF 토큰을 새로 만든다 (세션 고정 공격 방지)
        return Response(_user_body(user))


class LogoutView(APIView):
    authentication_classes = [SessionAuthentication]  # DRF 가 CSRF 를 확인한다
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request._request)
        return Response({"user": None})
