from django.urls import path
from . import views

urlpatterns = [
    # Movie routes
    path('movies/search/', views.search_movies, name='search-movies'),
    path('movies/<int:tmdb_id>/', views.get_movie_details, name='movie-details'),
    path('movies/<int:tmdb_id>/recommendations/', views.get_movie_recommendations, name='movie-recommendations'),  # New endpoint
    path('movies/popular/', views.get_popular_movies, name='popular-movies'),
    path('movies/now_showing/', views.get_now_showing_movies, name='now-showing-movies'),
    path('movies/<int:tmdb_id>/videos/', views.get_movie_videos, name='movie-videos'),  # NEW VIDEO ENDPOINT

    # Collection routes
    path('collection/', views.get_collection, name='get-collection'),
    path('collection/<int:tmdb_id>/', views.add_to_collection, name='add-to-collection'),
    path('collection/<int:tmdb_id>/remove/', views.remove_from_collection, name='remove-from-collection'),
    
    # Rating route
    path('movies/<int:tmdb_id>/rate/', views.rate_movie, name='rate-movie'),
    
    # People routes
    path('people/search/', views.search_people, name='search-people'),
    path('people/<int:person_id>/movies/', views.get_movies_by_person, name='movies-by-person'),
    
    # Genre routes
    path('genres/', views.get_genres, name='genres-list'),
    path('genres/<int:genre_id>/movies/', views.get_movies_by_genre, name='movies-by-genre'),
]