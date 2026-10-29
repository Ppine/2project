from rest_framework import authentication, exceptions

from .models import AgentToken


class AgentTokenAuthentication(authentication.BaseAuthentication):
    """`Authorization: Bearer <token>` 으로 에이전트 토큰을 확인한다."""

    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode()
        if not header:
            return None
        keyword, _, raw = header.partition(" ")
        if keyword != self.keyword or not raw:
            raise exceptions.AuthenticationFailed()
        token = AgentToken.verify(raw.strip())
        if not token:
            raise exceptions.AuthenticationFailed()
        return (AgentPrincipal(token), token)

    def authenticate_header(self, request):
        return self.keyword


class AgentPrincipal:
    is_authenticated = True

    def __init__(self, token: AgentToken):
        self.token = token

