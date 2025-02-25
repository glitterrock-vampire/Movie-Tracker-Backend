# movie_tracker/movies/urls.py
from django.urls import path
from . import views
from rest_framework_simplejwt.views import (  # Import JWT token views
    TokenObtainPairView,
    TokenRefreshView,
)

app_name = 'movies'  # Namespace for the app to avoid URL conflicts

urlpatterns = [
    # Authentication Endpoints
    path('register/', views.register, name='register'),  # User registration
    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),  # Obtain JWT tokens
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),  # Refresh JWT token

    # Movie Search and Details
    path('movies/search/', views.search_movies, name='search_movies'),  # Search movies by query
    path('movies/<int:tmdb_id>/', views.get_movie_details, name='movie_details'),  # Get movie details by TMDB ID
    path('movies/<int:tmdb_id>/videos/', views.get_movie_videos, name='movie_videos'),  # Get movie videos by TMDB ID

    # Movie Listings
    path('movies/popular/', views.get_popular_movies, name='popular_movies'),  # Get popular movies
    path('movies/now_showing/', views.get_now_showing_movies, name='now_showing_movies'),  # Get now showing movies

    # User Collection Management
    path('collection/', views.get_collection, name='get_collection'),  # Get user's movie collection
    path('collection/<int:tmdb_id>/', views.add_to_collection, name='add_to_collection'),  # Add movie to collection
    path('collection/<int:tmdb_id>/remove/', views.remove_from_collection, name='remove_from_collection'),  # Remove movie from collection
    path('movies/<int:tmdb_id>/rate/', views.rate_movie, name='rate_movie'),  # Rate a movie

    # People and Genres
    path('people/search/', views.search_people, name='search_people'),  # Search people (actors, directors, etc.)
    path('people/<int:person_id>/movies/', views.get_movies_by_person, name='movies_by_person'),  # Get movies by person
    path('genres/', views.get_genres, name='genres'),  # List all genres
    path('genres/<int:genre_id>/movies/', views.get_movies_by_genre, name='movies_by_genre'),  # Get movies by genre

    # Recommendations
    path('recommendations/', views.get_recommendations, name='recommendations'),  # Get AI-driven recommendations
]