import os
import requests
from datetime import datetime
from django.conf import settings
from django.db.models import Avg
from .models import Movie, Genre, Person, MovieCast, MovieCrew, UserMovie

class TMDBService:
    def __init__(self):
        self.api_key = settings.TMDB_API_KEY
        self.base_url = 'https://api.themoviedb.org/3'
        self.image_base_url = 'https://image.tmdb.org/t/p/w500'

    def _make_request(self, endpoint, params=None):
        """Make a request to TMDB API with error handling"""
        if params is None:
            params = {}
        params['api_key'] = self.api_key
        
        url = f"{self.base_url}/{endpoint}"
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def search_movies(self, query, page=1):
        """Search for movies with enhanced metadata"""
        data = self._make_request('search/movie', {
            'query': query,
            'page': page,
            'language': 'en-US'
        })
        
        # Return the raw results for the view to process
        return {
            'results': data['results'],
            'page': data['page'],
            'total_pages': data['total_pages']
        }

    def search_people(self, query, page=1):
        """Search for cast and crew members"""
        data = self._make_request('search/person', {
            'query': query,
            'page': page,
            'language': 'en-US'
        })
        return data

    def get_movies_by_person(self, person_id):
        """Get movies by cast or crew member"""
        data = self._make_request(f'person/{person_id}/combined_credits')
        return data

    def get_movie_details(self, movie_id):
        """Get detailed movie information including cast, crew, and external ratings"""
        try:
            # Get basic movie info
            movie_data = self._make_request(f'movie/{movie_id}')
            
            # Get credits
            credits_data = self._make_request(f'movie/{movie_id}/credits')
            
            # Get external IDs and ratings
            external_data = self._make_request(f'movie/{movie_id}/external_ids')
            
            # Get external ratings if OMDB_API_KEY is configured
            if hasattr(settings, 'OMDB_API_KEY') and external_data.get('imdb_id'):
                try:
                    omdb_data = requests.get(
                        f"http://www.omdbapi.com/",
                        params={
                            'i': external_data['imdb_id'],
                            'apikey': settings.OMDB_API_KEY
                        }
                    ).json()
                    
                    # Add external ratings to movie data
                    movie_data['imdb_rating'] = float(omdb_data.get('imdbRating', 0))
                    # Extract Rotten Tomatoes rating
                    for rating in omdb_data.get('Ratings', []):
                        if rating['Source'] == 'Rotten Tomatoes':
                            movie_data['rotten_tomatoes_rating'] = int(rating['Value'].replace('%', ''))
                            break
                except:
                    pass

            # Combine all data
            movie_data['credits'] = credits_data
            movie_data['external_ids'] = external_data
            
            # Process and save the data
            return self._process_and_save_movie(movie_data, include_credits=True)
            
        except Exception as e:
            raise Exception(f"Error fetching movie details: {str(e)}")

    def get_popular_movies(self, page=1):
        """Get popular movies"""
        data = self._make_request('movie/popular', {'page': page})
        return {
            'results': data['results'],
            'page': data['page'],
            'total_pages': data['total_pages']
        }

    def get_recommendations(self, user):
        """Get personalized movie recommendations"""
        # Get user's watched movies
        user_movies = UserMovie.objects.filter(user=user).select_related('movie')
        
        if not user_movies.exists():
            # If no watch history, return popular movies
            return self.get_popular_movies()
        
        # Get genres the user tends to watch
        favorite_genres = Genre.objects.filter(
            movies__usermovie__user=user
        ).annotate(
            avg_rating=Avg('movies__usermovie__rating')
        ).order_by('-avg_rating')[:3]
        
        # Get top rated movies in those genres
        recommended_movies = []
        for genre in favorite_genres:
            data = self._make_request('discover/movie', {
                'with_genres': genre.tmdb_id,
                'sort_by': 'vote_average.desc',
                'vote_count.gte': 100,
                'page': 1
            })
            recommended_movies.extend(data.get('results', [])[:5])
        
        return {'results': recommended_movies[:10]}

    def _process_and_save_movie(self, movie_data, include_credits=False):
        """Process movie data and save to database"""
        # Save or update genres
        genres = []
        if 'genres' in movie_data:
            for genre_data in movie_data['genres']:
                genre, _ = Genre.objects.get_or_create(
                    tmdb_id=genre_data['id'],
                    defaults={'name': genre_data['name']}
                )
                genres.append(genre)
        
        # Create or update movie
        movie, created = Movie.objects.get_or_create(
            tmdb_id=movie_data['id'],
            defaults={
                'title': movie_data['title'],
                'overview': movie_data.get('overview', ''),
                'poster_path': movie_data.get('poster_path', ''),
                'backdrop_path': movie_data.get('backdrop_path', ''),
                'release_date': self._parse_date(movie_data.get('release_date')),
                'vote_average': movie_data.get('vote_average'),
                'imdb_rating': movie_data.get('imdb_rating'),
                'rotten_tomatoes_rating': movie_data.get('rotten_tomatoes_rating')
            }
        )

        # Update genres
        if genres:
            movie.genres.set(genres)

        # Process credits if included
        if include_credits and 'credits' in movie_data:
            self._process_credits(movie, movie_data['credits'])

        return movie

    def _process_credits(self, movie, credits_data):
        """Process and save cast and crew information"""
        # Process cast
        MovieCast.objects.filter(movie=movie).delete()
        for cast_data in credits_data.get('cast', [])[:10]:  # Limit to top 10 cast members
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

        # Process crew (directors and writers)
        MovieCrew.objects.filter(movie=movie).delete()
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

    def _parse_date(self, date_str):
        """Parse date string to datetime object"""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            return None
    def search_companies(self, query, page=1):
        """Search for production companies."""
        return self._make_request(
            'search/company',
            {'query': query, 'page': page}
        )

    def get_company_details(self, company_id):
        """Get details for a production company."""
        return self._make_request(f'company/{company_id}')

    def get_movies_by_company(self, company_id, page=1):
        """Get movies from a specific production company."""
        return self._make_request(
            'discover/movie',
            {'with_companies': company_id, 'page': page, 'sort_by': 'popularity.desc'}
        )
def get_movie_external_ratings(self, tmdb_id):
    """Fetch external ratings (IMDb, Rotten Tomatoes) from TMDB or OMDB."""
    try:
        # Ensure OMDB API Key is set in settings
        omdb_api_key = getattr(settings, "OMDB_API_KEY", None)
        if not omdb_api_key:
            print("OMDB API Key is missing in settings.")
            return {"imdb": None, "rotten_tomatoes": None}

        # Get external IDs (including IMDb ID) from TMDB
        external_data = self._make_request(f"movie/{tmdb_id}/external_ids")
        imdb_id = external_data.get("imdb_id")

        if not imdb_id:
            print(f"IMDb ID not found for TMDB ID: {tmdb_id}")
            return {"imdb": None, "rotten_tomatoes": None}

        try:
            # Request IMDb and Rotten Tomatoes ratings from OMDB
            response = requests.get(
                "http://www.omdbapi.com/",
                params={"i": imdb_id, "apikey": omdb_api_key},
                timeout=5  # Set a timeout to avoid hanging requests
            )
            response.raise_for_status()  # Raise an error for bad responses
            omdb_data = response.json()

            # Extract IMDb rating
            imdb_rating = float(omdb_data.get("imdbRating", 0)) if "imdbRating" in omdb_data else None

            # Extract Rotten Tomatoes rating
            rotten_tomatoes_rating = None
            for rating in omdb_data.get("Ratings", []):
                if rating["Source"] == "Rotten Tomatoes":
                    rotten_tomatoes_rating = int(rating["Value"].replace("%", ""))
                    break

            return {
                "imdb": imdb_rating,
                "rotten_tomatoes": rotten_tomatoes_rating
            }

        except requests.RequestException as e:
            print(f"OMDB API request failed: {e}")
            return {"imdb": None, "rotten_tomatoes": None}

    except Exception as e:
        print(f"Error fetching external ratings: {e}")
        return {"imdb": None, "rotten_tomatoes": None}