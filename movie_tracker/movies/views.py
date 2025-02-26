import os
from datetime import datetime
from rest_framework import status, generics
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.conf import settings
import openai
from .models import CustomUser, Movie, UserMovie, Person, Genre, MovieCrew, MovieCast
from .serializers import (
    MovieSerializer,
    UserMovieSerializer,
    PersonSerializer,
    GenreSerializer,
    MovieCastSerializer,
    MovieCrewSerializer,
)
from .services import TMDBService
from rest_framework import serializers 
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

load_dotenv()  # Load environment variables from .env

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

def parse_recommendations(recommendations_text):
    """Parse GPT-generated recommendations into a structured format."""
    recommendations = []
    lines = recommendations_text.split("\n")
    for line in lines:
        if line.startswith(tuple(str(i) for i in range(1, 6))):
            parts = line.split(", ")
            if len(parts) >= 4:  # Ensure we have title, genre, actors, and directors
                title = parts[0].replace("Title: ", "").strip()
                genre = parts[1].replace("Genre: ", "").strip()
                actors = parts[2].replace("Actors: ", "").strip()
                directors = parts[3].replace("Directors: ", "").strip()
                tmdb_id = parts[4].replace("TMDB_ID: ", "").strip() if len(parts) > 4 and "TMDB_ID" in parts[4] else None
                recommendations.append({
                    "title": title,
                    "genre": genre,
                    "actors": actors,
                    "directors": directors,
                    "tmdb_id": tmdb_id if tmdb_id and tmdb_id.isdigit() else None
                })
    return recommendations

def get_movie_recommendations(user_collection):
    """Generate movie recommendations using OpenAI GPT based on user collection."""
    collection_details = [
        f"Title: {entry['movie_details']['title']}, Genres: {', '.join(g['name'] for g in entry['movie_details']['genres'])}, "
        f"Actors: {', '.join(c['person']['name'] for c in entry['movie_details']['cast'][:3])}, "
        f"Directors: {', '.join(c['person']['name'] for c in entry['movie_details']['crew'] if c['job'] == 'Director')}"
        for entry in user_collection
    ]
    collection_text = "; ".join(collection_details)

    prompt = f"""
    Based on the following user movie collection, recommend 5 movies similar in genre, actors, directors, or theme:
    {collection_text}

    Provide recommendations in this format, ensuring each movie could realistically exist and is similar to the collection:
    1. Title: [Movie Title], Genre: [Genres], Actors: [Main Actors], Directors: [Directors], TMDB_ID: [TMDB ID if known or placeholder]
    2. ...
    """

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a movie recommendation expert knowledgeable about TMDB movie data."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=300,
        temperature=0.7,
    )

    recommendations = response.choices[0].message.content.strip()
    return parse_recommendations(recommendations)

def clean_movie_data(movie_data):
    """Ensure release_date is properly formatted and accepts multiple formats."""
    accepted_formats = ["%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y"]

    if "release_date" in movie_data:
        if not movie_data["release_date"]:  # If empty, set to None
            movie_data["release_date"] = None
        else:
            for fmt in accepted_formats:
                try:
                    movie_data["release_date"] = datetime.strptime(movie_data["release_date"], fmt).date()
                    return movie_data  # Stops once a valid format is found
                except ValueError:
                    continue
            movie_data["release_date"] = None  # If no formats matched, set to None

    return movie_data

# Registration View (AllowAny for public access)
@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    try:
        email = request.data.get('email')
        password = request.data.get('password')

        if not email or not password:
            return Response({'error': 'Email and password are required'}, status=status.HTTP_400_BAD_REQUEST)

        if CustomUser.objects.filter(email=email).exists():
            return Response({'error': 'User with this email already exists'}, status=status.HTTP_400_BAD_REQUEST)

        user = CustomUser.objects.create_user(email=email, password=password)

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
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# Movie Search Views
@api_view(['GET'])
def search_movies(request):
    query = request.GET.get('query', '')
    if not query:
        return Response({"error": "Search query is required"}, status=status.HTTP_400_BAD_REQUEST)

    tmdb = TMDBService()
    try:
        results = tmdb.search_movies(query)
        movies = []
        for result in results.get('results', []):
            movie_data = {
                'tmdb_id': result['id'],
                'title': result['title'],
                'overview': result.get('overview', ''),
                'poster_path': result.get('poster_path', ''),
                'backdrop_path': result.get('backdrop_path', ''),
                'release_date': result.get('release_date'),
                'vote_average': result.get('vote_average'),
            }
            movie_data = clean_movie_data(movie_data)
            movie, created = Movie.objects.get_or_create(tmdb_id=result['id'], defaults=movie_data)
            movies.append(movie)

        serializer = MovieSerializer(movies, many=True, context={'request': request})
        return Response({
            'results': serializer.data,
            'page': results.get('page', 1),
            'total_pages': results.get('total_pages', 1)
        })

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class MovieSearchView(generics.ListAPIView):
    serializer_class = MovieSerializer

    def get_queryset(self):
        query = self.request.query_params.get('query', None)
        if query:
            return Movie.objects.filter(title__icontains=query)
        return Movie.objects.none()

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

@api_view(['GET'])
def get_movie_details(request, tmdb_id):
    tmdb = TMDBService()
    try:
        try:
            movie = Movie.objects.get(tmdb_id=tmdb_id)
            needs_update = True
        except Movie.DoesNotExist:
            movie_data = tmdb._make_request(f'movie/{tmdb_id}')
            if not movie_data or 'status_code' in movie_data:
                logger.error(f"TMDB returned error for {tmdb_id}: {movie_data.get('status_message', 'Unknown error')}")
                return Response({"error": "Movie not found on TMDB"}, status=status.HTTP_404_NOT_FOUND)

            credits_data = tmdb._make_request(f'movie/{tmdb_id}/credits')
            movie = Movie.objects.create(
                tmdb_id=tmdb_id,
                title=movie_data['title'],
                overview=movie_data.get('overview', ''),
                poster_path=movie_data.get('poster_path', ''),
                backdrop_path=movie_data.get('backdrop_path', ''),
                release_date=movie_data.get('release_date'),
                vote_average=movie_data.get('vote_average'),
            )

            for genre_data in movie_data.get('genres', []):
                genre, _ = Genre.objects.get_or_create(tmdb_id=genre_data['id'], defaults={'name': genre_data['name']})
                movie.genres.add(genre)

            for cast_data in credits_data.get('cast', [])[:10]:
                person, _ = Person.objects.get_or_create(
                    tmdb_id=cast_data['id'],
                    defaults={'name': cast_data['name'], 'profile_path': cast_data.get('profile_path', '') or None}
                )
                MovieCast.objects.create(movie=movie, person=person, character=cast_data['character'], order=cast_data['order'])

            for crew_data in credits_data.get('crew', []):
                if crew_data['job'] in ['Director', 'Screenplay', 'Writer']:
                    person, _ = Person.objects.get_or_create(
                        tmdb_id=crew_data['id'],
                        defaults={'name': crew_data['name'], 'profile_path': crew_data.get('profile_path', '') or None}
                    )
                    MovieCrew.objects.create(movie=movie, person=person, job=crew_data['job'], department=crew_data['department'])
            needs_update = False

        if needs_update:
            movie_data = tmdb._make_request(f'movie/{tmdb_id}')
            if not movie_data or 'status_code' in movie_data:
                logger.error(f"TMDB update failed for {tmdb_id}: {movie_data.get('status_message', 'Unknown error')}")
                return Response({"error": "Movie update failed on TMDB"}, status=status.HTTP_404_NOT_FOUND)

            credits_data = tmdb._make_request(f'movie/{tmdb_id}/credits')

            movie.title = movie_data['title']
            movie.overview = movie_data.get('overview', '')
            movie.poster_path = movie_data.get('poster_path', '')
            movie.backdrop_path = movie_data.get('backdrop_path', '')
            movie.release_date = movie_data.get('release_date')
            movie.vote_average = movie_data.get('vote_average')
            movie.save()

            movie.genres.clear()
            for genre_data in movie_data.get('genres', []):
                genre, _ = Genre.objects.get_or_create(tmdb_id=genre_data['id'], defaults={'name': genre_data['name']})
                movie.genres.add(genre)

            MovieCast.objects.filter(movie=movie).delete()
            MovieCrew.objects.filter(movie=movie).delete()

            for cast_data in credits_data.get('cast', [])[:10]:
                person, _ = Person.objects.get_or_create(
                    tmdb_id=cast_data['id'],
                    defaults={'name': cast_data['name'], 'profile_path': cast_data.get('profile_path', '') or None}
                )
                MovieCast.objects.create(movie=movie, person=person, character=cast_data['character'], order=cast_data['order'])

            for crew_data in credits_data.get('crew', []):
                if crew_data['job'] in ['Director', 'Screenplay', 'Writer']:
                    person, _ = Person.objects.get_or_create(
                        tmdb_id=crew_data['id'],
                        defaults={'name': crew_data['name'], 'profile_path': crew_data.get('profile_path', '') or None}
                    )
                    MovieCrew.objects.create(movie=movie, person=person, job=crew_data['job'], department=crew_data['department'])

        user_rating = None
        if request.user.is_authenticated:
            user_movie = UserMovie.objects.filter(user=request.user, movie=movie).first()
            user_rating = user_movie.rating if user_movie else None

        return Response({
            "tmdb_id": movie.tmdb_id,
            "title": movie.title,
            "overview": movie.overview,
            "poster_path": movie.poster_path,
            "backdrop_path": movie.backdrop_path,
            "release_date": movie.release_date,
            "vote_average": movie.vote_average,
            "user_rating": user_rating,
        })

    except Exception as e:
        logger.error(f"Movie details error for TMDB ID {tmdb_id}: {str(e)}")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def rate_movie(request, tmdb_id):
    try:
        movie = get_object_or_404(Movie, tmdb_id=tmdb_id)
        rating = request.data.get('rating')

        if not rating or not isinstance(rating, (int, float)) or not (1 <= rating <= 5):
            return Response({"error": "Rating must be between 1 and 5"}, status=status.HTTP_400_BAD_REQUEST)

        user_movie, created = UserMovie.objects.get_or_create(
            user=request.user,
            movie=movie,
            defaults={'rating': rating}
        )

        if not created and user_movie.rating is not None:
            return Response({"error": "You have already rated this movie"}, status=status.HTTP_400_BAD_REQUEST)

        if created or user_movie.rating is None:
            user_movie.rating = rating
            user_movie.save()

        serializer = UserMovieSerializer(user_movie)
        return Response(serializer.data)

    except Exception as e:
        logger.error(f"Rating error for TMDB ID {tmdb_id}: {str(e)}")
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
def advanced_movie_search(request):
    """
    Advanced search endpoint that handles multiple criteria:
    - title (text query)
    - person (actor or crew member name)
    - genre_id
    - company_id (publisher/production company)
    - min_rating (minimum TMDB rating)
    - max_rating (maximum TMDB rating)
    - sort_by (popularity, release_date, vote_average)
    - page (pagination)
    """
    title = request.GET.get('title', '')
    person_query = request.GET.get('person', '')
    genre_id = request.GET.get('genre_id', '')
    company_id = request.GET.get('company_id', '')
    min_rating = request.GET.get('min_rating', '')
    max_rating = request.GET.get('max_rating', '')
    sort_by = request.GET.get('sort_by', 'popularity.desc')
    page = request.GET.get('page', 1)

    tmdb = TMDBService()

    try:
        movies = []
        total_pages = 1
        person_info = None

        if person_query:
            people_response = tmdb.search_people(person_query)
            if people_response.get('results'):
                person = people_response['results'][0]
                person_id = person['id']
                person_info = {
                    'id': person['id'],
                    'name': person['name'],
                    'profile_path': person.get('profile_path')
                }
                movies_response = tmdb._make_request(f'person/{person_id}/movie_credits')
                movies_data = movies_response.get('cast', []) + movies_response.get('crew', [])
                movies_data = list({movie['id']: movie for movie in movies_data}.values())
            else:
                # Fallback to title search if no person found
                results = tmdb.search_movies(person_query)
                movies_data = results.get('results', [])
                total_pages = results.get('total_pages', 1)
                if not movies_data:
                    return Response({
                        'results': [],
                        'page': int(page),
                        'total_pages': 1,
                        'message': f"No persons or movies found for '{person_query}'."
                    }, status=status.HTTP_200_OK)

        elif title:
            results = tmdb.search_movies(title)
            movies_data = results.get('results', [])
            total_pages = results.get('total_pages', 1)

        else:
            params = {
                'page': page,
                'sort_by': sort_by
            }
            if genre_id:
                params['with_genres'] = genre_id
            if company_id:
                params['with_companies'] = company_id
            if min_rating:
                params['vote_average.gte'] = min_rating
            if max_rating:
                params['vote_average.lte'] = max_rating
            data = tmdb._make_request('discover/movie', params)
            movies_data = data.get('results', [])
            total_pages = data.get('total_pages', 1)

        processed_movies = []
        for result in movies_data:
            movie_data = {
                'tmdb_id': result['id'],
                'title': result['title'],
                'overview': result.get('overview', ''),
                'poster_path': result.get('poster_path', ''),
                'backdrop_path': result.get('backdrop_path', ''),
                'release_date': result.get('release_date'),
                'vote_average': result.get('vote_average'),
            }
            movie_data = clean_movie_data(movie_data)
            movie, created = Movie.objects.get_or_create(
                tmdb_id=result['id'], 
                defaults=movie_data
            )
            processed_movies.append(movie)

        serializer = MovieSerializer(processed_movies, many=True, context={'request': request})
        response_data = {
            'results': serializer.data,
            'page': int(page),
            'total_pages': total_pages
        }
        if person_info:
            response_data['person'] = person_info
        return Response(response_data)

    except Exception as e:
        logger.error(f"Advanced search error for query '{person_query or title}': {str(e)}")
        return Response({"error": "An error occurred during search.", "details": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
def search_companies(request):
    query = request.GET.get('query', '')
    if not query:
        return Response({"error": "Search query is required"}, status=status.HTTP_400_BAD_REQUEST)
    
    tmdb = TMDBService()
    try:
        results = tmdb.search_companies(query)
        return Response(results)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
def get_movies_by_company(request, company_id):
    page = request.GET.get('page', 1)
    tmdb = TMDBService()
    try:
        data = tmdb._make_request('discover/movie', {
            'with_companies': company_id,
            'page': page,
            'sort_by': 'popularity.desc'
        })
        
        movies = []
        for result in data.get('results', []):
            movie_data = {
                'tmdb_id': result['id'],
                'title': result['title'],
                'overview': result.get('overview', ''),
                'poster_path': result.get('poster_path', ''),
                'backdrop_path': result.get('backdrop_path', ''),
                'release_date': result.get('release_date'),
                'vote_average': result.get('vote_average'),
            }
            movie_data = clean_movie_data(movie_data)
            movie, created = Movie.objects.get_or_create(tmdb_id=result['id'], defaults=movie_data)
            movies.append(movie)
        
        serializer = MovieSerializer(movies, many=True, context={'request': request})
        return Response({
            'results': serializer.data,
            'page': data.get('page', 1),
            'total_pages': data.get('total_pages', 1)
        })
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)

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
        return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
def get_genres(request):
    try:
        genres = Genre.objects.all()
        serializer = GenreSerializer(genres, many=True)
        return Response(serializer.data)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
        return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
def search_people(request):
    query = request.GET.get('query', '')
    if not query:
        return Response({"error": "Search query is required"}, status=status.HTTP_400_BAD_REQUEST)
    
    page = request.GET.get('page', 1)
    tmdb = TMDBService()
    try:
        results = tmdb.search_people(query, page=page)
        people = []
        for result in results.get('results', []):
            person, created = Person.objects.get_or_create(
                tmdb_id=result['id'],
                defaults={'name': result['name'], 'profile_path': result.get('profile_path', '')}
            )
            people.append(person)
        
        serializer = PersonSerializer(people, many=True)
        return Response({
            'results': serializer.data,
            'page': results.get('page', 1),
            'total_pages': results.get('total_pages', 1)
        })
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_collection(request):
    try:
        user_movies = UserMovie.objects.select_related('movie').filter(user=request.user)
        serializer = UserMovieSerializer(user_movies, many=True)
        return Response(serializer.data)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
            defaults={'rating': request.data.get('rating'), 'notes': request.data.get('notes', '')}
        )

        if not created:
            user_movie.rating = request.data.get('rating', user_movie.rating)
            user_movie.notes = request.data.get('notes', user_movie.notes)
            user_movie.save()

        serializer = UserMovieSerializer(user_movie)
        return Response(serializer.data)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def remove_from_collection(request, tmdb_id):
    try:
        movie = get_object_or_404(Movie, tmdb_id=tmdb_id)
        result = UserMovie.objects.filter(user=request.user, movie=movie).delete()
        if result[0] == 0:
            return Response({"error": "Movie not found in collection"}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def rate_movie(request, tmdb_id):
    try:
        movie = get_object_or_404(Movie, tmdb_id=tmdb_id)
        rating = request.data.get('rating')
        
        if not rating or not isinstance(rating, (int, float)) or not (1 <= rating <= 5):
            return Response({"error": "Rating must be between 1 and 5"}, status=status.HTTP_400_BAD_REQUEST)
        
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
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_recommendations(request):
    try:
        # Fetch user's history/collection
        user_movies = UserMovie.objects.filter(user=request.user).select_related('movie').order_by('-watched_at')
        if not user_movies.exists():
            logger.info(f"No movies in collection/history for user {request.user.email}")
            return Response({"results": []}, status=status.HTTP_200_OK)

        # Build collection details with history context
        user_collection = []
        for user_movie in user_movies:
            movie = user_movie.movie
            try:
                genres = [{'name': g.name} for g in movie.genres.all()]
                cast = [{'person': {'name': c.person.name}} for c in movie.movie_cast.all()[:3]] if movie.movie_cast.exists() else []
                crew = [{'person': {'name': c.person.name}, 'job': c.job} for c in movie.movie_crew.all() if c.job == 'Director'] if movie.movie_crew.exists() else []
                user_collection.append({
                    'movie_details': {
                        'id': movie.id,
                        'tmdb_id': movie.tmdb_id,
                        'title': movie.title,
                        'genres': genres,
                        'cast': cast,
                        'crew': crew,
                        'poster_path': movie.poster_path,
                        'release_date': str(movie.release_date) if movie.release_date else None,
                        'vote_average': movie.vote_average or 0,
                        'user_rating': user_movie.rating,
                        'watched_at': str(user_movie.watched_at),
                    }
                })
            except AttributeError as e:
                logger.warning(f"Error processing movie {movie.tmdb_id}: {str(e)}")
                user_collection.append({
                    'movie_details': {
                        'id': movie.id,
                        'tmdb_id': movie.tmdb_id,
                        'title': movie.title,
                        'genres': [{'name': g.name} for g in movie.genres.all()],
                        'cast': [],
                        'crew': [],
                        'poster_path': movie.poster_path,
                        'release_date': str(movie.release_date) if movie.release_date else None,
                        'vote_average': movie.vote_average or 0,
                        'user_rating': user_movie.rating,
                        'watched_at': str(user_movie.watched_at),
                    }
                })

        # Generate recommendations with OpenAI
        collection_text = "; ".join(
            f"Title: {entry['movie_details']['title']}, Genres: {', '.join(g['name'] for g in entry['movie_details']['genres'])}, "
            f"Actors: {', '.join(c['person']['name'] for c in entry['movie_details']['cast']) or 'Unknown'}, "
            f"Directors: {', '.join(c['person']['name'] for c in entry['movie_details']['crew']) or 'Unknown'}, "
            f"User Rating: {entry['movie_details']['user_rating'] or 'Not Rated'}, "
            f"Watched On: {entry['movie_details']['watched_at']}"
            for entry in user_collection
        )

        prompt = f"""
        Based on the following user movie collection and watch history, recommend 5 movies similar in genre, actors, directors, or theme. 
        Prioritize movies that align with highly rated (4-5 stars) or recently watched entries to reflect the user's preferences:
        {collection_text}

        Provide recommendations in this format:
        1. Title: [Movie Title], Genre: [Genres], Actors: [Main Actors], Directors: [Directors], TMDB_ID: [TMDB ID if known or placeholder]
        2. ...
        """

        openai_api_key = os.getenv("OPENAI_API_KEY", "")
        if not openai_api_key:
            logger.error("OPENAI_API_KEY not set")
            raise ValueError("OpenAI API key is missing")

        client = openai.OpenAI(api_key=openai_api_key)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a movie recommendation expert knowledgeable about TMDB movie data."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=300,
            temperature=0.7,
        )

        recommendations_text = response.choices[0].message.content.strip()
        recommendations = parse_recommendations(recommendations_text)

        # Enrich with TMDB data, ensuring valid tmdb_id
        tmdb = TMDBService()
        enriched_recommendations = []
        processed_titles = set()  # Avoid duplicates

        for rec in recommendations:
            if len(enriched_recommendations) >= 5:
                break
            try:
                if rec['tmdb_id'] and rec['tmdb_id'].isdigit():
                   电影 = tmdb.get_movie_details(int(rec['tmdb_id']))
                if movie.tmdb_id > 0 and movie.title not in processed_titles:
                        enriched_recommendations.append(movie)
                        processed_titles.add(movie.title)
                else:
                    search_results = tmdb.search_movies(rec['title'])
                    if search_results.get('results'):
                        movie = tmdb.get_movie_details(search_results['results'][0]['id'])
                        if movie.tmdb_id > 0 and movie.title not in processed_titles:
                            enriched_recommendations.append(movie)
                            processed_titles.add(movie.title)
            except Exception as e:
                logger.warning(f"Failed to enrich {rec['title']}: {str(e)}")
                continue  # Skip if enrichment fails

        # If less than 5, fetch popular movies as fallback
        if len(enriched_recommendations) < 5:
            popular_movies = tmdb.get_popular_movies().get('results', [])
            for pop_movie in popular_movies:
                if len(enriched_recommendations) >= 5:
                    break
                movie_data = tmdb.get_movie_details(pop_movie['id'])
                if movie_data.title not in processed_titles:
                    enriched_recommendations.append(movie_data)
                    processed_titles.add(movie_data.title)

        serializer = MovieSerializer(enriched_recommendations[:5], many=True, context={'request': request})
        return Response({"results": serializer.data}, status=status.HTTP_200_OK)

    except openai.AuthenticationError as e:
        logger.error(f"OpenAI Authentication Error: {str(e)}")
        return Response({"error": "Invalid OpenAI API key"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as e:
        logger.error(f"Recommendation error for user {request.user.email}: {str(e)}")
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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

@api_view(['GET'])
def get_movie_videos(request, tmdb_id):
    tmdb = TMDBService()
    try:
        data = tmdb._make_request(f"movie/{tmdb_id}/videos")
        return Response(data)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
def get_movies_by_person(request, person_id):
    try:
        person = get_object_or_404(Person, tmdb_id=person_id)
        tmdb = TMDBService()
        results = tmdb.get_movies_by_person(person_id)
        
        movies = []
        for result in results.get('cast', []) + results.get('crew', []):
            if "title" not in result:
                print(f"Skipping entry without title: {result.get('id', 'Unknown ID')}")
                continue
            
            movie_data = {
                'tmdb_id': result['id'],
                'title': result['title'],
                'overview': result.get('overview', ''),
                'poster_path': result.get('poster_path', ''),
                'backdrop_path': result.get('backdrop_path', ''),
                'release_date': result.get('release_date'),
                'vote_average': result.get('vote_average', 0),
            }
            movie_data = clean_movie_data(movie_data)
            
            movie, created = Movie.objects.get_or_create(
                tmdb_id=movie_data['tmdb_id'],
                defaults=movie_data
            )
            if not created and movie.release_date != movie_data['release_date']:
                for key, value in movie_data.items():
                    setattr(movie, key, value)
                movie.save()
            
            if result in results.get('cast', []):
                MovieCast.objects.get_or_create(movie=movie, person=person)
            if result in results.get('crew', []):
                MovieCrew.objects.get_or_create(
                    movie=movie,
                    person=person,
                    job=result.get('job', 'Unknown')
                )
            movies.append(movie)
        
        serializer = MovieSerializer(movies, many=True, context={'request': request})
        return Response(serializer.data)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
def get_genres(request):
    try:
        genres = Genre.objects.all()
        serializer = GenreSerializer(genres, many=True)
        return Response(serializer.data)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
        return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)