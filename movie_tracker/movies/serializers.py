from rest_framework import serializers
from .models import Movie, UserMovie, Genre, Person, MovieCast, MovieCrew

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
        fields = ['id', 'name']

class MovieSerializer(serializers.ModelSerializer):
    genres = GenreSerializer(many=True, read_only=True)
    cast = MovieCastSerializer(source='moviecast_set', many=True, read_only=True)
    crew = MovieCrewSerializer(source='moviecrew_set', many=True, read_only=True)
    user_rating = serializers.SerializerMethodField()
    in_collection = serializers.SerializerMethodField()
    
    class Meta:
        model = Movie
        fields = [
            'id', 'tmdb_id', 'title', 'overview', 'poster_path',
            'backdrop_path', 'release_date', 'vote_average',
            'imdb_rating', 'rotten_tomatoes_rating', 'genres',
            'cast', 'crew', 'user_rating', 'in_collection'
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

class UserMovieSerializer(serializers.ModelSerializer):
    movie_details = MovieSerializer(source='movie', read_only=True)
    
    class Meta:
        model = UserMovie
        fields = ['id', 'movie', 'movie_details', 'rating', 'notes', 'watched_at']
        read_only_fields = ['watched_at']