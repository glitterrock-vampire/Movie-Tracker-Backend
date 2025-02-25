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

# Configure OpenAI API key (store securely in environment variables or settings.py)
# openai.api_key = os.environ.get("OPENAI_API_KEY", getattr(settings, "OPENAI_API_KEY", ""))
# import os
from dotenv import load_dotenv

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

# Movie Details and Metadata Views
@api_view(['GET'])
def get_movie_details(request, tmdb_id):
    tmdb = TMDBService()
    try:
        try:
            movie = Movie.objects.get(tmdb_id=tmdb_id)
            needs_update = True
        except Movie.DoesNotExist:
            movie_data = tmdb._make_request(f'movie/{tmdb_id}')
            credits_data = tmdb._make_request(f'movie/{tmdb_id}/credits')
            
            movie = Movie.objects.create(
                tmdb_id=tmdb_id,
                title=movie_data['title'],
                overview=movie_data.get('overview', ''),
                poster_path=movie_data.get('poster_path', ''),
                backdrop_path=movie_data.get('backdrop_path', ''),
                release_date=movie_data.get('release_date'),
                vote_average=movie_data.get('vote_average')
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
                        defaults={'name': crew_data['name'], 'profile_path': crew_data.get('profile_path', '')}
                    )
                    MovieCrew.objects.create(movie=movie, person=person, job=crew_data['job'], department=crew_data['department'])
            needs_update = False
        
        if needs_update:
            movie_data = tmdb._make_request(f'movie/{tmdb_id}')
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
                    defaults={'name': cast_data['name'], 'profile_path': cast_data.get('profile_path', '')}
                )
                MovieCast.objects.create(movie=movie, person=person, character=cast_data['character'], order=cast_data['order'])
            
            for crew_data in credits_data.get('crew', []):
                if crew_data['job'] in ['Director', 'Screenplay', 'Writer']:
                    person, _ = Person.objects.get_or_create(
                        tmdb_id=crew_data['id'],
                        defaults={'name': crew_data['name'], 'profile_path': crew_data.get('profile_path', '')}
                    )
                    MovieCrew.objects.create(movie=movie, person=person, job=crew_data['job'], department=crew_data['department'])
        
        serializer = MovieSerializer(movie, context={'request': request})
        return Response(serializer.data)
    
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
        # Fetch the user's collection
        user_movies = UserMovie.objects.filter(user=request.user).select_related('movie')
        user_collection = [
            {
                'movie_details': {
                    'id': movie.movie.id,
                    'tmdb_id': movie.movie.tmdb_id,
                    'title': movie.movie.title,
                    'genres': [{'name': g.name} for g in movie.movie.genres.all()],
                    'cast': [{'person': {'name': c.person.name}} for c in movie.movie.moviecast_set.all()[:3]],  # ✅ FIXED
                    'crew': [{'person': {'name': c.person.name}, 'job': c.job} for c in movie.movie.moviecrew_set.all() if c.job == 'Director'],
                    'poster_path': movie.movie.poster_path,
                    'release_date': str(movie.movie.release_date) if movie.movie.release_date else None,
                    'vote_average': movie.movie.vote_average,
                }
            }
            for movie in user_movies
        ]

        if not user_collection:
            return Response({"results": []}, status=status.HTTP_200_OK)

        # Use GPT to generate recommendations based on the collection
        collection_details = [
            f"Title: {entry['movie_details']['title']}, Genres: {', '.join(g['name'] for g in entry['movie_details']['genres'])}, "
            f"Actors: {', '.join(c['person']['name'] for c in entry['movie_details']['cast'])}, "
            f"Directors: {', '.join(c['person']['name'] for c in entry['movie_details']['crew'])}"
            for entry in user_collection
        ]
        collection_text = "; ".join(collection_details)

        prompt = f"""
        Based on the following user movie collection, recommend 5 movies similar in genre, actors, directors, or theme:
        {collection_text}

        Provide recommendations in this format:
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

        recommendations_text = response.choices[0].message.content.strip()
        recommendations = parse_recommendations(recommendations_text)

        # Enrich recommendations with TMDB data
        tmdb = TMDBService()
        enriched_recommendations = []
        for rec in recommendations:
            try:
                if rec['tmdb_id']:
                    movie_data = tmdb.get_movie_details(rec['tmdb_id'])
                    movie, created = Movie.objects.get_or_create(
                        tmdb_id=rec['tmdb_id'],
                        defaults={
                            'title': movie_data['title'],
                            'overview': movie_data.get('overview', ''),
                            'poster_path': movie_data.get('poster_path', ''),
                            'backdrop_path': movie_data.get('backdrop_path', ''),
                            'release_date': movie_data.get('release_date'),
                            'vote_average': movie_data.get('vote_average', 0),
                        }
                    )
                    rec.update({
                        'poster_path': movie_data.get('poster_path', ''),
                        'release_date': movie_data.get('release_date', ''),
                        'vote_average': movie_data.get('vote_average', 0),
                        'id': movie.id,
                    })
                enriched_recommendations.append(rec)
            except Exception as e:
                print(f"Failed to fetch TMDB data for {rec['title']}: {e}")
                rec.update({
                    'poster_path': '',
                    'release_date': '',
                    'vote_average': 0,
                    'id': None,
                })
                enriched_recommendations.append(rec)

        serializer = MovieSerializer(
            [Movie(**{k: v for k, v in rec.items() if k in ['id', 'tmdb_id', 'title', 'overview', 'poster_path', 'backdrop_path', 'release_date', 'vote_average']}) for rec in enriched_recommendations],
            many=True,
            context={'request': request}
        )
        return Response({
            'results': serializer.data
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )



def parse_recommendations(recommendations_text):
    """Simple parsing to extract recommendations from GPT response."""
    lines = recommendations_text.split("\n")
    recommendations = []
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