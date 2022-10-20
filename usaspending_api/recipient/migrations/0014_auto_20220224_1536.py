# Generated by Django 2.2.17 on 2022-02-24 15:36
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('recipient', '0013_create_uei_indexes_for_performance'),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP INDEX recipient_l_duns_bb057a_partial",
            reverse_sql="CREATE UNIQUE INDEX recipient_l_duns_bb057a_partial ON recipient_lookup (duns) WHERE duns IS NOT NULL"
        ),
        migrations.RunSQL(
            sql="CREATE INDEX recipient_l_duns_a43c07_partial ON recipient_lookup (duns) WHERE duns IS NOT NULL",
            reverse_sql="DROP INDEX recipient_l_duns_a43c07_partial",
        ),
        migrations.AlterField(
            model_name='recipientlookup',
            name='duns',
            field=models.TextField(null=True),
        ),
    ]