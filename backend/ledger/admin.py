from django.contrib import admin

from .models import AgentToken, MerchantAlias, ServiceFee, Statement, Transaction

admin.site.register([Statement, Transaction, ServiceFee, MerchantAlias])


@admin.register(AgentToken)
class AgentTokenAdmin(admin.ModelAdmin):
    list_display = ["name", "scope", "created_at", "revoked"]
    readonly_fields = ["token_hash"]
