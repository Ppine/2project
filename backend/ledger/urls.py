from django.urls import path

from . import api

urlpatterns = [
    path("statements/", api.StatementUploadView.as_view()),
    path("subscriptions/", api.SubscriptionListView.as_view()),
    path("charges/explain/", api.ExplainChargeView.as_view()),
    path("notifications/", api.NotificationIngestView.as_view()),
    path("merchant-aliases/", api.MerchantAliasView.as_view()),
]
