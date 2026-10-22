"""A urlconf with one view that fails, so a real 500 can be asked for. Tests only."""

from django.urls import path


def boom(request):
    raise RuntimeError("a deliberate failure")


urlpatterns = [path("boom/", boom)]
