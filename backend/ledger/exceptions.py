from rest_framework import exceptions
from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return response
    if isinstance(exc, (exceptions.AuthenticationFailed, exceptions.NotAuthenticated)):
        request = context.get("request")
        if request is not None and request.headers.get("Authorization"):
            response.data = {"error": "invalid_token", "detail": "토큰이 없거나 유효하지 않습니다."}
        else:
            response.data = {"error": "auth_required", "detail": "로그인하거나 토큰을 보내 주세요."}
    elif isinstance(exc, exceptions.Throttled):
        response.data = {"error": "throttled", "detail": "시도가 너무 많아요. 잠시 후 다시 해 주세요."}
    return response
