# Generated by Django 5.0.2 on 2025-02-23 03:09

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('movies', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='person',
            name='profile_path',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
