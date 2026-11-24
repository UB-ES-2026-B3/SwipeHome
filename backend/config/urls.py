from properties.proposal_views import proposals, proposal_detail, proposal_resolution, edit_listing, availability
from properties.preference_views import preferences, filter_options
from django.urls import path
from accounts.views import current_user, register
from accounts.profile_views import logout, password, update_profile
from accounts.notification_views import notifications
from config.health import health
from properties.views import create_property
from properties.discovery_views import explore_listings, listing_decision
from properties.match_views import candidates_view, matches_view, seller_match_decision
from properties.views import decide_property


def profile_dispatch(request):
    if request.method in ("PATCH", "PUT"):
        return update_profile(request)
    return current_user(request)


urlpatterns = [
    path("api/propuestas", proposals, name="proposals"),
    path("api/propuestas/<str:proposal_id>", proposal_detail, name="proposal-detail"),
    path("api/propuestas/<str:proposal_id>/<str:action>", proposal_resolution, name="proposal-resolution"),
    path("api/inmuebles/<str:listing_id>/disponibilidad", availability, name="listing-availability"),
    path("api/exploracion/filtros", preferences, name="search-preferences"),
    path("api/inmuebles/opciones-filtro", filter_options, name="filter-options"),
    path("api/notificaciones", notifications, name="notifications"),
    path("api/health", health, name="health"),
    path("api/auth/register", register, name="register"),
    path("api/auth/me", profile_dispatch, name="current-user"),
    path("api/auth/me/password", password, name="change-password"),
    path("api/auth/logout", logout, name="logout"),
    path("api/inmuebles/explorar", explore_listings, name="explore-listings"),
    path("api/inmuebles/<str:listing_id>/decision", listing_decision, name="listing-decision"),
    path("api/inmuebles", create_property, name="create-property"),
    path("api/inmuebles/decidir", decide_property, name="decide-property"),
    path("api/matches", matches_view, name="matches"),
    path("api/candidatos", candidates_view, name="candidates"),
    path("api/matches/<str:match_id>/decision-vendedor", seller_match_decision, name="seller-match-decision"),
    path("api/inmuebles/<str:listing_id>", edit_listing, name="edit-listing"),
]
