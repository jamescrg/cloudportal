from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import CustomUser
from apps.folders.folders import get_folders_for_page, get_task_folders, select_folder
from apps.folders.models import Folder
from apps.management.pagination import CustomPaginator
from apps.tasks.filter import TasksFilter
from apps.tasks.forms import TaskForm
from apps.tasks.models import Task


def _get_task_list_context(request):
    """Helper to build context for task list partial."""
    user = request.user
    folders = get_task_folders(request)
    selected_folder = select_folder(request, "tasks")
    tasks_folder_all = request.session.get("tasks_all", False)

    if tasks_folder_all:
        queryset = Task.objects.filter(user=user, is_recurring=False)
    elif selected_folder:
        queryset = Task.objects.filter(folder=selected_folder, is_recurring=False)
    else:
        queryset = Task.objects.filter(
            user=user, folder__isnull=True, is_recurring=False
        )

    filter_data = request.session.get("tasks_filter", {})
    filter_label = filter_data.get("filter_label", "")
    task_filter = TasksFilter(filter_data, queryset=queryset)
    tasks = task_filter.qs

    # Default behavior: if no custom filter, exclude archived
    if filter_label not in ("custom", "due"):
        tasks = tasks.filter(archived=False)

    # Apply sort — always push completed tasks to the bottom
    sort = filter_data.get("sort", "priority")
    valid_sorts = (
        "title",
        "-title",
        "due_date",
        "-due_date",
        "-created_at",
        "priority",
        "-priority",
    )
    if sort in valid_sorts:
        tasks = tasks.order_by("status", sort)

    session_key = "tasks_page"
    trigger_key = "tasksChanged"
    pagination = CustomPaginator(tasks, 20, request, session_key)

    task_list = pagination.get_object_list()

    priority_value = filter_data.get("priority")
    priority_value = (
        int(priority_value) if priority_value not in (None, "", 0) else None
    )

    return {
        "page": "tasks",
        "folders": folders,
        "selected_folder": selected_folder,
        "tasks": task_list,
        "pagination": pagination,
        "session_key": session_key,
        "trigger_key": trigger_key,
        "filter_label": filter_label,
        "tasks_folder_all": tasks_folder_all,
        "has_completed_tasks": any(t.status == 1 for t in task_list),
        "priority_choices": range(1, 11),
        "priorities": list(range(1, 11)),
        "priority_value": priority_value,
        "current_sort": sort,
    }


@login_required
def index(request):
    """Display a list of folders and one or more lists of tasks.

    Notes:
        * Always displays folders.
        * If a folder is selected, displays the tasks for that folder.
        * Allows the display of mulitple task folders.
        * Task folders are informally called "lists" but are part of the consolidated
          folder system for the whole site.
    """

    context = _get_task_list_context(request)
    return render(request, "tasks/content.html", context)


@login_required
def status(request, id, origin="tasks"):
    """Update a task status to complete / not complete

    Args:
        id (int): a task id
        origin (str): the page from which the request originated and should return

    Notes:
        Tasks may be updated from the home or the task page,
        in which case, the user should be returned to the page of origin.
    """

    task = get_object_or_404(Task, pk=id)
    if task.status == 1:
        task.status = 0
        task.completed_date = None
    else:
        task.status = 1
        task.completed_date = date.today()
    task.save()
    return redirect(origin)


@login_required
def add(request):
    """Add a new task.

    Notes:
        GET: There is no get method for this view.
             The task form is always visible via "index".
        POST: Add task to database.
    """

    if request.method == "POST":
        task = Task()

        task.user = request.user
        task.title = request.POST.get("title")
        task.title = task.title[0].upper() + task.title[1:]

        try:
            folder = Folder.objects.filter(pk=request.POST.get("folder_id")).get()
            task.folder = folder
            task.save()

        except ValueError:
            task.save()

        return redirect("tasks")


@login_required
def edit(request, id):
    """Edit a task.

    Args:
        id (int): A Task instance id

    Notes:
        GET: Display task edit form.
        POST: Update task in database.
    """

    user = request.user

    if request.method == "POST":
        try:
            task = Task.objects.filter(pk=id).get()
        except ObjectDoesNotExist:
            raise Http404("Record not found.")

        # Check if this task was already recurring before the edit
        was_recurring = task.is_recurring
        parent_task = task.parent_task  # Capture before form.save()

        form = TaskForm(request.POST, instance=task)
        if form.is_valid():
            task = form.save(commit=False)
            task.user = user
            task.title = task.title[0].upper() + task.title[1:]
            recurrence = form.cleaned_data.get("recurrence")

            # If editing a recurring instance, sync changes to the template
            if parent_task:
                task.save()
                parent_task.folder = task.folder
                parent_task.title = task.title
                parent_task.priority = task.priority
                parent_task.due_time = task.due_time
                if recurrence:
                    parent_task.recurrence_type = recurrence
                    if task.due_date:
                        if recurrence == "daily":
                            parent_task.recurrence_day = None
                        elif recurrence == "monthly":
                            parent_task.recurrence_day = task.due_date.day
                        elif recurrence == "weekly":
                            parent_task.recurrence_day = task.due_date.weekday()
                        elif recurrence == "yearly":
                            parent_task.recurrence_day = task.due_date.day
                            parent_task.recurrence_month = task.due_date.month
                    parent_task.save()
                else:
                    # Recurrence removed - delete the template
                    parent_task.delete()
                    task.parent_task = None
                    task.save()

            # Editing a regular task or a template
            else:
                if recurrence:
                    task.is_recurring = True
                    task.recurrence_type = recurrence

                    # Set recurrence_day based on due_date
                    if task.due_date:
                        if recurrence == "daily":
                            task.recurrence_day = None
                        elif recurrence == "monthly":
                            task.recurrence_day = task.due_date.day
                        elif recurrence == "weekly":
                            task.recurrence_day = task.due_date.weekday()
                        elif recurrence == "yearly":
                            task.recurrence_day = task.due_date.day
                            task.recurrence_month = task.due_date.month
                else:
                    task.is_recurring = False
                    task.recurrence_type = None
                    task.recurrence_day = None
                    task.recurrence_month = None

                task.save()

                # If task just became recurring, create the first instance immediately
                if task.is_recurring and not was_recurring:
                    from datetime import date

                    Task.objects.create(
                        user=task.user,
                        folder=task.folder,
                        title=task.title,
                        priority=task.priority,
                        status=0,
                        due_date=task.due_date,
                        due_time=task.due_time,
                        parent_task=task,
                    )
                    task.last_generated = date.today()
                    task.save(update_fields=["last_generated"])

                # If editing a recurring template, update the most recent incomplete instance
                elif task.is_recurring and was_recurring:
                    latest_instance = (
                        Task.objects.filter(parent_task=task, status=0)
                        .order_by("-due_date")
                        .first()
                    )
                    if latest_instance:
                        latest_instance.folder = task.folder
                        latest_instance.title = task.title
                        latest_instance.priority = task.priority
                        latest_instance.due_time = task.due_time
                        latest_instance.save()

        return redirect("tasks")

    else:
        task = get_object_or_404(Task, pk=id)
        folders = get_task_folders(request)
        try:
            selected_folder = folders.filter(id=task.folder.id).get()
        except AttributeError:
            selected_folder = None

        if selected_folder:
            form = TaskForm(instance=task, initial={"folder": selected_folder.id})
        else:
            form = TaskForm(instance=task)

        form.fields["folder"].queryset = folders

        # For recurring instances, show recurrence field with parent's value
        if task.parent_task:
            form.fields["recurrence"].initial = task.parent_task.recurrence_type

        context = {
            "page": "tasks",
            "edit": True,
            "folders": folders,
            "selected_folder": selected_folder,
            "action": f"/tasks/{id}/edit",
            "task": task,
            "form": form,
        }

        return render(request, "tasks/content.html", context)


@login_required
def delete(request, id):
    """Delete a task.

    Args:
        id (int): A Task instance id
    """
    task = get_object_or_404(Task, pk=id, user=request.user)
    task.delete()
    return redirect("tasks")


@login_required
def clear(request):
    """Archive all completed tasks in the active folder."""
    selected_folder = select_folder(request, "tasks")

    if selected_folder:
        Task.objects.filter(folder=selected_folder, status=1).update(archived=True)
    else:
        Task.objects.filter(user=request.user, folder__isnull=True, status=1).update(
            archived=True
        )

    return redirect("/tasks/")


@login_required
def add_editor(request, folder_id, user_id):
    folder = get_object_or_404(Folder, pk=folder_id)
    user = get_object_or_404(CustomUser, pk=user_id)
    folder.editors.add(user)
    folder.save()
    return redirect("/tasks/")


@login_required
def remove_editor(request, folder_id, user_id):
    folder = get_object_or_404(Folder, pk=folder_id)
    user = get_object_or_404(CustomUser, pk=user_id)
    folder.editors.remove(user)
    folder.save()
    return redirect("/tasks/")


# HTMX Views


@login_required
def tasks_all(request):
    """Select 'All' folder view and return updated tasks with folders OOB."""
    request.session["tasks_all"] = True
    request.user.tasks_folder = 0
    request.user.save()
    context = _get_task_list_context(request)
    return render(request, "tasks/tasks-with-folders-oob.html", context)


@login_required
def tasks_due(request):
    """Toggle quick filter: stash current filter and show due tasks, or restore."""
    current_filter = request.session.get("tasks_filter", {})
    stash = request.session.get("tasks_filter_stash")

    if current_filter.get("filter_label") == "due" and stash is not None:
        # Restore stashed state
        request.session["tasks_filter"] = stash["tasks_filter"]
        request.session["tasks_all"] = stash["tasks_all"]
        request.user.tasks_folder = stash["tasks_folder"]
        request.user.save()
        request.session.pop("tasks_filter_stash", None)
    else:
        # Stash current state and apply due filter
        request.session["tasks_filter_stash"] = {
            "tasks_filter": current_filter,
            "tasks_all": request.session.get("tasks_all", False),
            "tasks_folder": request.user.tasks_folder,
        }
        request.session["tasks_all"] = True
        request.user.tasks_folder = 0
        request.user.save()
        request.session["tasks_filter"] = {
            "filter_label": "due",
            "status": "Pending",
            "due_date_max": date.today().strftime("%Y-%m-%d"),
            "sort": "due_date",
        }

    context = _get_task_list_context(request)
    return render(request, "tasks/tasks-with-folders-oob.html", context)


@login_required
def task_list(request):
    """Return task list partial for htmx."""
    context = _get_task_list_context(request)
    return render(request, "tasks/list.html", context)


@login_required
def task_filter(request):
    """Display or apply task filter."""
    if request.method == "POST":
        filter_data = {
            k: v for k, v in request.POST.items() if k != "csrfmiddlewaretoken"
        }
        filter_data["filter_label"] = "custom"
        request.session["tasks_filter"] = filter_data
        request.session.pop("tasks_filter_stash", None)
        return HttpResponse(status=204, headers={"HX-Trigger": "tasksChanged"})

    filter_data = request.session.get("tasks_filter", {})
    task_filter = TasksFilter(filter_data)
    return render(
        request,
        "tasks/filter.html",
        {
            "filter": task_filter,
            "sort_value": filter_data.get("sort", ""),
        },
    )


@login_required
def tasks_order_by(request, order):
    """Sort tasks by column header click."""
    filter_data = request.session.get("tasks_filter", {})
    current_sort = filter_data.get("sort", "priority")

    if current_sort == order:
        new_sort = f"-{order}"
    elif current_sort == f"-{order}":
        new_sort = order
    else:
        new_sort = order

    filter_data["sort"] = new_sort
    request.session["tasks_filter"] = filter_data
    request.session["tasks_page"] = 1
    request.session.pop("tasks_filter_stash", None)
    request.session.modified = True

    return HttpResponse(status=204, headers={"HX-Trigger": "tasksChanged"})


@login_required
def task_filter_default(request):
    """Clear task filter to defaults."""
    request.session.pop("tasks_filter", None)
    request.session.pop("tasks_filter_stash", None)
    return HttpResponse(status=204, headers={"HX-Trigger": "tasksChanged"})


@login_required
def add_htmx(request):
    """Add a new task via htmx and return updated list."""
    if request.method == "POST":
        task = Task()
        task.user = request.user
        task.title = request.POST.get("title", "").strip()

        if task.title:
            task.title = task.title[0].upper() + task.title[1:]

            try:
                folder = Folder.objects.filter(pk=request.POST.get("folder_id")).get()
                task.folder = folder
            except (ValueError, Folder.DoesNotExist):
                pass

            task.save()

    context = _get_task_list_context(request)
    return render(request, "tasks/list.html", context)


@login_required
def task_form(request, id):
    """Return task edit form in modal, or process form submission."""
    user = request.user
    task = get_object_or_404(Task, pk=id)
    folders = get_task_folders(request)

    if request.method == "POST":
        # Check if this task was already recurring before the edit
        was_recurring = task.is_recurring
        parent_task = task.parent_task
        old_status = task.status

        form = TaskForm(request.POST, instance=task, use_required_attribute=False)
        form.fields["folder"].queryset = folders
        if form.is_valid():
            task = form.save(commit=False)
            task.user = user
            task.title = task.title[0].upper() + task.title[1:]
            recurrence = form.cleaned_data.get("recurrence")

            # Update completed_date when status changes
            if task.status == 1 and old_status != 1:
                task.completed_date = date.today()
            elif task.status != 1 and old_status == 1:
                task.completed_date = None

            # If editing a recurring instance, sync changes to the template
            if parent_task:
                task.save()
                parent_task.folder = task.folder
                parent_task.title = task.title
                parent_task.priority = task.priority
                parent_task.due_time = task.due_time
                if recurrence:
                    parent_task.recurrence_type = recurrence
                    if task.due_date:
                        if recurrence == "daily":
                            parent_task.recurrence_day = None
                        elif recurrence == "monthly":
                            parent_task.recurrence_day = task.due_date.day
                        elif recurrence == "weekly":
                            parent_task.recurrence_day = task.due_date.weekday()
                        elif recurrence == "yearly":
                            parent_task.recurrence_day = task.due_date.day
                            parent_task.recurrence_month = task.due_date.month
                    parent_task.save()
                else:
                    parent_task.delete()
                    task.parent_task = None
                    task.save()
            else:
                if recurrence:
                    task.is_recurring = True
                    task.recurrence_type = recurrence
                    if task.due_date:
                        if recurrence == "daily":
                            task.recurrence_day = None
                        elif recurrence == "monthly":
                            task.recurrence_day = task.due_date.day
                        elif recurrence == "weekly":
                            task.recurrence_day = task.due_date.weekday()
                        elif recurrence == "yearly":
                            task.recurrence_day = task.due_date.day
                            task.recurrence_month = task.due_date.month
                else:
                    task.is_recurring = False
                    task.recurrence_type = None
                    task.recurrence_day = None
                    task.recurrence_month = None

                task.save()

                if task.is_recurring and not was_recurring:
                    from datetime import date

                    Task.objects.create(
                        user=task.user,
                        folder=task.folder,
                        title=task.title,
                        priority=task.priority,
                        status=0,
                        due_date=task.due_date,
                        due_time=task.due_time,
                        parent_task=task,
                    )
                    task.last_generated = date.today()
                    task.save(update_fields=["last_generated"])
                elif task.is_recurring and was_recurring:
                    latest_instance = (
                        Task.objects.filter(parent_task=task, status=0)
                        .order_by("-due_date")
                        .first()
                    )
                    if latest_instance:
                        latest_instance.folder = task.folder
                        latest_instance.title = task.title
                        latest_instance.priority = task.priority
                        latest_instance.due_time = task.due_time
                        latest_instance.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "tasksChanged"})

        # Form validation failed - re-render form with errors

    else:
        # GET request - display the form
        form = TaskForm(instance=task, use_required_attribute=False)

        if task.parent_task:
            form.fields["recurrence"].initial = task.parent_task.recurrence_type

    context = {
        "page": "tasks",
        "edit": True,
        "action": f"/tasks/{id}/form",
        "task": task,
        "form": form,
        "folders": get_folders_for_page(request, "tasks"),
    }
    return render(request, "tasks/modal-form.html", context)


@login_required
def status_htmx(request, id):
    """Toggle task status via htmx and return updated list."""
    task = get_object_or_404(Task, pk=id)
    if task.status == 1:
        task.status = 0
        task.completed_date = None
    else:
        task.status = 1
        task.completed_date = date.today()
    task.save()

    # Generate next recurring instance on completion
    if task.status == 1 and task.parent_task:
        parent = task.parent_task
        if parent.is_recurring and not parent.archived:
            has_pending = Task.objects.filter(
                parent_task=parent, status=0, archived=False
            ).exists()
            if not has_pending:
                Task.objects.create(
                    user=parent.user,
                    folder=parent.folder,
                    title=parent.title,
                    priority=parent.priority,
                    status=0,
                    due_date=date.today(),
                    due_time=parent.due_time,
                    parent_task=parent,
                )
                parent.last_generated = date.today()
                parent.save(update_fields=["last_generated"])

    context = _get_task_list_context(request)
    return render(request, "tasks/list.html", context)


@login_required
def priority_htmx(request, id):
    """Update task priority via htmx and return updated list."""
    task = get_object_or_404(Task, pk=id)
    priority = request.GET.get("priority")
    if priority:
        task.priority = int(priority)
        task.save(update_fields=["priority"])

    context = _get_task_list_context(request)
    return render(request, "tasks/list.html", context)


@login_required
def delete_htmx(request, id):
    """Delete task via htmx and close modal."""
    task = get_object_or_404(Task, pk=id, user=request.user)
    task.delete()
    return HttpResponse(status=204, headers={"HX-Trigger": "tasksChanged"})


@login_required
def bulk_status_htmx(request):
    """Set all visible tasks to complete or pending."""
    new_status = int(request.GET.get("status", 0))
    tasks_folder_all = request.session.get("tasks_all", False)
    selected_folder = select_folder(request, "tasks")

    if tasks_folder_all:
        qs = Task.objects.filter(user=request.user, is_recurring=False, archived=False)
    elif selected_folder:
        qs = Task.objects.filter(
            folder=selected_folder, is_recurring=False, archived=False
        )
    else:
        qs = Task.objects.filter(
            user=request.user, folder__isnull=True, is_recurring=False, archived=False
        )

    if new_status == 1:
        qs.filter(status=0).update(status=1, completed_date=date.today())
    else:
        qs.filter(status=1).update(status=0, completed_date=None)

    context = _get_task_list_context(request)
    return render(request, "tasks/list.html", context)


@login_required
def clear_htmx(request):
    """Archive completed tasks via htmx and return updated list."""
    tasks_folder_all = request.session.get("tasks_all", False)
    selected_folder = select_folder(request, "tasks")

    if tasks_folder_all:
        Task.objects.filter(user=request.user, status=1).update(archived=True)
    elif selected_folder:
        Task.objects.filter(folder=selected_folder, status=1).update(archived=True)
    else:
        Task.objects.filter(user=request.user, folder__isnull=True, status=1).update(
            archived=True
        )

    context = _get_task_list_context(request)
    return render(request, "tasks/list.html", context)


@login_required
def delete_completed_htmx(request):
    """Delete completed tasks via htmx and return updated list."""
    tasks_folder_all = request.session.get("tasks_all", False)
    selected_folder = select_folder(request, "tasks")

    if tasks_folder_all:
        Task.objects.filter(user=request.user, status=1).delete()
    elif selected_folder:
        Task.objects.filter(folder=selected_folder, status=1).delete()
    else:
        Task.objects.filter(user=request.user, folder__isnull=True, status=1).delete()

    context = _get_task_list_context(request)
    return render(request, "tasks/list.html", context)


@login_required
def filter_priority_htmx(request, priority_value):
    """Filter tasks by priority level via htmx."""
    filter_data = request.session.get("tasks_filter", {})
    filter_data["priority"] = "" if priority_value == 0 else priority_value
    request.session["tasks_filter"] = filter_data
    request.session.pop("tasks_filter_stash", None)
    request.session.modified = True

    context = _get_task_list_context(request)
    return render(request, "tasks/list.html", context)


@login_required
def move_folder_htmx(request):
    """Move completed tasks to a different folder via htmx."""
    tasks_folder_all = request.session.get("tasks_all", False)
    selected_folder = select_folder(request, "tasks")

    if tasks_folder_all:
        qs = Task.objects.filter(user=request.user, status=1, archived=False)
    elif selected_folder:
        qs = Task.objects.filter(folder=selected_folder, status=1, archived=False)
    else:
        qs = Task.objects.filter(
            user=request.user, folder__isnull=True, status=1, archived=False
        )

    folder_id = request.GET.get("folder_id", "")
    if folder_id:
        folder = get_object_or_404(Folder, pk=folder_id, user=request.user)
        qs.update(folder=folder)
    else:
        qs.update(folder=None)

    context = _get_task_list_context(request)
    return render(request, "tasks/list.html", context)
