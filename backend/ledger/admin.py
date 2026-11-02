from django.contrib import admin

from .models import AgentToken, MerchantAlias, ServiceFee, Statement, SubscriptionState, Transaction

admin.site.register([Statement, Transaction, ServiceFee, MerchantAlias, SubscriptionState])


@admin.register(AgentToken)
class AgentTokenAdmin(admin.ModelAdmin):
    list_display = ["name", "owner", "scope", "created_at", "revoked"]
    readonly_fields = ["token_hash"]
