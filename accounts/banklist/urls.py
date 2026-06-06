from django.urls import path
from .views import search_banks

urlpatterns = [
    path('banks/search/', search_banks),
]