from django.db.models import Count, Q

from apps.folders.models import Folder


def get_accessible_folder_ids(user, page):
    """Get IDs of all folders a user can access.

    Args:
        user: The user to check access for
        page: The page type (tasks, notes, contacts, favorites)

    Returns:
        set: Set of folder IDs the user can access
    """
    direct_access = Folder.objects.filter(page=page).filter(
        Q(user=user) | Q(editors=user)
    )

    return set(direct_access.values_list("id", flat=True))


def get_folders_for_page(request, page):
    """Get all accessible folders for a specific page.

    Args:
        request: The HTTP request object
        page: The page type (tasks, notes, contacts, favorites)

    Returns:
        QuerySet: Folders the user can access, ordered by name
    """
    user = request.user
    accessible_ids = get_accessible_folder_ids(user, page)

    folders = (
        Folder.objects.filter(id__in=accessible_ids)
        .prefetch_related("editors")
        .order_by("name")
    )

    if page == "tasks":
        count_field = "task"
        count_filters = {
            "task__user": user,
            "task__is_recurring": False,
            "task__archived": False,
        }
    elif page == "favorites":
        count_field = "favorite"
        count_filters = {"favorite__user": user}
    elif page == "notes":
        count_field = "note"
        count_filters = {"note__user": user}
    elif page == "contacts":
        count_field = "contact"
        count_filters = {"contact__user": user}

    folders = folders.annotate(item_count=Count(count_field, filter=Q(**count_filters)))

    return folders


def get_task_folders(request):
    """Get task folders (wrapper for backward compatibility).

    Args:
        request: The HTTP request object

    Returns:
        QuerySet: Task folders the user can access
    """
    return get_folders_for_page(request, "tasks")


def select_folder(request, page):
    """Get the user's currently selected folder for a page.

    Args:
        request: The HTTP request object
        page: The page type (tasks, notes, contacts, favorites)

    Returns:
        Folder or None: The selected folder, or None if not set
    """
    user = request.user
    folder_id = getattr(user, page + "_folder")

    if folder_id and folder_id > 0:
        try:
            accessible_ids = get_accessible_folder_ids(user, page)
            folder = Folder.objects.filter(pk=folder_id, id__in=accessible_ids).first()

            if not folder:
                setattr(user, page + "_folder", 0)
                user.save()
                folder = None
        except Exception:
            setattr(user, page + "_folder", 0)
            user.save()
            folder = None
    else:
        folder = None

    return folder


def toggle_home(folder):
    """Put a folder on the home page, at the end of its owner's sequence,
    or take it off. The home page shows a folder with home_column set,
    in home_rank order."""
    if folder.home_column:
        folder.home_column = 0
        folder.home_rank = 0
    else:
        last = (
            Folder.objects.filter(user=folder.user, page=folder.page, home_column__gt=0)
            .exclude(pk=folder.pk)
            .order_by("-home_rank")
            .first()
        )
        folder.home_column = 1
        folder.home_rank = (last.home_rank or 0) + 1 if last else 1
    folder.save(update_fields=["home_column", "home_rank"])
