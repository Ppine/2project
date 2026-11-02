"""모든 사용자 데이터에 owner 를 붙인다.

이전까지는 데모 사용자 1명이 데이터를 공유했다. 기존 데이터가 있으면 'demo' 계정(비밀번호 없음)으로 옮긴다.
`python manage.py create_user demo` 로 비밀번호를 정하면 그 계정으로 로그인해 기존 데이터를 볼 수 있다.
"""

import django.db.models.deletion
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import migrations, models

OWNED = ["statement", "transaction", "merchantalias", "subscriptionstate", "agenttoken"]


def assign_existing_rows(apps, schema_editor):
    models_ = [apps.get_model("ledger", name) for name in OWNED]
    if not any(m.objects.exists() for m in models_):
        return
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    demo, created = User.objects.get_or_create(username="demo")
    if created:
        demo.password = make_password(None)  # 로그인 불가. create_user 명령어로 비밀번호를 정한다
        demo.save(update_fields=["password"])
    for m in models_:
        m.objects.filter(owner__isnull=True).update(owner=demo)


def owner_field(null):
    return models.ForeignKey(null=null, on_delete=django.db.models.deletion.CASCADE, related_name="+",
                             to=settings.AUTH_USER_MODEL)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("ledger", "0003_statement_history_subscription_state"),
    ]

    operations = [
        *[migrations.AddField(model_name=name, name="owner", field=owner_field(null=True)) for name in OWNED],
        migrations.RunPython(assign_existing_rows, migrations.RunPython.noop),
        *[migrations.AlterField(model_name=name, name="owner", field=owner_field(null=False)) for name in OWNED],
        migrations.RemoveConstraint(model_name="merchantalias", name="unique_alias"),
        migrations.AddConstraint(
            model_name="merchantalias",
            constraint=models.UniqueConstraint(fields=("owner", "cleaned_merchant", "amount"), name="unique_alias"),
        ),
        migrations.RemoveConstraint(model_name="subscriptionstate", name="unique_subscription_state"),
        migrations.AddConstraint(
            model_name="subscriptionstate",
            constraint=models.UniqueConstraint(fields=("owner", "cleaned_merchant", "amount"),
                                               name="unique_subscription_state"),
        ),
        migrations.AlterField(model_name="transaction", name="notification_id",
                              field=models.CharField(max_length=255, null=True)),
        migrations.AddConstraint(
            model_name="transaction",
            constraint=models.UniqueConstraint(fields=("owner", "notification_id"), name="unique_notification"),
        ),
    ]
