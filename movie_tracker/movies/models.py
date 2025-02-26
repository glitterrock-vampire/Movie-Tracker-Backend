from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import MinValueValidator, MaxValueValidator

# ✅ Custom User Manager for email authentication
class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)

# ✅ Custom User Model for email authentication
class CustomUser(AbstractUser):
    username = None
    email = models.EmailField('email address', unique=True)
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    def __str__(self):
        return self.email

# ✅ Genre Model
class Genre(models.Model):
    tmdb_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name

# ✅ Person Model (Actors, Directors, etc.)
class Person(models.Model):
    tmdb_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=255)
    profile_path = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return self.name

# ✅ Movie Model
class Movie(models.Model):
    tmdb_id = models.IntegerField(unique=True)
    title = models.CharField(max_length=255)
    overview = models.TextField(blank=True)
    poster_path = models.CharField(max_length=255, blank=True, null=True)
    backdrop_path = models.CharField(max_length=255, blank=True, null=True)  # ✅ Allow NULL
    release_date = models.DateField(null=True, blank=True)
    vote_average = models.FloatField(null=True, blank=True)
    
    # ✅ Relationships
    genres = models.ManyToManyField(Genre, related_name='movies')
    cast = models.ManyToManyField(Person, through='MovieCast', related_name='movies_cast')  # ✅ Fixed
    crew = models.ManyToManyField(Person, through='MovieCrew', related_name='movies_crew')  # ✅ Fixed

    # ✅ Additional Ratings
    imdb_rating = models.FloatField(null=True, blank=True)
    rotten_tomatoes_rating = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

# ✅ MovieCast Model (Actors in Movies)
class MovieCast(models.Model):
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE)
    person = models.ForeignKey(Person, on_delete=models.CASCADE)
    character = models.CharField(max_length=255, blank=True, null=True)
    order = models.IntegerField(null=True, blank=True)  # Changed to allow NULL
    
    class Meta:
        unique_together = ('movie', 'person', 'character')
# ✅ MovieCrew Model (Directors, Writers, etc.)
class MovieCrew(models.Model):
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="movie_crew")  # ✅ Explicit related_name
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="person_crew")  # ✅ Explicit related_name
    department = models.CharField(max_length=100)
    job = models.CharField(max_length=100)

    class Meta:
        unique_together = ['movie', 'person', 'job']

# ✅ UserMovie Model (User's watched & rated movies)
class UserMovie(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='watched_movies')
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='user_movies')
    rating = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    notes = models.TextField(blank=True)
    watched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'movie']
        ordering = ['-watched_at']

    def __str__(self):
        return f"{self.user.email} - {self.movie.title}"
