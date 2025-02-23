from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import CustomUser, Movie, UserMovie, Person, Genre, MovieCrew, MovieCast
from .serializers import (
    MovieSerializer, UserMovieSerializer, PersonSerializer,
    GenreSerializer, MovieCastSerializer, MovieCrewSerializer
)
from .services import TMDBService

@api_view(['POST'])
@permission_classes([AllowAny])  # Explicitly allow any user to register
def register(request):
    try:
        email = request.data.get('email')
        password = request.data.get('password')

        if not email or not password:
            return Response({'error': 'Email and password are required'}, 
                          status=status.HTTP_400_BAD_REQUEST)

        # Check if user already exists
        if CustomUser.objects.filter(email=email).exists():
            return Response({'error': 'User with this email already exists'}, 
                          status=status.HTTP_400_BAD_REQUEST)

        # Create new user with CustomUser
        user = CustomUser.objects.create_user(
            email=email,
            password=password
        )

        # Generate JWT tokens
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)

        return Response({
            'message': 'User created successfully',
            'tokens': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({'error': str(e)}, 
                       status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
        # Check if the movie already exists in DB
        movie = Movie.objects.get(tmdb_id=tmdb_id)
        needs_update = True
    except Movie.DoesNotExist:
        # Fetch from TMDB since it's missing in DB
        movie_data = tmdb._make_request(f'movie/{tmdb_id}')
        
        if not movie_data or "title" not in movie_data:
            return Response({"error": "Movie not found on TMDB"}, status=status.HTTP_404_NOT_FOUND)

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
        
        needs_update = False  # We just fetched fresh data, no update needed

    # Fetch new data if needed
    if needs_update:
        movie_data = tmdb._make_request(f'movie/{tmdb_id}')
        
        movie.title = movie_data['title']
        movie.overview = movie_data.get('overview', '')
        movie.poster_path = movie_data.get('poster_path', '')
        movie.backdrop_path = movie_data.get('backdrop_path', '')
        movie.release_date = movie_data.get('release_date')
        movie.vote_average = movie_data.get('vote_average')
        movie.save()

    serializer = MovieSerializer(movie, context={'request': request})
    return Response(serializer.data)
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
def get_movie_recommendations(request, tmdb_id):
    tmdb = TMDBService()
    try:
        data = tmdb._make_request(f'movie/{tmdb_id}/recommendations')
        results = data.get('results', [])

        movies = []
        for result in results:
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
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        
        
@api_view(['GET'])
def get_movie_videos(request, tmdb_id):
    """
    Fetches videos (trailers, teasers, etc.) for a specific movie from TMDB.
    """
    tmdb = TMDBService()
    try:
        response = tmdb._make_request(f'movie/{tmdb_id}/videos')
        results = response.get('results', [])

        videos = []
        for video in results:
            videos.append({
                "id": video.get("id"),
                "name": video.get("name"),
                "key": video.get("key"),
                "site": video.get("site"),
                "type": video.get("type"),
                "size": video.get("size"),
                "official": video.get("official", False),
                "published_at": video.get("published_at"),
            })

        return Response({
            "tmdb_id": tmdb_id,
            "videos": videos
        })
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
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

@api_view(['GET'])
def get_now_showing_movies(request):
    tmdb = TMDBService()
    page = request.GET.get('page', 1)
    try:
        data = tmdb._make_request('movie/now_playing', {'page': page})
        results = data.get('results', [])

        movies = []
        for result in results:
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

        serializer = MovieSerializer(movies, many=True)
        return Response({
            'results': serializer.data,
            'page': data.get('page', 1),
            'total_pages': data.get('total_pages', 1)
        })
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
def get_popular_movies(request):
    tmdb = TMDBService()
    page = request.GET.get('page', 1)
    try:
        data = tmdb.get_popular_movies(page=page)
        results = data.get('results', [])

        movies = []
        for result in results:
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

        serializer = MovieSerializer(movies, many=True)
        return Response({
            'results': serializer.data,
            'page': data.get('page', 1),
            'total_pages': data.get('total_pages', 1)
        })
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)