# Generated by Django 5.0.2 on 2025-02-25 10:04

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('movies', '0004_alter_movie_cast_alter_moviecast_movie'),
    ]

    operations = [
        migrations.AlterField(
            model_name='movie',
            name='cast',
            field=models.ManyToManyField(related_name='movies_cast', through='movies.MovieCast', to='movies.person'),
        ),
        migrations.AlterField(
            model_name='movie',
            name='crew',
            field=models.ManyToManyField(related_name='movies_crew', through='movies.MovieCrew', to='movies.person'),
        ),
        migrations.AlterField(
            model_name='moviecast',
            name='person',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='person_cast', to='movies.person'),
        ),
        migrations.AlterField(
            model_name='moviecrew',
            name='movie',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='movie_crew', to='movies.movie'),
        ),
        migrations.AlterField(
            model_name='moviecrew',
            name='person',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='person_crew', to='movies.person'),
        ),
        migrations.AlterField(
            model_name='usermovie',
            name='movie',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='user_movies', to='movies.movie'),
        ),
    ]
