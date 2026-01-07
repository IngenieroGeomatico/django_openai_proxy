from django.urls import path
from .views import ai_proxy

urlpatterns = [
    path('v1/chat/completions', ai_proxy),
]