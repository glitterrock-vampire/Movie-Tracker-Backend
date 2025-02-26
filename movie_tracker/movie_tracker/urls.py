from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from movies.views import register  # Import the register view

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('movies.urls')),

    path('api/register/', register, name='register'),  # Add registration endpoint
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/', include('movies.urls')),
]