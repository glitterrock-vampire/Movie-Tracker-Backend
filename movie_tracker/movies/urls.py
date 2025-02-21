from django.urls import path
from . import views

urlpatterns = [
    path('movies/search/', views.search_movies, name='search-movies'),
        path('movies/<int:tmdb_id>/', views.get_movie_details, name='movie-details'),  

    path('movies/popular/', views.get_popular_movies, name='popular-movies'),
    path('collection/', views.get_collection, name='get-collection'),
    path('collection/<int:tmdb_id>/', views.add_to_collection, name='add-to-collection'),
    path('collection/<int:tmdb_id>/remove/', views.remove_from_collection, name='remove-from-collection'),
    path('movies/<int:tmdb_id>/rate/', views.rate_movie, name='rate-movie'),
    
    # New endpoints
    path('people/search/', views.search_people, name='search-people'),
    path('people/<int:person_id>/movies/', views.get_movies_by_person, name='movies-by-person'),
    path('genres/', views.get_genres, name='genres-list'),
    path('genres/<int:genre_id>/movies/', views.get_movies_by_genre, name='movies-by-genre'),
    path('recommendations/', views.get_recommendations, name='recommendations'),
    path('movies/now_showing/', views.get_now_showing_movies, name='now-showing-movies'),
    path('movies/popular/', views.get_popular_movies, name='popular-movies'),
]