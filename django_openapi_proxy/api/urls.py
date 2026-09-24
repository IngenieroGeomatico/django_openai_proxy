from django.urls import path
from .views import ai_proxy, list_models

urlpatterns = [
    path('v1/chat/completions', ai_proxy),
    path('v1/models', list_models),
]