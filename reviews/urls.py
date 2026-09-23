from django.urls import path

from . import views


urlpatterns = [
    path("", views.home, name="home"),
    path("bundles/upload/", views.upload_bundle, name="upload-bundle"),
    path("bundles/<uuid:bundle_id>/", views.bundle_detail, name="bundle"),
    path("bundles/<uuid:bundle_id>/cases/<int:case_id>/", views.review_case, name="review-case"),
    path("bundles/<uuid:bundle_id>/export/", views.export_bundle, name="export-bundle"),
    path("bundles/<uuid:bundle_id>/delete/", views.delete_bundle, name="delete-bundle"),
]
