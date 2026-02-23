from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import CustomUser
from apps.folders.folders import (
    get_accessible_folder_ids,
    get_folders_for_page,
    select_folder,
)
from apps.folders.models import Folder


def _redirect_page(page):
    """Redirect to the correct URL for a page, handling namespaced URLs."""
    if page == "notes":
        return redirect("notes:index")
    return redirect(page)


@login_required
def select(request, id, page):
    """Select a folder for display, redirect to index if that folder's page.

    Args:
        id (int): a Folder instance id
        page (int): the page to which the folder belongs

    """
    user = request.user
    setattr(user, page + "_folder", id)
    user.save()
    request.session.pop(f"{page}_all", None)
    return _redirect_page(page)


@login_required
def insert(request, page):
    """Add a new folder.

    Args:
        page(str): the page to which the folder belongs

    Notes:
        Only accepts post requests

    """
    user = request.user
    folder = Folder()
    folder.user = user
    folder.page = page

    folder.name = request.POST.get("name", "").strip()
    if not folder.name:
        return _redirect_page(page)

    folder.save()

    return _redirect_page(page)


@login_required
def update(request, id, page):
    """Edit a folder.

    Args:
        id (str): a Folder instance id
        page (str): the page to which the folder belongs

    Notes:
        Only accepts post requests

    """
    user = request.user

    accessible_ids = get_accessible_folder_ids(user, page)
    try:
        folder = Folder.objects.filter(pk=id, id__in=accessible_ids).get()
    except ObjectDoesNotExist:
        raise Http404("Record not found.")

    if folder.user == user:
        folder.name = request.POST.get("name", folder.name).strip()
        folder.save()

    return _redirect_page(page)


@login_required
def delete(request, id, page):
    """Delete a folder or remove from sharing.

    Args:
        id (int): a Folder instance id
        page (str): the page to which the delete function should redirect

    Notes:
        For owners: deletes the folder
        For shared recipients: removes themselves from the folder's editors

    """
    user = request.user

    accessible_ids = get_accessible_folder_ids(user, page)
    try:
        folder = Folder.objects.filter(pk=id, id__in=accessible_ids).get()
    except ObjectDoesNotExist:
        raise Http404("Record not found.")

    if folder.user == user:
        attr = f"{page}_folder"
        selected_folder_id = getattr(user, attr)

        if selected_folder_id == folder.id:
            setattr(user, attr, 0)
            user.save()

        folder.delete()
    else:
        folder.editors.remove(user)

        attr = f"{page}_folder"
        if getattr(user, attr) == folder.id:
            setattr(user, attr, 0)
            user.save()

    return _redirect_page(page)


@login_required
def home(request, id, page):
    """Add a folder to the home page.

    Args:
        id (int): a Folder instance id
        page (str): the page to which function should redirect

    """

    user = request.user
    home_folder = get_object_or_404(Folder, pk=id)

    if not home_folder.home_column:

        destination_column = 5

        # sequence destination column
        # make sure the folders are sequential and adjacent
        folders = Folder.objects.filter(user=user, home_column=destination_column)
        folders = folders.order_by("home_rank")
        count = 1
        for folder in folders:
            folder.home_rank = count
            folder.save(update_fields=["home_rank"])
            count += 1

        # increment all up by one
        for folder in folders:
            folder.home_rank = folder.home_rank + 1
            folder.save(update_fields=["home_rank"])

        home_folder.home_column = destination_column
        home_folder.home_rank = 1

    else:

        home_folder.home_rank = 0
        home_folder.home_column = 0

    home_folder.save(update_fields=["home_column", "home_rank"])
    return _redirect_page(page)


@login_required
def share(request, id, page):
    """Manage sharing for a folder.

    Args:
        id (int): a Folder instance id
        page (str): the page to which the folder belongs
    """
    try:
        folder = Folder.objects.filter(user=request.user, pk=id).get()
    except ObjectDoesNotExist:
        raise Http404("Record not found.")

    if request.method == "POST":
        user_id = request.POST.get("user_id")
        action = request.POST.get("action")

        if user_id and action:
            try:
                target_user = CustomUser.objects.get(pk=user_id)
                if action == "add":
                    folder.editors.add(target_user)
                elif action == "remove":
                    folder.editors.remove(target_user)
                return JsonResponse({"status": "success"})
            except CustomUser.DoesNotExist:
                return JsonResponse({"status": "error", "message": "User not found"})

    all_users = CustomUser.objects.exclude(pk=request.user.pk)
    current_editors = folder.editors.all()
    available_users = all_users.exclude(
        pk__in=current_editors.values_list("pk", flat=True)
    )

    context = {
        "folder": folder,
        "page": page,
        "current_editors": current_editors,
        "available_users": available_users,
    }

    return render(request, "folders/share.html", context)


# HTMX Views


def _get_folder_context(request, page):
    """Helper to build context for folder list partial."""
    user = request.user
    context = {
        "page": page,
        "folders": get_folders_for_page(request, page),
        "selected_folder": select_folder(request, page),
    }

    # Compute inbox count (items with no folder assigned)
    if page == "tasks":
        from apps.tasks.models import Task

        base_qs = Task.objects.filter(user=user, is_recurring=False, archived=False)
        context["all_count"] = base_qs.count()
        context["inbox_count"] = base_qs.filter(folder__isnull=True).count()
        context["tasks_folder_all"] = request.session.get("tasks_all", False)
    elif page == "favorites":
        from apps.favorites.models import Favorite

        base_qs = Favorite.objects.filter(user=user)
        context["all_count"] = base_qs.count()
        context["inbox_count"] = base_qs.filter(folder__isnull=True).count()
        context["favorites_folder_all"] = request.session.get("favorites_all", False)
    elif page == "notes":
        from apps.notes.models import Note

        base_qs = Note.objects.filter(user=user)
        context["all_count"] = base_qs.count()
        context["inbox_count"] = base_qs.filter(folder__isnull=True).count()
        context["notes_folder_all"] = request.session.get("notes_all", False)
    elif page == "contacts":
        from apps.contacts.models import Contact

        base_qs = Contact.objects.filter(user=user)
        context["all_count"] = base_qs.count()
        context["inbox_count"] = base_qs.filter(folder__isnull=True).count()
        context["contacts_folder_all"] = request.session.get("contacts_all", False)

    return context


@login_required
def folder_tree(request):
    """Return folder list partial for htmx."""
    page = request.GET.get("page", "tasks")
    context = _get_folder_context(request, page)
    return render(request, "folders/tree.html", context)


@login_required
def folder_form(request, page, id=None):
    """Return folder form in modal for htmx, or process form submission."""
    user = request.user
    folder = None
    is_shared = False

    if id:
        accessible_ids = get_accessible_folder_ids(user, page)
        try:
            folder = Folder.objects.filter(pk=id, id__in=accessible_ids).get()
            is_shared = folder.user != user
        except ObjectDoesNotExist:
            raise Http404("Record not found.")

    if request.method == "POST":
        if folder:
            if folder.user == user:
                folder.name = request.POST.get("name", folder.name).strip()
                folder.save()
        else:
            folder = Folder()
            folder.user = user
            folder.page = page
            folder.name = request.POST.get("name", "").strip()

            if not folder.name:
                return HttpResponse(
                    status=204, headers={"HX-Trigger": "foldersChanged"}
                )

            folder.save()

        return HttpResponse(status=204, headers={"HX-Trigger": "foldersChanged"})

    # GET request - display the form
    context = {
        "page": page,
        "folder": folder,
        "is_shared": is_shared,
        "action": f"/folders/form/{id}/{page}" if id else f"/folders/form/{page}",
    }
    return render(request, "folders/form.html", context)


@login_required
def select_htmx(request, id, page):
    """Select folder via htmx and return updated task list."""
    user = request.user
    setattr(user, page + "_folder", id)
    user.save()

    if page == "tasks":
        from apps.tasks.views import _get_task_list_context

        request.session.pop("tasks_all", None)

        context = _get_task_list_context(request)
        return render(request, "tasks/tasks-with-folders-oob.html", context)

    elif page == "favorites":
        from apps.favorites.views import _get_favorites_list_context

        request.session.pop("favorites_all", None)

        context = _get_favorites_list_context(request)
        return render(request, "favorites/favorites-with-folders-oob.html", context)

    elif page == "contacts":
        from apps.contacts.views import _get_contacts_context

        request.session.pop("contacts_all", None)

        context = _get_contacts_context(request)
        return render(request, "contacts/contacts-with-folders-oob.html", context)

    elif page == "notes":
        from apps.notes.views import _get_notes_list_context

        request.session.pop("notes_all", None)

        context = _get_notes_list_context(request)
        return render(request, "notes/notes-with-folders-oob.html", context)

    return _redirect_page(page)


@login_required
def home_htmx(request, id, page):
    """Toggle folder home status via htmx and return updated tree."""
    user = request.user
    home_folder = get_object_or_404(Folder, pk=id)

    if not home_folder.home_column:
        destination_column = 5
        folders = Folder.objects.filter(user=user, home_column=destination_column)
        folders = folders.order_by("home_rank")
        count = 1
        for folder in folders:
            folder.home_rank = count
            folder.save(update_fields=["home_rank"])
            count += 1

        for folder in folders:
            folder.home_rank = folder.home_rank + 1
            folder.save(update_fields=["home_rank"])

        home_folder.home_column = destination_column
        home_folder.home_rank = 1
    else:
        home_folder.home_rank = 0
        home_folder.home_column = 0

    home_folder.save(update_fields=["home_column", "home_rank"])

    context = _get_folder_context(request, page)
    return render(request, "folders/tree.html", context)


@login_required
def delete_htmx(request, id, page):
    """Delete folder via htmx and return updated tree."""
    user = request.user

    accessible_ids = get_accessible_folder_ids(user, page)
    try:
        folder = Folder.objects.filter(pk=id, id__in=accessible_ids).get()
    except ObjectDoesNotExist:
        raise Http404("Record not found.")

    if folder.user == user:
        attr = f"{page}_folder"
        selected_folder_id = getattr(user, attr)

        if selected_folder_id == folder.id:
            setattr(user, attr, 0)
            user.save()

        folder.delete()
    else:
        folder.editors.remove(user)
        attr = f"{page}_folder"
        if getattr(user, attr) == folder.id:
            setattr(user, attr, 0)
            user.save()

    if request.headers.get("HX-Target") != "folder-tree-container":
        return HttpResponse(status=204, headers={"HX-Trigger": "foldersChanged"})

    context = _get_folder_context(request, page)
    return render(request, "folders/tree.html", context)
