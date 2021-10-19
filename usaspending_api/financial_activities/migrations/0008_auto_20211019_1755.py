# Generated by Django 2.2.23 on 2021-10-19 17:55

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('financial_activities', '0007_drop_old_defc_field'),
        ('references', '0057_drop_old_defc_field'),
    ]

    operations = [
        migrations.AlterField(
            model_name='financialaccountsbyprogramactivityobjectclass',
            name='disaster_emergency_fund',
            field=models.ForeignKey(
                blank=True,
                db_column='disaster_emergency_fund_code',
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                to='references.DisasterEmergencyFundCode'
            ),
        ),
    ]
