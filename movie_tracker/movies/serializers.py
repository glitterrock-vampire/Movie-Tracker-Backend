from rest_framework import serializers
from .models import Movie, UserMovie, Genre, Person, MovieCast, MovieCrew
from datetime import datetime

class PersonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Person
        fields = ['id', 'tmdb_id', 'name', 'profile_path']

class MovieCastSerializer(serializers.ModelSerializer):
    person = PersonSerializer()
    class Meta:
        model = MovieCast
        fields = ['person', 'character', 'order']

class MovieCrewSerializer(serializers.ModelSerializer):
    person = PersonSerializer()
    class Meta:
        model = MovieCrew
        fields = ['person', 'department', 'job']

class GenreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Genre
        fields = ['id', 'tmdb_id', 'name']  # Added tmdb_id for searches

class MovieSerializer(serializers.ModelSerializer):
    genres = GenreSerializer(many=True, read_only=True)
    cast = MovieCastSerializer(source='moviecast_set', many=True, read_only=True)
    crew = MovieCrewSerializer(source='moviecrew_set', many=True, read_only=True)
    user_rating = serializers.SerializerMethodField()
    in_collection = serializers.SerializerMethodField()
    user_has_watched = serializers.SerializerMethodField()  # Alias for in_collection for frontend compatibility

    # ✅ Fix: Allow null release dates and accept multiple formats
    release_date = serializers.DateField(
        
        required=False,
        default=None,
        allow_null=True,  # ✅ Allow NULL values
        format="%Y-%m-%d",  # ✅ Ensure output is in YYYY-MM-DD
        input_formats=[
            "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d",
            "%d %b %Y", "%d %B %Y", None, "",  # ✅ Allow multiple formats
        ]
    )

    class Meta:
        model = Movie
        fields = [
            'id', 'tmdb_id', 'title', 'overview', 'poster_path',
            'backdrop_path', 'release_date', 'vote_average',
            'imdb_rating', 'rotten_tomatoes_rating', 'genres',
            'cast', 'crew', 'user_rating', 'in_collection', 'user_has_watched'
        ]

    def get_user_rating(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            try:
                user_movie = UserMovie.objects.get(
                    user=request.user,
                    movie=obj
                )
                return user_movie.rating
            except UserMovie.DoesNotExist:
                return None
        return None

    def get_in_collection(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return UserMovie.objects.filter(
                user=request.user,
                movie=obj
            ).exists()
        return False
        
    # Alias for in_collection to maintain compatibility with frontend
    def get_user_has_watched(self, obj):
        return self.get_in_collection(obj)

class UserMovieSerializer(serializers.ModelSerializer):
    movie_details = MovieSerializer(source='movie', read_only=True)
    class Meta:
        model = UserMovie
        fields = ['id', 'movie', 'movie_details', 'rating', 'notes', 'watched_at']
        read_only_fields = ['watched_at']