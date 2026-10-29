from rest_framework import exceptions
from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is not None and isinstance(exc, (exceptions.AuthenticationFailed, exceptions.NotAuthenticated)):
        response.data = {"error": "invalid_token", "detail": "토큰이 없거나 유효하지 않습니다."}
    return response
