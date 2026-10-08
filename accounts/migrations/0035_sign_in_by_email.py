import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0034_remove_theme"),
    ]

    operations = [
        # The cooldown is keyed on the email typed now, not a username
        migrations.RenameField(
            model_name="loginthrottle",
            old_name="username",
            new_name="login",
        ),
        migrations.AlterField(
            model_name="loginthrottle",
            name="login",
            field=models.CharField(max_length=254, unique=True),
        ),
        migrations.AddConstraint(
            model_name="customuser",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("email"),
                condition=models.Q(("email", ""), _negated=True),
                name="accounts_customuser_email_unique",
            ),
        ),
    ]
