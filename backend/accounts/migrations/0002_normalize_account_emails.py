import accounts.fields
from django.db import migrations, models


def normalize_existing_emails(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    users = User.objects.using(schema_editor.connection.alias)
    # Keep the historical rule here: future changes must not alter this migration.
    seen = set()
    changes = []
    for pk, email in users.values_list("pk", "email").iterator():
        normalized = email.strip().lower()
        if normalized in seen:
            # Never include addresses or credentials in migration errors.
            raise RuntimeError(
                "Account emails collide after normalization. No accounts were changed. "
                "Resolve conflicting accounts manually before retrying this migration."
            )
        seen.add(normalized)
        if email != normalized:
            changes.append((pk, normalized))
    # Audit every account BEFORE changing any row. Passwords/IDs are untouched.
    for pk, email in changes:
        users.filter(pk=pk).update(email=email)


class Migration(migrations.Migration):
    atomic = True
    dependencies = [("accounts", "0001_initial")]
    operations = [
        migrations.RunPython(normalize_existing_emails, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="email",
            field=accounts.fields.NormalizedEmailField(max_length=254, unique=True),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(email=models.Func(models.F("email"), function="swipehome_normalize_email")),
                name="accounts_user_normalized_email",
            ),
        ),
    ]
