import json
from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.favorites import site_icons
from apps.favorites.models import Favorite
from apps.folders.folders import get_accessible_folder_ids, get_folders_for_page
from apps.folders.models import Folder
from apps.home import agenda
from apps.home.models import HomeNotice
from apps.home.toggle import show_section
from apps.quotes import quotes as quotes_of_the_day
from apps.tasks.models import Task
from apps.tasks.views import complete_task
from apps.weather.service import report_for


def fetch_current_weather(user):
    """What the home page's indicator shows: the current temperature and
    conditions, from the weather page's cached report."""
    try:
        report = report_for(user)
    except Exception:
        return None
    if not report:
        return None
    current = report["current"]
    return {
        "temp": current["temp"],
        "icon": current["icon"],
        "owm_icon": current["owm_icon"],
        "description": current["description"],
    }


def get_search_context(user):
    """Get search engine context for a user"""
    engines = [
        {"id": "google", "name": "Google", "url": "google.com/search"},
        {"id": "duckduckgo", "name": "DuckDuckGo", "url": "duckduckgo.com/"},
        {"id": "wikipedia", "name": "Wikipedia", "url": "en.wikipedia.org/w/index.php"},
        {"id": "bing", "name": "Bing", "url": "bing.com/"},
    ]

    search_engine = "google"
    for engine in engines:
        if engine["id"] == user.search_engine:
            search_engine = engine

    return {
        "engines": engines,
        "search_engine": search_engine,
    }


@login_required
def index(request):
    """Display the home page.

    Notes:
        Displays upcoming events, current tasks, and priority favorites

    """

    user = request.user

    # NOTIFICATIONS
    # ----------------

    # the cards notifications sent to the home page, until each is closed
    notices = HomeNotice.objects.open_for(user)

    # EVENTS
    # ----------------

    # the next week of the user's own calendar, when the section is shown
    show_events = show_section(user, "events")
    week = agenda.week_days(request) if show_events else []
    # the panel is left out of a week with nothing on it
    week_count = sum(day.count for day in week)

    # QUOTES
    # ----------------

    # every quote marked always, then the day's own, when the section is shown
    show_quotes = show_section(user, "quotes")
    quotes = quotes_of_the_day.todays(user) if show_quotes else []

    # TASKS
    # ----------------

    # check whether tasks are shown or hidden
    show_tasks = show_section(user, "tasks")

    # if tasks are shown, check for task_folders
    # Get all task folders that user has access to (owned or shared)
    all_task_folders = get_folders_for_page(request, "tasks")
    task_folders = all_task_folders.filter(home_column__gt=0)
    if task_folders:

        # eliminate folders with no tasks
        for folder in task_folders:
            tasks = Task.objects.filter(
                folder_id=folder.id, is_recurring=False, archived=False
            ).exclude(status=1)
            if not tasks:
                task_folders = task_folders.exclude(id=folder.id)

        # attatch tasks to folders with tasks
        for folder in task_folders:
            tasks = Task.objects.filter(
                folder_id=folder.id, is_recurring=False, archived=False
            ).exclude(status=1)
            tasks = tasks.order_by("status", "priority", "title")
            folder.tasks = tasks

    # check whether there are some tasks in any of the folders
    # if so, flag as true
    # the purpose of this flag is to show the tasks area
    # only if there are at least some unchecked tasks to display
    some_tasks = False
    if task_folders:
        for folder in task_folders:
            if folder.tasks:
                some_tasks = True

    # DUE TASKS
    # ----------------

    # overdue tasks and those due in the next few days, grouped by day
    show_due_tasks = show_section(user, "due_tasks")
    due_task_groups = agenda.due_task_groups(user) if show_due_tasks else []

    # WEATHER
    # ----------------
    show_weather = bool(user.home_weather)
    weather = fetch_current_weather(user) if show_weather else None

    # SEARCH
    # ----------------
    search_context = get_search_context(user)

    # FAVORITES
    # ----------------

    # the folders on the home page, by column, each with the favorites
    # chosen for it in their order
    columns = home_columns(request)

    context = {
        "page": "home",
        "origin": "home",
        "notices": notices,
        "show_tasks": show_tasks,
        "task_folders": task_folders,
        "some_tasks": some_tasks,
        "show_due_tasks": show_due_tasks,
        "due_task_groups": due_task_groups,
        "week": week,
        "week_count": week_count,
        "show_events": show_events,
        "show_quotes": show_quotes,
        "quotes": quotes,
        "columns": columns,
        "show_weather": show_weather,
        "weather": weather,
    }

    # Add search context
    context.update(search_context)

    return render(request, "home/content.html", context)


@login_required
@require_POST
def notice_dismiss(request, id):
    """Close a notification card. The card is swapped away in place, so
    nothing comes back."""
    notice = get_object_or_404(HomeNotice, pk=id, user=request.user)
    notice.dismiss()
    return HttpResponse("")


@login_required
@require_POST
def notice_done(request, id):
    """A task card's Done: marks the task done the way the user has chosen
    and closes the card."""
    notice = get_object_or_404(HomeNotice, pk=id, user=request.user, kind="task")
    if notice.task and notice.task.status != 1:
        complete_task(notice.task, request.user)
    # a deleted task takes its card with it; one kept or archived leaves
    # the card to be closed here
    if HomeNotice.objects.filter(pk=id).exists():
        notice.dismiss()
    return HttpResponse("")


@login_required
def toggle(request, section):
    """Toggle on or off various sections of the home page.

    Args:
        section (str): the section to toggle

    Notes:
        Page sections appear in the morning, this turns them off.

        The hidden state is stored per-user on the CustomUser model
        (home_{section}_hidden field) and syncs across all devices.

    """

    user = request.user

    attrib = f"home_{section}_hidden"
    if getattr(user, attrib):
        setattr(user, attrib, None)
    else:
        setattr(user, attrib, date.today())

    user.save()

    return redirect("/home/")


def with_favorites(folders):
    """Attach to each folder the favorites chosen for the home page, in
    rank order, each with the host of its url and whether its icon is on
    hand."""
    shown = list(
        Favorite.objects.filter(folder__in=folders, home_rank__gt=0).order_by(
            "home_rank", "id"
        )
    )
    site_icons.with_hosts(shown)
    by_folder = {}
    for favorite in shown:
        by_folder.setdefault(favorite.folder_id, []).append(favorite)
    for folder in folders:
        folder.favorites = by_folder.get(folder.id, [])
    return folders


# The most columns the home page's folders can be arranged in
COLUMNS = 5


def home_columns(request):
    """The favorites folders on the home page as columns, up to five:
    a list of lists, the first column to the last one in use, each in
    rank order, each folder with its favorites (see with_favorites)."""
    folders = with_favorites(
        list(
            get_folders_for_page(request, "favorites")
            .filter(home_column__gt=0)
            .order_by("home_column", "home_rank", "id")
        )
    )
    if not folders:
        return []
    columns = [[] for _ in range(min(folders[-1].home_column, COLUMNS))]
    for folder in folders:
        columns[min(folder.home_column, COLUMNS) - 1].append(folder)
    return columns


def _ids(request, field):
    """The list of ids posted as JSON under field, or None if it isn't one."""
    try:
        ids = json.loads(request.POST.get(field, ""))
        return [int(i) for i in ids]
    except (ValueError, TypeError):
        return None


def _columns(request):
    """The columns posted as JSON under 'columns', a list of lists of ids,
    or None if that isn't what was posted."""
    try:
        columns = json.loads(request.POST.get("columns", ""))
        if not isinstance(columns, list) or not all(
            isinstance(column, list) for column in columns
        ):
            return None
        return [[int(i) for i in column] for column in columns]
    except (ValueError, TypeError):
        return None


@login_required
@require_POST
def layout(request):
    """Set the home page's columns: one list of folder ids per column,
    first column to last, each first to last.

    The page posts the whole board after a folder is dragged somewhere
    else, up to five columns. Only the user's own folders can be placed; a
    folder shared with the user stays where its owner put it, and is left
    out of the post, so a column may be posted empty.
    """
    columns = _columns(request)
    if columns is None or len(columns) > COLUMNS:
        return JsonResponse(
            {"ok": False, "error": f"columns must be up to {COLUMNS} lists"},
            status=400,
        )
    ids = [folder_id for column in columns for folder_id in column]
    own = Folder.objects.filter(user=request.user, page="favorites", pk__in=ids)
    if len(set(ids)) != len(ids) or set(own.values_list("id", flat=True)) != set(ids):
        return JsonResponse({"ok": False, "error": "not your folder"}, status=403)
    for column, members in enumerate(columns, start=1):
        for rank, folder_id in enumerate(members, start=1):
            Folder.objects.filter(pk=folder_id).update(
                home_column=column, home_rank=rank
            )
    return JsonResponse({"ok": True})


@login_required
@require_POST
def folder_favorites(request, id):
    """Set a folder's favorites on the home page: the posted ids, in the
    posted order.

    The page posts the whole destination list after a favorite is dropped
    into it. A favorite dropped in from another folder moves into this
    folder, on the favorites page as well as here: the home page shows the
    folders as they are, so the drop is a move, not a copy.
    """
    if id not in get_accessible_folder_ids(request.user, "favorites"):
        return JsonResponse({"ok": False, "error": "no such folder"}, status=404)
    ids = _ids(request, "favorites")
    if ids is None:
        return JsonResponse(
            {"ok": False, "error": "favorites must be a list"}, status=400
        )
    own = Favorite.objects.filter(user=request.user, pk__in=ids)
    if set(own.values_list("id", flat=True)) != set(ids):
        return JsonResponse({"ok": False, "error": "not your favorite"}, status=403)
    for rank, favorite_id in enumerate(ids, start=1):
        Favorite.objects.filter(pk=favorite_id).update(folder_id=id, home_rank=rank)
    return JsonResponse({"ok": True})


@login_required
def choose(request, id):
    """A folder's chooser on the home page: all its favorites, with those
    shown ticked, for the menu under the folder's plus."""
    if id not in get_accessible_folder_ids(request.user, "favorites"):
        raise Http404("No such folder.")
    folder = get_object_or_404(Folder, pk=id)
    favorites = site_icons.with_hosts(
        list(Favorite.objects.filter(folder=folder).order_by("name"))
    )
    return render(
        request, "home/choose.html", {"folder": folder, "favorites": favorites}
    )


@login_required
@require_POST
def favorite_shown(request, id):
    """Show a favorite on the home page, or take it off: a post with
    'shown' set shows it, at the end of its folder's list, and one without
    hides it. Returns the folder's body for the page to swap in."""
    favorite = get_object_or_404(Favorite, pk=id)
    if favorite.folder_id not in get_accessible_folder_ids(request.user, "favorites"):
        raise Http404("No such favorite.")
    if request.POST.get("shown"):
        if not favorite.home_rank:
            favorite.home_rank = favorite.next_home_rank()
    else:
        favorite.home_rank = 0
    favorite.save(update_fields=["home_rank"])
    folder = with_favorites([favorite.folder])[0]
    return render(request, "home/folder_body.html", {"folder": folder})


@login_required
def save_location(request):
    """Save browser geolocation coordinates."""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Only POST method allowed"})

    try:
        lat = float(request.POST.get("lat"))
        lon = float(request.POST.get("lon"))
    except (ValueError, TypeError):
        return JsonResponse({"success": False, "error": "Invalid coordinates"})

    user = request.user
    user.weather_lat = lat
    user.weather_lon = lon
    # the place is looked up again for the new location when it is next shown
    user.weather_place = ""
    user.save(update_fields=["weather_lat", "weather_lon", "weather_place"])

    return JsonResponse({"success": True})
