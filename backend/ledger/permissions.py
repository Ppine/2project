from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import AgentToken


class DashboardPermission(BasePermission):
    """웹 대시보드 API.

    로그인(세션)한 사용자는 자기 데이터를 읽고 쓴다. 에이전트·앱 토큰은 그 토큰 주인의 데이터를 읽기만 한다
    (README 원칙: 에이전트는 읽기 전용).
    """

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if isinstance(request.auth, AgentToken):
            return request.method in SAFE_METHODS
        return True


class IsAppToken(BasePermission):
    """결제 알림 전송은 폰 앱 토큰만. 에이전트(read) 토큰은 읽기만 한다."""

    def has_permission(self, request, view):
        return isinstance(request.auth, AgentToken) and request.auth.scope == AgentToken.APP
