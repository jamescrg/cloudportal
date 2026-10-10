from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from watson import search as watson

from apps.contacts.models import Contact
from apps.favorites.models import Favorite
from apps.notes.models import Note

# Available search scopes
SEARCH_SCOPES = [
    ("favorites", "Favorites", Favorite),
    ("contacts", "Contacts", Contact),
    ("notes", "Notes", Note),
]

# Synonym mappings for search
SEARCH_SYNONYMS = {
    "contract": ["agreement"],
    "agreement": ["contract"],
}


def expand_search_with_synonyms(query):
    """Expand a search query with synonyms, returning list of search terms."""
    terms = [query]
    query_lower = query.lower()
    for word, synonyms in SEARCH_SYNONYMS.items():
        if word in query_lower:
            for synonym in synonyms:
                terms.append(query.lower().replace(word, synonym))
    return terms


def get_active_scopes(request):
    """Get active search scopes from session, defaulting to all enabled."""
    default_scopes = ["favorites", "contacts", "notes"]
    stored_scopes = request.session.get("search_scopes")

    if stored_scopes is None:
        return default_scopes

    # Add any new default scopes that weren't in the stored session
    for scope in default_scopes:
        if scope not in stored_scopes:
            stored_scopes.append(scope)

    return stored_scopes


@login_required
def index(request):
    """Return the search modal form."""
    active_scopes = get_active_scopes(request)
    context = {
        "page": "search",
        "scopes": SEARCH_SCOPES,
        "active_scopes": active_scopes,
    }
    return render(request, "search/form.html", context)


@login_required
def results(request):
    """Run the search query and return results partial."""
    text = request.POST.get("search_text", "").strip()

    # Get scope filters from POST (checkboxes)
    scope_favorites = request.POST.get("scope_favorites") == "on"
    scope_contacts = request.POST.get("scope_contacts") == "on"
    scope_notes = request.POST.get("scope_notes") == "on"

    # If no scopes selected, enable all
    if not any([scope_favorites, scope_contacts, scope_notes]):
        scope_favorites = scope_contacts = scope_notes = True

    # Save to session for persistence
    active_scopes = []
    if scope_favorites:
        active_scopes.append("favorites")
    if scope_contacts:
        active_scopes.append("contacts")
    if scope_notes:
        active_scopes.append("notes")
    request.session["search_scopes"] = active_scopes

    if not text:
        return render(
            request,
            "search/results.html",
            {
                "favorites": None,
                "contacts": None,
                "notes": None,
                "scopes": SEARCH_SCOPES,
                "active_scopes": active_scopes,
                "text": "",
                "scope_notes": scope_notes,
            },
        )

    user = request.user
    favorites = []
    contacts = []
    notes = []

    # Digits only - use exact matching for phone numbers
    if text.isdigit():
        if scope_contacts:
            contacts = list(
                Contact.objects.filter(user=user)
                .filter(
                    Q(phone1__contains=text)
                    | Q(phone2__contains=text)
                    | Q(phone3__contains=text)
                )
                .order_by("name")
            )
    else:
        # Expand search terms with synonyms
        search_terms = expand_search_with_synonyms(text)

        # Build list of models to search based on active scopes
        models_to_search = []
        if scope_favorites:
            models_to_search.append(Favorite)
        if scope_contacts:
            models_to_search.append(Contact)
        if scope_notes:
            models_to_search.append(Note)

        if models_to_search:
            # Use watson for fuzzy search, deduplicate across synonym terms
            seen_ids = {
                "favorite": set(),
                "contact": set(),
                "note": set(),
            }

            for term in search_terms:
                search_results = watson.search(term, models=tuple(models_to_search))

                for result in search_results:
                    obj = result.object
                    if obj is None:
                        continue
                    # Filter to current user's data
                    if hasattr(obj, "user_id") and obj.user_id != user.id:
                        continue
                    if isinstance(obj, Favorite) and obj.id not in seen_ids["favorite"]:
                        seen_ids["favorite"].add(obj.id)
                        favorites.append(obj)
                    elif isinstance(obj, Contact) and obj.id not in seen_ids["contact"]:
                        seen_ids["contact"].add(obj.id)
                        contacts.append(obj)
                    elif isinstance(obj, Note) and obj.id not in seen_ids["note"]:
                        seen_ids["note"].add(obj.id)
                        notes.append(obj)

    context = {
        "favorites": favorites,
        "contacts": contacts,
        "notes": notes,
        "scopes": SEARCH_SCOPES,
        "active_scopes": active_scopes,
        # the browser searches inside encrypted notes itself, which the
        # index cannot (notes-search.js); it needs the query and the scope
        "text": text,
        "scope_notes": scope_notes,
    }

    return render(request, "search/results.html", context)
