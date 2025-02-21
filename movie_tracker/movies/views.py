from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User
from rest_framework_simplejwt.tokens import RefreshToken
from .models import Movie, UserMovie, Person, Genre, MovieCrew, MovieCast
from .serializers import (
    MovieSerializer, UserMovieSerializer, PersonSerializer,
    GenreSerializer, MovieCastSerializer, MovieCrewSerializer
)
from .services import TMDBService


@api_view(['POST'])
@permission_classes([AllowAny])  # Explicitly allow any user to register
def register(request):
    try:
        username = request.data.get('username')
        password = request.data.get('password')
        email = request.data.get('email', '')

        if not username or not password:
            return Response({
                'error': 'Username and password are required'
            }, status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(username=username).exists():
            return Response({
                'error': 'Username already exists'
            }, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.create_user(
            username=username,
            password=password,
            email=email
        )

        refresh = RefreshToken.for_user(user)

        return Response({
            'message': 'User created successfully',
            'tokens': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({
            'error': str(e)
        }, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
def search_movies(request):
    query = request.GET.get('query', '')
    if not query:
        return Response(
            {"error": "Search query is required"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    tmdb = TMDBService()
    try:
        results = tmdb.search_movies(query)
        # Store movies in our database for future reference
        movies = []
        for result in results.get('results', []):
            movie, created = Movie.objects.get_or_create(
                tmdb_id=result['id'],
                defaults={
                    'title': result['title'],
                    'overview': result.get('overview', ''),
                    'poster_path': result.get('poster_path', ''),
                    'backdrop_path': result.get('backdrop_path', ''),
                    'release_date': result.get('release_date'),
                    'vote_average': result.get('vote_average'),
                }
            )
            movies.append(movie)
        
        serializer = MovieSerializer(movies, many=True, context={'request': request})
        return Response({
            'results': serializer.data,
            'page': results.get('page', 1),
            'total_pages': results.get('total_pages', 1)
        })
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
@api_view(['GET'])
def get_movie_details(request, tmdb_id):
    tmdb = TMDBService()
    try:
        # First check our database
        try:
            movie = Movie.objects.get(tmdb_id=tmdb_id)
            needs_update = True
        except Movie.DoesNotExist:
            # Get movie data from TMDB
            movie_data = tmdb._make_request(f'movie/{tmdb_id}')
            credits_data = tmdb._make_request(f'movie/{tmdb_id}/credits')
            
            # Create the movie
            movie = Movie.objects.create(
                tmdb_id=tmdb_id,
                title=movie_data['title'],
                overview=movie_data.get('overview', ''),
                poster_path=movie_data.get('poster_path', ''),
                backdrop_path=movie_data.get('backdrop_path', ''),
                release_date=movie_data.get('release_date'),
                vote_average=movie_data.get('vote_average')
            )
            
            # Handle genres
            for genre_data in movie_data.get('genres', []):
                genre, _ = Genre.objects.get_or_create(
                    tmdb_id=genre_data['id'],
                    defaults={'name': genre_data['name']}
                )
                movie.genres.add(genre)
            
            # Handle cast
            for cast_data in credits_data.get('cast', [])[:10]:  # Top 10 cast members
                person, _ = Person.objects.get_or_create(
                    tmdb_id=cast_data['id'],
                    defaults={
                        'name': cast_data['name'],
                        'profile_path': cast_data.get('profile_path', '')
                    }
                )
                MovieCast.objects.create(
                    movie=movie,
                    person=person,
                    character=cast_data['character'],
                    order=cast_data['order']
                )
            
            # Handle crew
            for crew_data in credits_data.get('crew', []):
                if crew_data['job'] in ['Director', 'Screenplay', 'Writer']:
                    person, _ = Person.objects.get_or_create(
                        tmdb_id=crew_data['id'],
                        defaults={
                            'name': crew_data['name'],
                            'profile_path': crew_data.get('profile_path', '')
                        }
                    )
                    MovieCrew.objects.create(
                        movie=movie,
                        person=person,
                        job=crew_data['job'],
                        department=crew_data['department']
                    )
            needs_update = False
        
        if needs_update:
            # Update the movie with fresh data
            movie_data = tmdb._make_request(f'movie/{tmdb_id}')
            credits_data = tmdb._make_request(f'movie/{tmdb_id}/credits')
            
            # Update basic info
            movie.title = movie_data['title']
            movie.overview = movie_data.get('overview', '')
            movie.poster_path = movie_data.get('poster_path', '')
            movie.backdrop_path = movie_data.get('backdrop_path', '')
            movie.release_date = movie_data.get('release_date')
            movie.vote_average = movie_data.get('vote_average')
            movie.save()
            
            # Update genres
            movie.genres.clear()
            for genre_data in movie_data.get('genres', []):
                genre, _ = Genre.objects.get_or_create(
                    tmdb_id=genre_data['id'],
                    defaults={'name': genre_data['name']}
                )
                movie.genres.add(genre)
            
            # Update cast and crew
            MovieCast.objects.filter(movie=movie).delete()
            MovieCrew.objects.filter(movie=movie).delete()
            
            for cast_data in credits_data.get('cast', [])[:10]:
                person, _ = Person.objects.get_or_create(
                    tmdb_id=cast_data['id'],
                    defaults={
                        'name': cast_data['name'],
                        'profile_path': cast_data.get('profile_path', '')
                    }
                )
                MovieCast.objects.create(
                    movie=movie,
                    person=person,
                    character=cast_data['character'],
                    order=cast_data['order']
                )
            
            for crew_data in credits_data.get('crew', []):
                if crew_data['job'] in ['Director', 'Screenplay', 'Writer']:
                    person, _ = Person.objects.get_or_create(
                        tmdb_id=crew_data['id'],
                        defaults={
                            'name': crew_data['name'],
                            'profile_path': crew_data.get('profile_path', '')
                        }
                    )
                    MovieCrew.objects.create(
                        movie=movie,
                        person=person,
                        job=crew_data['job'],
                        department=crew_data['department']
                    )
        
        # Serialize the response
        serializer = MovieSerializer(movie, context={'request': request})
        return Response(serializer.data)
    
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_404_NOT_FOUND
        )
@api_view(['GET'])
def get_popular_movies(request):
    page = request.GET.get('page', 1)
    tmdb = TMDBService()
    try:
        results = tmdb.get_popular_movies(page=page)
        movies = []
        for result in results.get('results', []):
            movie, created = Movie.objects.get_or_create(
                tmdb_id=result['id'],
                defaults={
                    'title': result['title'],
                    'overview': result.get('overview', ''),
                    'poster_path': result.get('poster_path', ''),
                    'backdrop_path': result.get('backdrop_path', ''),
                    'release_date': result.get('release_date'),
                    'vote_average': result.get('vote_average'),
                }
            )
            movies.append(movie)
        
        serializer = MovieSerializer(movies, many=True, context={'request': request})
        return Response({
            'results': serializer.data,
            'page': results.get('page', 1),
            'total_pages': results.get('total_pages', 1)
        })
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_to_collection(request, tmdb_id):
    tmdb = TMDBService()
    try:
        # First check our database
        try:
            movie = Movie.objects.get(tmdb_id=tmdb_id)
        except Movie.DoesNotExist:
            movie_data = tmdb.get_movie_details(tmdb_id)
            movie = Movie.objects.create(
                tmdb_id=tmdb_id,
                title=movie_data['title'],
                overview=movie_data.get('overview', ''),
                poster_path=movie_data.get('poster_path', ''),
                backdrop_path=movie_data.get('backdrop_path', ''),
                release_date=movie_data.get('release_date'),
                vote_average=movie_data.get('vote_average'),
            )

        user_movie, created = UserMovie.objects.get_or_create(
            user=request.user,
            movie=movie,
            defaults={
                'rating': request.data.get('rating'),
                'notes': request.data.get('notes', '')
            }
        )

        if not created:
            user_movie.rating = request.data.get('rating', user_movie.rating)
            user_movie.notes = request.data.get('notes', user_movie.notes)
            user_movie.save()

        serializer = UserMovieSerializer(user_movie)
        return Response(serializer.data)
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def remove_from_collection(request, tmdb_id):
    try:
        movie = get_object_or_404(Movie, tmdb_id=tmdb_id)
        result = UserMovie.objects.filter(user=request.user, movie=movie).delete()
        if result[0] == 0:
            return Response(
                {"error": "Movie not found in collection"},
                status=status.HTTP_404_NOT_FOUND
            )
        return Response(status=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_404_NOT_FOUND
        )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_collection(request):
    try:
        user_movies = UserMovie.objects.select_related('movie').filter(user=request.user)
        serializer = UserMovieSerializer(user_movies, many=True)
        return Response(serializer.data)
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def rate_movie(request, tmdb_id):
    try:
        movie = get_object_or_404(Movie, tmdb_id=tmdb_id)
        rating = request.data.get('rating')
        
        if not rating or not isinstance(rating, (int, float)) or not (1 <= rating <= 5):
            return Response(
                {"error": "Rating must be between 1 and 5"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        user_movie, created = UserMovie.objects.get_or_create(
            user=request.user,
            movie=movie,
            defaults={'rating': rating}
        )
        
        if not created:
            user_movie.rating = rating
            user_movie.save()
        
        serializer = UserMovieSerializer(user_movie)
        return Response(serializer.data)
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )
@api_view(['GET'])
def search_people(request):
    query = request.GET.get('query', '')
    if not query:
        return Response(
            {"error": "Search query is required"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    page = request.GET.get('page', 1)
    tmdb = TMDBService()
    try:
        results = tmdb.search_people(query, page=page)
        # Store people in our database for future reference
        people = []
        for result in results.get('results', []):
            person, created = Person.objects.get_or_create(
                tmdb_id=result['id'],
                defaults={
                    'name': result['name'],
                    'profile_path': result.get('profile_path', ''),
                }
            )
            people.append(person)
        
        serializer = PersonSerializer(people, many=True)
        return Response({
            'results': serializer.data,
            'page': results.get('page', 1),
            'total_pages': results.get('total_pages', 1)
        })
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
@api_view(['GET'])
def get_movies_by_person(request, person_id):
    try:
        person = get_object_or_404(Person, tmdb_id=person_id)
        tmdb = TMDBService()
        results = tmdb.get_movies_by_person(person_id)
        
        movies = []
        for result in results.get('cast', []) + results.get('crew', []):
            movie, created = Movie.objects.get_or_create(
                tmdb_id=result['id'],
                defaults={
                    'title': result['title'],
                    'overview': result.get('overview', ''),
                    'poster_path': result.get('poster_path', ''),
                    'backdrop_path': result.get('backdrop_path', ''),
                    'release_date': result.get('release_date'),
                    'vote_average': result.get('vote_average'),
                }
            )
            movies.append(movie)
        
        serializer = MovieSerializer(movies, many=True, context={'request': request})
        return Response(serializer.data)
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_404_NOT_FOUND
        )
        

@api_view(['GET'])
def get_genres(request):
    try:
        genres = Genre.objects.all()
        serializer = GenreSerializer(genres, many=True)
        return Response(serializer.data)
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
def get_movies_by_genre(request, genre_id):
    page = request.GET.get('page', 1)
    try:
        genre = get_object_or_404(Genre, tmdb_id=genre_id)
        tmdb = TMDBService()
        data = tmdb._make_request('discover/movie', {
            'with_genres': genre_id,
            'page': page,
            'sort_by': 'popularity.desc'
        })
        
        movies = []
        for result in data.get('results', []):
            movie, created = Movie.objects.get_or_create(
                tmdb_id=result['id'],
                defaults={
                    'title': result['title'],
                    'overview': result.get('overview', ''),
                    'poster_path': result.get('poster_path', ''),
                    'backdrop_path': result.get('backdrop_path', ''),
                    'release_date': result.get('release_date'),
                    'vote_average': result.get('vote_average'),
                }
            )
            movies.append(movie)
        
        serializer = MovieSerializer(movies, many=True, context={'request': request})
        return Response({
            'results': serializer.data,
            'page': data.get('page', 1),
            'total_pages': data.get('total_pages', 1)
        })
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_404_NOT_FOUND
        )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_recommendations(request):
    try:
        tmdb = TMDBService()
        results = tmdb.get_recommendations(request.user)
        
        movies = []
        for result in results.get('results', []):
            movie, created = Movie.objects.get_or_create(
                tmdb_id=result['id'],
                defaults={
                    'title': result['title'],
                    'overview': result.get('overview', ''),
                    'poster_path': result.get('poster_path', ''),
                    'backdrop_path': result.get('backdrop_path', ''),
                    'release_date': result.get('release_date'),
                    'vote_average': result.get('vote_average'),
                }
            )
            movies.append(movie)
        
        serializer = MovieSerializer(movies, many=True, context={'request': request})
        return Response({
            'results': serializer.data
        })
    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )