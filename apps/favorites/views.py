import json
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.favorites.forms import FavoriteExtensionForm, FavoriteForm
from apps.favorites.models import Favorite
from apps.folders.folders import get_folders_for_page, select_folder
from apps.folders.models import Folder
from apps.management.pagination import CustomPaginator

FAVORITES_ALLOWED_ORDER_FIELDS = {"name", "created_at", "updated_at"}


def _get_favorites_list_context(request):
    """Helper to build context for favorites list partial."""
    user = request.user
    selected_folder = select_folder(request, "favorites")
    favorites_folder_all = request.session.get("favorites_all", False)

    if favorites_folder_all:
        favorites = Favorite.objects.filter(user=user)
    elif selected_folder:
        favorites = Favorite.objects.filter(user=user, folder_id=selected_folder.id)
    else:
        favorites = Favorite.objects.filter(user=user, folder_id__isnull=True)

    keyword = request.session.get("favorites_keyword", "")
    if keyword:
        favorites = favorites.filter(name__icontains=keyword)

    order_by = request.session.get("favorites_order", "name")
    bare_field = order_by.lstrip("-")
    if bare_field not in FAVORITES_ALLOWED_ORDER_FIELDS:
        order_by = "name"
        bare_field = "name"
    favorites = favorites.order_by(order_by)

    session_key = "favorites_page"
    trigger_key = "favoritesChanged"
    pagination = CustomPaginator(favorites, 20, request, session_key)

    base_count_qs = Favorite.objects.filter(user=user)

    return {
        "page": "favorites",
        "folders": get_folders_for_page(request, "favorites"),
        "selected_folder": selected_folder,
        "favorites_folder_all": favorites_folder_all,
        "favorites": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": session_key,
        "trigger_key": trigger_key,
        "current_order": bare_field,
        "keyword": keyword,
        "all_count": base_count_qs.count(),
        "inbox_count": base_count_qs.filter(folder__isnull=True).count(),
    }


def cors_headers(view_func):
    """Decorator to add CORS headers for browser extension API endpoints."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.method == "OPTIONS":
            response = JsonResponse({})
        else:
            response = view_func(request, *args, **kwargs)

        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

    return wrapper


@login_required
def index(request):
    """Display a list of folders and favorites

    Notes:
        Always displays folders.
        If a folder is selected, displays the favorites for a folder.

    """

    context = {"edit": False} | _get_favorites_list_context(request)
    return render(request, "favorites/content.html", context)


@login_required
def add(request):
    """Add a new favorite

    Notes:
        GET: Display new favorite form
        POST: Add favorite to database

    """
    user = request.user
    folders = get_folders_for_page(request, "favorites")

    selected_folder = select_folder(request, "favorites")

    if request.method == "POST":
        form = FavoriteForm(request.POST)

        if form.is_valid():
            favorite = form.save(commit=False)
            favorite.user = user
            favorite.save()
            return redirect("favorites")

    else:
        if selected_folder:
            form = FavoriteForm(initial={"folder": selected_folder.id})
        else:
            form = FavoriteForm()

    form.fields["folder"].queryset = get_folders_for_page(request, "favorites")

    context = {
        "page": "favorites",
        "add": True,
        "action": "/favorites/add",
        "folders": folders,
        "selected_folder": selected_folder,
        "form": form,
    }

    return render(request, "favorites/content.html", context)


@login_required
def edit(request, id):
    """Edit a favorite
    Args:
        id (int): a Favorite instance id

    GET: Display favorite form
    POST: Update favorite in database

    """
    user = request.user
    folders = get_folders_for_page(request, "favorites")

    selected_folder = select_folder(request, "favorites")

    favorite = get_object_or_404(Favorite, pk=id)

    if request.method == "POST":
        try:
            favorite = get_object_or_404(Favorite, pk=id)
        except ObjectDoesNotExist:
            raise Http404("Record note found.")

        form = FavoriteForm(request.POST, instance=favorite)

        if form.is_valid():
            favorite = form.save(commit=False)
            favorite.user = user
            favorite.save()
            return redirect("favorites")

    else:
        if selected_folder:
            form = FavoriteForm(
                instance=favorite, initial={"folder": selected_folder.id}
            )
        else:
            form = FavoriteForm(instance=favorite)

    form.fields["folder"].queryset = get_folders_for_page(request, "favorites")

    context = {
        "page": "favorites",
        "edit": True,
        "add": False,
        "action": f"/favorites/{id}/edit",
        "folders": folders,
        "selected_folder": selected_folder,
        "form": form,
    }

    return render(request, "favorites/content.html", context)


@login_required
def delete(request, id):
    """
    Delete a favorite

    Args:
        id (int): a Favorite instance id

    """
    try:
        favorite = Favorite.objects.filter(user=request.user, pk=id).get()
    except ObjectDoesNotExist:
        raise Http404("Record not found.")
    favorite.delete()
    return redirect("favorites")


@login_required
def home(request, id):
    """Add or remove a favorite from home

    Args:
        id (int): a Favorite instance id

    """
    favorite = get_object_or_404(Favorite, pk=id)
    if favorite.home_rank:
        favorite.home_rank = 0
    else:
        favorite.home_rank = 1
    favorite.save()
    return redirect("favorites")


# -----------------------------------------------------------------------------
# HTMX Views
# -----------------------------------------------------------------------------


@login_required
def favorites_all(request):
    """Select 'All' folder view and return updated favorites with folders OOB."""
    request.session["favorites_all"] = True
    request.user.favorites_folder = 0
    request.user.save()
    context = _get_favorites_list_context(request)
    return render(request, "favorites/favorites-with-folders-oob.html", context)


@login_required
def favorites_list(request):
    """Return favorites card partial for htmx."""
    context = _get_favorites_list_context(request)
    return render(request, "favorites/favorites.html", context)


@login_required
def favorites_filter_keyword(request):
    """Filter favorites by keyword."""
    keyword = request.GET.get("keyword", "").strip()

    if keyword:
        request.session["favorites_keyword"] = keyword
    else:
        request.session.pop("favorites_keyword", None)

    request.session["favorites_page"] = 1
    request.session.modified = True

    context = _get_favorites_list_context(request)
    return render(request, "favorites/list.html", context)


@login_required
def favorites_order_by(request, order):
    """Toggle sort order for favorites list."""
    current = request.session.get("favorites_order", "name")
    if current == order:
        order = f"-{order}" if not current.startswith("-") else order
    request.session["favorites_order"] = order
    request.session["favorites_page"] = 1
    request.session.modified = True
    return redirect("favorites-list")


@login_required
def favorites_form(request, id=None):
    """Return favorite form in modal, or process form submission."""
    user = request.user

    if id:
        favorite = get_object_or_404(Favorite, pk=id)
        edit = True
    else:
        favorite = None
        edit = False

    if request.method == "POST":
        if edit:
            form = FavoriteForm(
                request.POST, instance=favorite, use_required_attribute=False
            )
        else:
            form = FavoriteForm(request.POST, use_required_attribute=False)

        form.fields["folder"].queryset = get_folders_for_page(request, "favorites")

        if form.is_valid():
            favorite = form.save(commit=False)
            favorite.user = user
            favorite.save()

            # Switch to the saved favorite's folder
            user.favorites_folder = favorite.folder_id or 0
            user.save()

            return HttpResponse(
                status=204,
                headers={
                    "HX-Trigger": json.dumps(
                        {"favoritesChanged": "", "foldersChanged": ""}
                    )
                },
            )

        # Form validation failed - re-render form with errors

    else:
        # GET request - display the form
        if edit:
            form = FavoriteForm(instance=favorite, use_required_attribute=False)
        else:
            form = FavoriteForm(use_required_attribute=False)

    context = {
        "page": "favorites",
        "edit": edit,
        "action": f"/favorites/{id}/form" if edit else "/favorites/form",
        "favorite": favorite,
        "form": form,
        "folders": get_folders_for_page(request, "favorites"),
        "selected_folder_id": user.favorites_folder,
    }
    return render(request, "favorites/modal-form.html", context)


@login_required
def delete_htmx(request, id):
    """Delete favorite via htmx and close modal."""
    favorite = get_object_or_404(Favorite, pk=id, user=request.user)
    favorite.delete()
    return HttpResponse(status=204, headers={"HX-Trigger": "favoritesChanged"})


@login_required
@require_POST
def bulk_delete(request):
    """Bulk delete favorites."""
    data = json.loads(request.body)
    ids = data.get("favorite_ids", [])
    Favorite.objects.filter(user=request.user, id__in=ids).delete()
    return HttpResponse(status=204, headers={"HX-Trigger": "favoritesChanged"})


@login_required
@require_POST
def bulk_move_folder(request):
    """Bulk move favorites to a folder."""
    data = json.loads(request.body)
    ids = data.get("favorite_ids", [])
    folder_id = data.get("folder_id")
    Favorite.objects.filter(user=request.user, id__in=ids).update(folder_id=folder_id)
    return HttpResponse(status=204, headers={"HX-Trigger": "favoritesChanged"})


@login_required
def home_htmx(request, id):
    """Toggle favorite home status via htmx and return updated list."""
    favorite = get_object_or_404(Favorite, pk=id)
    if favorite.home_rank:
        favorite.home_rank = 0
    else:
        favorite.home_rank = 1
    favorite.save()

    context = _get_favorites_list_context(request)
    return render(request, "favorites/list.html", context)


# -----------------------------------------------------------------------------
# Browser Extension API
# -----------------------------------------------------------------------------


@csrf_exempt
@cors_headers
def api_add(request):
    """API endpoint for browser extension to add favorites.

    Expects JSON body with: name, url, folder_id (optional), auth_token
    """
    if request.method == "OPTIONS":
        return JsonResponse({})

    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # Authenticate via token
    auth_token = data.get("auth_token")
    if not auth_token:
        return JsonResponse({"error": "Authentication required"}, status=401)

    from accounts.models import CustomUser

    try:
        user = CustomUser.objects.get(extension_token=auth_token)
    except CustomUser.DoesNotExist:
        return JsonResponse({"error": "Invalid authentication token"}, status=401)

    # Create the favorite
    name = data.get("name", "").strip()
    url = data.get("url", "").strip()
    folder_id = data.get("folder_id")

    if not name or not url:
        return JsonResponse({"error": "Name and URL are required"}, status=400)

    favorite = Favorite(user=user, name=name, url=url)

    if folder_id:
        try:
            folder = Folder.objects.get(pk=folder_id, user=user)
            favorite.folder = folder
        except Folder.DoesNotExist:
            pass

    favorite.save()

    return JsonResponse({"success": True, "id": favorite.id})


@csrf_exempt
@cors_headers
def api_folders(request):
    """API endpoint to get user's folders for the browser extension."""
    if request.method == "OPTIONS":
        return JsonResponse({})

    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    auth_token = data.get("auth_token")
    if not auth_token:
        return JsonResponse({"error": "Authentication required"}, status=401)

    from accounts.models import CustomUser

    try:
        user = CustomUser.objects.get(extension_token=auth_token)
    except CustomUser.DoesNotExist:
        return JsonResponse({"error": "Invalid authentication token"}, status=401)

    folders = Folder.objects.filter(user=user, page="favorites").order_by("name")
    folder_list = [{"id": f.id, "name": f.name} for f in folders]

    return JsonResponse({"folders": folder_list})


@login_required
def extension_add(request):
    """Web form for adding favorites via browser extension popup.

    This provides a logged-in web form that the extension can open in a popup.
    """
    user = request.user

    if request.method == "POST":
        form = FavoriteExtensionForm(request.POST)
        form.fields["folder"].queryset = get_folders_for_page(request, "favorites")

        if form.is_valid():
            favorite = form.save(commit=False)
            favorite.user = user
            favorite.save()

            user.favorites_folder = favorite.folder_id or 0
            user.save()

            return render(
                request, "favorites/extension_success.html", {"favorite": favorite}
            )
    else:
        # Pre-fill from query params (extension passes these)
        initial = {}
        if request.GET.get("url"):
            initial["url"] = request.GET.get("url")
        if request.GET.get("name"):
            initial["name"] = request.GET.get("name")

        selected_folder = select_folder(request, "favorites")
        if selected_folder:
            initial["folder"] = selected_folder.id

        form = FavoriteExtensionForm(initial=initial)
        form.fields["folder"].queryset = get_folders_for_page(request, "favorites")

    context = {
        "form": form,
    }

    return render(request, "favorites/extension_form.html", context)
