from datetime import date, datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from accounts.models import CustomUser
from apps.common import notify
from apps.folders.folders import get_folders_for_page, get_task_folders, select_folder
from apps.folders.models import Folder
from apps.management.pagination import CustomPaginator
from apps.tasks import recurring, reminders
from apps.tasks.filter import TasksFilter
from apps.tasks.forms import TaskForm, TaskReminderForm
from apps.tasks.models import Task
from apps.tasks.priority import (
    DATE_FILTER_NAMES,
    default_due_date,
    level_for,
    levels,
    quick_date_filters,
)


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

    filter_data = dict(request.session.get("tasks_filter", {}))
    filter_label = filter_data.get("filter_label", "")

    # A date preset is worked out afresh each time, so "Today" is still
    # today tomorrow
    presets = quick_date_filters(date.today())
    if filter_label in presets:
        filter_data.update(presets[filter_label])

    task_filter = TasksFilter(filter_data, queryset=queryset)
    tasks = task_filter.qs

    # Archived tasks show only when the filter dialog asks for them
    if filter_label != "custom":
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
    for task in task_list:
        task.level = level_for(task.priority)

    base_count_qs = Task.objects.filter(user=user, is_recurring=False, archived=False)

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
        # The header's check toggles: all checked means the next click unchecks
        "all_complete": bool(task_list) and all(t.status == 1 for t in task_list),
        "priority_levels": levels(),
        "date_filter_label": filter_label if filter_label in presets else "all",
        "date_filter_name": DATE_FILTER_NAMES.get(filter_label, "All Dates"),
        "date_filter_names": DATE_FILTER_NAMES,
        "today": date.today(),
        "current_sort": sort,
        "all_count": base_count_qs.count(),
        "inbox_count": base_count_qs.filter(folder__isnull=True).count(),
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
        task.save()
    else:
        task.status = 1
        task.completed_date = date.today()
        mode = request.user.task_completion_mode
        if mode == "delete":
            task.delete()
        else:
            if mode == "archive":
                task.archived = True
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
        task.due_date = default_due_date(
            request.session.get("tasks_filter", {}), date.today()
        )
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

        form = TaskForm(request.POST, instance=task)
        if form.is_valid():
            task = form.save(commit=False)
            task.user = user
            task.time_zone = user.time_zone
            task.title = task.title[0].upper() + task.title[1:]
            task.save()
            recurring.apply_edit(task, form.rule(), form.repeat_start())

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
@require_POST
def filter_date_htmx(request, preset):
    """Apply one of the date dropdown's presets, or "all" to clear it. Only
    the date dimension changes; status and sort stay as they are."""
    presets = quick_date_filters(date.today())
    if preset not in presets:
        return HttpResponse("Unknown date filter", status=400)

    filter_data = request.session.get("tasks_filter", {})
    filter_data.update(presets[preset])
    filter_data["filter_label"] = preset
    request.session["tasks_filter"] = filter_data
    request.session["tasks_page"] = 1
    request.session.modified = True

    context = _get_task_list_context(request)
    return render(request, "tasks/list.html", context)


@login_required
@require_POST
def due_date_htmx(request, id):
    """Set or clear a task's due date from the list's Due column. Clearing
    the date clears the time with it."""
    task = get_object_or_404(Task, pk=id, user=request.user)
    value = request.POST.get("due_date", "").strip()
    if value:
        try:
            task.due_date = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return HttpResponse("Unreadable date", status=400)
        task.time_zone = request.user.time_zone
    else:
        task.due_date = None
        task.due_time = None
    task.save(update_fields=["due_date", "due_time", "time_zone"])

    context = _get_task_list_context(request)
    response = render(request, "tasks/list.html", context)
    response["HX-Trigger"] = "tasksChanged"
    return response


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
    request.session.modified = True

    return HttpResponse(status=204, headers={"HX-Trigger": "tasksChanged"})


@login_required
def task_filter_default(request):
    """Clear task filter to defaults."""
    request.session.pop("tasks_filter", None)
    return HttpResponse(status=204, headers={"HX-Trigger": "tasksChanged"})


@login_required
def add_htmx(request):
    """Add a new task via htmx and return updated list."""
    if request.method == "POST":
        task = Task()
        task.user = request.user
        # The filter in force sets the date: today's view gives today,
        # tomorrow's gives tomorrow, and the rest give none
        task.due_date = default_due_date(
            request.session.get("tasks_filter", {}), date.today()
        )
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
    response = render(request, "tasks/list.html", context)
    response["HX-Trigger"] = "tasksChanged"
    return response


@login_required
def task_form(request, id):
    """Return task edit form in modal, or process form submission."""
    user = request.user
    task = get_object_or_404(Task, pk=id)
    folders = get_task_folders(request)

    if request.method == "POST":
        old_status = task.status

        form = TaskForm(request.POST, instance=task, use_required_attribute=False)
        form.fields["folder"].queryset = folders
        if form.is_valid():
            task = form.save(commit=False)
            task.user = user
            task.time_zone = user.time_zone
            task.title = task.title[0].upper() + task.title[1:]

            # Update completed_date when status changes
            if task.status == 1 and old_status != 1:
                task.completed_date = date.today()
            elif task.status != 1 and old_status == 1:
                task.completed_date = None

            task.save()
            recurring.apply_edit(task, form.rule(), form.repeat_start())
            # A recurring task's instance marked done here brings on the next
            if task.status == 1 and old_status != 1:
                recurring.after_completion(task)
            return HttpResponse(status=204, headers={"HX-Trigger": "tasksChanged"})

        # Form validation failed - re-render form with errors

    else:
        # GET request - display the form, its due date and time as seen
        # from where the user is now
        form = TaskForm(
            instance=task,
            initial=vars(task.in_zone(user.time_zone)),
            use_required_attribute=False,
        )

    context = {
        "page": "tasks",
        "edit": True,
        "action": f"/tasks/{id}/form",
        "task": task,
        "form": form,
        "folders": get_folders_for_page(request, "tasks"),
    } | _reminders_context(task)
    return render(request, "tasks/modal-form.html", context)


def _reminders_context(task, reminder_form=None):
    """The Notifications section of the task form (components/reminders.html).
    A task needs a due date before it can have one."""
    task_reminders = list(task.reminders.all())
    for reminder in task_reminders:
        reminder.delete_url = reverse(
            "tasks-reminder-delete", args=[task.id, reminder.id]
        )
    if task.due_date:
        form = reminder_form or TaskReminderForm(task=task)
        note = ""
    else:
        form = None
        note = "Set a due date to add notifications."
    return {
        "reminders": task_reminders,
        "reminder_form": form,
        "reminder_add_url": reverse("tasks-reminder-add", args=[task.id]),
        "reminders_note": note,
    }


@login_required
@require_POST
def reminder_add(request, id):
    """Add a notification to the task and re-render the section."""
    task = get_object_or_404(Task, pk=id, user=request.user)
    form = TaskReminderForm(request.POST, task=task)
    if task.due_date and form.is_valid():
        data = form.cleaned_data
        reminders.add_reminder(
            task, data["amount"], data["unit"], data["time"], data["channel"]
        )
        form = None
    return render(request, "components/reminders.html", _reminders_context(task, form))


@login_required
@require_http_methods(["POST", "DELETE"])
def reminder_delete(request, id, reminder_id):
    """Remove a notification from the task and re-render the section."""
    task = get_object_or_404(Task, pk=id, user=request.user)
    reminders.remove_reminder(task, reminder_id)
    return render(request, "components/reminders.html", _reminders_context(task))


def complete_task(task, user):
    """Mark a task done the way the user has chosen (keep it, archive it,
    or delete it) and bring on a recurring task's next instance."""
    task.status = 1
    task.completed_date = date.today()
    mode = user.task_completion_mode
    if mode == "delete":
        task.delete()
    else:
        if mode == "archive":
            task.archived = True
        task.save()
    recurring.after_completion(task)


@csrf_exempt
@require_POST
def notify_done(request, token):
    """A notification's Done button (apps.common.notify.done_link): marks the
    task done without a login, the signed token standing for one. Pressing
    it again, or on a task done another way, changes nothing."""
    found = notify.read_done_link(token)
    if found is None:
        return HttpResponse("This link has expired.", status=403)
    task_id, user_id = found
    task = (
        Task.objects.filter(pk=task_id, user_id=user_id).select_related("user").first()
    )
    if task is None:
        return HttpResponse("This task is gone.", status=404)
    if task.status != 1:
        complete_task(task, task.user)
    return HttpResponse("Done.")


@login_required
def status_htmx(request, id):
    """Toggle task status via htmx and return updated list."""
    task = get_object_or_404(Task, pk=id)
    if task.status == 1:
        task.status = 0
        task.completed_date = None
        task.save()
    else:
        task.status = 1
        task.completed_date = date.today()
        mode = request.user.task_completion_mode
        if mode == "delete":
            task.delete()
        else:
            if mode == "archive":
                task.archived = True
            task.save()

    # A recurring task's instance done brings on the next, due on its
    # rule's next day
    if task.status == 1:
        recurring.after_completion(task)

    context = _get_task_list_context(request)
    response = render(request, "tasks/list.html", context)
    response["HX-Trigger"] = "tasksChanged"
    return response


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
        pending = qs.filter(status=0)
        mode = request.user.task_completion_mode
        if mode == "delete":
            pending.delete()
        elif mode == "archive":
            pending.update(status=1, completed_date=date.today(), archived=True)
        else:
            pending.update(status=1, completed_date=date.today())
    else:
        qs.filter(status=1).update(status=0, completed_date=None)

    context = _get_task_list_context(request)
    response = render(request, "tasks/list.html", context)
    response["HX-Trigger"] = "tasksChanged"
    return response


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
    response = render(request, "tasks/list.html", context)
    response["HX-Trigger"] = "tasksChanged"
    return response


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
    response = render(request, "tasks/list.html", context)
    response["HX-Trigger"] = "tasksChanged"
    return response


def _checked_tasks(request):
    """The checked (completed) tasks in the view the user is looking at:
    every folder, the selected folder, or the Inbox. The bulk buttons
    under the list act on these."""
    if request.session.get("tasks_all", False):
        return Task.objects.filter(user=request.user, status=1, archived=False)
    selected_folder = select_folder(request, "tasks")
    if selected_folder:
        return Task.objects.filter(folder=selected_folder, status=1, archived=False)
    return Task.objects.filter(
        user=request.user, folder__isnull=True, status=1, archived=False
    )


def _list_response(request):
    context = _get_task_list_context(request)
    response = render(request, "tasks/list.html", context)
    response["HX-Trigger"] = "tasksChanged"
    return response


@login_required
@require_POST
def bulk_due_date_htmx(request):
    """Give the checked tasks a due date: today, tomorrow, a week out, a
    chosen day, or none. Clearing the date clears the time with it."""
    value = request.POST.get("due_date", "").strip()
    today = date.today()
    presets = {
        "today": today,
        "tomorrow": today + timedelta(days=1),
        "week": today + timedelta(days=7),
    }
    if value in presets:
        due_date = presets[value]
    elif value:
        try:
            due_date = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return HttpResponse("Unreadable date", status=400)
    else:
        due_date = None

    tasks = _checked_tasks(request)
    if due_date is None:
        tasks.update(due_date=None, due_time=None)
    else:
        tasks.update(due_date=due_date, time_zone=request.user.time_zone)
    return _list_response(request)


@login_required
@require_POST
def bulk_priority_htmx(request, priority_value):
    """Give the checked tasks a priority level."""
    if not 1 <= priority_value <= 10:
        return HttpResponse("Unknown priority", status=400)
    _checked_tasks(request).update(priority=priority_value)
    return _list_response(request)


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
    response = render(request, "tasks/list.html", context)
    response["HX-Trigger"] = "tasksChanged"
    return response
