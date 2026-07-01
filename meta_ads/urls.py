#meta_ads/urls.py
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CampanaMetaViewSet

router = DefaultRouter()
router.register(r"campanas-meta", CampanaMetaViewSet, basename="campanas-meta")

urlpatterns = [
    path("api/", include(router.urls)),
]