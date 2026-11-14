from django.urls import path

from . import accounts, api

urlpatterns = [
    path("auth/me/", accounts.MeView.as_view()),
    path("auth/signup/", accounts.SignupView.as_view()),
    path("auth/login/", accounts.LoginView.as_view()),
    path("auth/logout/", accounts.LogoutView.as_view()),
    path("statements/", api.StatementUploadView.as_view()),
    path("statements/<int:statement_id>/", api.StatementDetailView.as_view()),
    path("subscriptions/", api.SubscriptionListView.as_view()),
    path("subscriptions/state/", api.SubscriptionStateView.as_view()),
    path("charges/explain/", api.ExplainChargeView.as_view()),
    path("notifications/", api.NotificationIngestView.as_view()),
    path("service-candidates/", api.ServiceCandidateView.as_view()),
    path("merchant-aliases/", api.MerchantAliasView.as_view()),
]
