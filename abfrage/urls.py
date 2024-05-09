from django.urls import path

from . import views

app_name = "abfrage"
urlpatterns = [
    path("", views.MenuListView.as_view(), name="start"),
    path("menu/create", views.MenuCreateView.as_view(), name="menu_create"),
    path("menu/<int:pk>", views.MenuDetailView.as_view(), name="menu_detail"),
]
