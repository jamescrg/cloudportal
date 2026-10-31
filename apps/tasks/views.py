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
from apps.common.forms import dialog_timing, follow_fields
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

VALID_SORTS = (
    "title",
    "-title",
    "due_date",
    "-due_date",
    "-created_at",
    "priority",
    "-priority",
)


# Each task list (a folder, the Inbox, All) remembers the sort and the date
# preset last chosen for it, in the user's task_views, so a grocery list
# stays alphabetical and unscheduled, and a working list stays on Today,
# with nothing to set up.


def _view_key(request):
    """The key the list in view keeps its view under: "all", "inbox" or
    the folder's id."""
    if request.session.get("tasks_all", False):
        return "all"
    folder = select_folder(request, "tasks")
    return str(folder.id) if folder else "inbox"


def _list_view(request):
    return dict((request.user.task_views or {}).get(_view_key(request), {}))


def _save_list_view(request, **values):
    """Remember values for the list in view; a blank one is forgotten."""
    views = dict(request.user.task_views or {})
    key = _view_key(request)
    view = dict(views.get(key, {}))
    for name, value in values.items():
        if value:
            view[name] = value
        else:
            view.pop(name, None)
    if view:
        views[key] = view
    else:
        views.pop(key, None)
    request.user.task_views = views
    request.user.save(update_fields=["task_views"])
    request.session["tasks_page"] = 1


def get_sort(request):
    """The sort of the list in view, Priority until one is chosen."""
    sort = _list_view(request).get("sort", "priority")
    return sort if sort in VALID_SORTS else "priority"


def set_sort(request, sort):
    _save_list_view(request, sort=sort if sort in VALID_SORTS else "")


def current_filter(request):
    """The filter in force for the list in view: the session's filter
    (status, archived, and the filter dialog's dates), with the list's own
    date preset over it, unless the filter dialog's custom dates are in
    force. A preset is worked out afresh each time, so "Today" is still
    today tomorrow."""
    filter_data = dict(request.session.get("tasks_filter", {}))
    if filter_data.get("filter_label") == "custom":
        return filter_data
    presets = quick_date_filters(date.today())
    preset = _list_view(request).get("date", "all")
    if preset not in presets:
        preset = "all"
    filter_data.update(presets[preset])
    filter_data["filter_label"] = preset
    return filter_data


# The filter dialog's fields, apart from the sort and the due dates a
# list's date preset fills in
DIALOG_FIELDS = (
    "status",
    "recurring",
    "completed_date_min",
    "completed_date_max",
    "created_at_min",
    "created_at_max",
)


def _filter_dialog_in_use(filter_data):
    return filter_data.get("filter_label") == "custom" or any(
        filter_data.get(name) for name in DIALOG_FIELDS
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

    filter_data = current_filter(request)
    filter_label = filter_data["filter_label"]
    presets = quick_date_filters(date.today())

    task_filter = TasksFilter(filter_data, queryset=queryset)
    tasks = task_filter.qs

    # Archived tasks show only when the filter dialog asks for them
    if filter_data.get("show_archived") != "true":
        tasks = tasks.filter(archived=False)

    # Each list keeps its own sort; completed tasks always go to the bottom
    sort = get_sort(request)
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
        # The Filter button is lit while the dialog narrows the list
        "filter_active": _filter_dialog_in_use(filter_data),
        "show_archived": filter_data.get("show_archived") == "true",
        "tasks_folder_all": tasks_folder_all,
        "has_completed_tasks": any(t.status == 1 for t in task_list),
        # The header's check toggles: all checked means the next click unchecks
        "all_complete": bool(task_list) and all(t.status == 1 for t in task_list),
        "priority_levels": levels(),
        "date_filter_label": filter_label if filter_label in presets else "all",
        "date_filter_name": DATE_FILTER_NAMES.get(filter_label, "All Dates"),
        "date_filter_names": DATE_FILTER_NAMES,
        # The dropdown is lit while it narrows the list to a span of dates;
        # All Dates and Unscheduled leave it plain
        "date_filter_scheduled": filter_label in presets
        and filter_label not in ("all", "unscheduled"),
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

    task = get_object_or_404(Task, pk=id, user=request.user)
    if task.status == 1:
        task.status = 0
        task.completed_date = None
        task.save()
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
        task.due_date = default_due_date(current_filter(request), date.today())
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
            task = Task.objects.filter(pk=id, user=user).get()
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
        task = get_object_or_404(Task, pk=id, user=request.user)
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


def apply_date_preset(request, preset):
    """Remember a date preset for the list in view, leaving status and
    sort as they are. A preset ends the filter dialog's custom dates. False
    when the preset is unknown."""
    if preset not in quick_date_filters(date.today()):
        return False

    filter_data = request.session.get("tasks_filter", {})
    if filter_data.get("filter_label") == "custom":
        for name in ("due_date_min", "due_date_max", "has_due_date"):
            filter_data.pop(name, None)
        filter_data["filter_label"] = ""
        request.session["tasks_filter"] = filter_data
    # All Dates is the default, so it need not be kept
    _save_list_view(request, date="" if preset == "all" else preset)
    return True


@login_required
@require_POST
def filter_date_htmx(request, preset):
    """Apply one of the date dropdown's presets, or "all" to clear it. Only
    the date dimension changes; status and sort stay as they are."""
    if not apply_date_preset(request, preset):
        return HttpResponse("Unknown date filter", status=400)

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
@require_POST
def filter_archived_htmx(request, mode):
    """Show or hide archived tasks, from the toolbar's Archived dropdown.
    Like the filter dialog, it holds for every list until changed."""
    if mode not in ("show", "hide"):
        return HttpResponse("Unknown archived filter", status=400)

    filter_data = request.session.get("tasks_filter", {})
    filter_data["show_archived"] = "true" if mode == "show" else "false"
    request.session["tasks_filter"] = filter_data
    request.session["tasks_page"] = 1
    request.session.modified = True

    context = _get_task_list_context(request)
    return render(request, "tasks/list.html", context)


@login_required
def task_filter(request):
    """Display or apply task filter."""
    if request.method == "POST":
        filter_data = {
            k: v for k, v in request.POST.items() if k != "csrfmiddlewaretoken"
        }
        # The sort belongs to the list in view, not the session's filter
        if "sort" in filter_data:
            set_sort(request, filter_data.pop("sort"))
        # Archived tasks are shown or hidden from the toolbar's dropdown,
        # which the dialog leaves as it was
        show_archived = request.session.get("tasks_filter", {}).get("show_archived")
        if show_archived:
            filter_data["show_archived"] = show_archived
        # Only a due-date range of the dialog's own sets the dates aside
        # from each list's date preset
        due_range = filter_data.get("due_date_min") or filter_data.get("due_date_max")
        filter_data["filter_label"] = "custom" if due_range else ""
        request.session["tasks_filter"] = filter_data
        return HttpResponse(status=204, headers={"HX-Trigger": "tasksChanged"})

    filter_data = request.session.get("tasks_filter", {})
    task_filter = TasksFilter(filter_data)
    return render(
        request,
        "tasks/filter.html",
        {
            "filter": task_filter,
            "sort_value": get_sort(request),
        },
    )


@login_required
def tasks_order_by(request, order):
    """Sort the list in view by a column header click; the list keeps
    the sort until another is chosen for it."""
    current_sort = get_sort(request)

    if current_sort == order:
        new_sort = f"-{order}"
    elif current_sort == f"-{order}":
        new_sort = order
    else:
        new_sort = order

    set_sort(request, new_sort)

    return HttpResponse(status=204, headers={"HX-Trigger": "tasksChanged"})


@login_required
def task_filter_default(request):
    """Clear task filter to defaults, and the list in view's sort and date
    preset with it."""
    request.session.pop("tasks_filter", None)
    _save_list_view(request, sort="", date="")
    return HttpResponse(status=204, headers={"HX-Trigger": "tasksChanged"})


@login_required
def add_htmx(request):
    """Add a new task via htmx and return updated list."""
    if request.method == "POST":
        task = Task()
        task.user = request.user
        # The filter in force sets the date: today's view gives today,
        # tomorrow's gives tomorrow, and the rest give none
        task.due_date = default_due_date(current_filter(request), date.today())
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
    task = get_object_or_404(Task, pk=id, user=request.user)
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

        # Form validation failed - re-render form with errors, the
        # notifications following the due date and time as posted
        timing = _timing(task, request.POST)

    else:
        timing = None
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
    } | _reminders_context(task, timing)
    return render(request, "tasks/modal-form.html", context)


def _timing(task, data):
    """Whether the task has a due date and a due time as the dialog now has
    them, when the request carries its fields, else as saved."""
    return dialog_timing(data, task, "due_date", "due_time")


def _reminders_context(task, timing=None, reminder_form=None):
    """The Notifications section of the task form (components/reminders.html).
    A task needs a due date before it can have one. The section follows
    the dialog's due date and time: ``timing`` is theirs as (dated, timed),
    or None for the task's as saved."""
    dated, timed = timing or _timing(task, {})
    task_reminders = list(task.reminders.all())
    for reminder in task_reminders:
        reminder.delete_url = reverse(
            "tasks-reminder-delete", args=[task.id, reminder.id]
        )
    if dated:
        form = reminder_form or TaskReminderForm(task=task, timed=timed)
        note = ""
    else:
        form = None
        note = "Set a due date to add notifications."
    return {
        "reminders": task_reminders,
        "reminder_form": form,
        "reminder_add_url": reverse("tasks-reminder-add", args=[task.id]),
        "reminders_note": note,
    } | follow_fields(
        reverse("tasks-reminders", args=[task.id]), "id_due_date", "id_due_time"
    )


@login_required
def reminders_section(request, id):
    """The Notifications section again, for the due date and time the dialog
    now has (a change to either fetches it)."""
    task = get_object_or_404(Task, pk=id, user=request.user)
    context = _reminders_context(task, _timing(task, request.GET))
    return render(request, "components/reminders.html", context)


@login_required
@require_POST
def reminder_add(request, id):
    """Add a notification to the task and re-render the section. It is
    measured against the due date and time the dialog has, so one in
    minutes goes on a task whose time is typed but not yet saved."""
    task = get_object_or_404(Task, pk=id, user=request.user)
    dated, timed = timing = _timing(task, request.POST)
    form = TaskReminderForm(request.POST, task=task, timed=timed)
    if dated and form.is_valid():
        data = form.cleaned_data
        reminders.add_reminder(
            task, data["amount"], data["unit"], data["time"], data["channel"]
        )
        form = None
    context = _reminders_context(task, timing, form)
    return render(request, "components/reminders.html", context)


@login_required
@require_http_methods(["POST", "DELETE"])
def reminder_delete(request, id, reminder_id):
    """Remove a notification from the task and re-render the section."""
    task = get_object_or_404(Task, pk=id, user=request.user)
    reminders.remove_reminder(task, reminder_id)
    context = _reminders_context(task, _timing(task, request.POST))
    return render(request, "components/reminders.html", context)


def complete_task(task, user):
    """Mark a task done and bring on a recurring task's next instance. A
    done task stays in its list, checked and struck through, until the
    buttons under the list archive or delete it."""
    task.status = 1
    task.completed_date = date.today()
    task.save()
    recurring.after_completion(task)


@login_required
@require_POST
def done_htmx(request, id):
    """Mark a task done from its box on the calendar, which shows only open
    tasks. Unlike the list's toggle it only ever completes: a second press,
    from a grid not yet redrawn, leaves the task done."""
    task = get_object_or_404(Task, pk=id, user=request.user)
    if task.status != 1:
        complete_task(task, request.user)
    return HttpResponse(status=204, headers={"HX-Trigger": "tasksChanged"})


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
    task = get_object_or_404(Task, pk=id, user=request.user)
    if task.status == 1:
        task.status = 0
        task.completed_date = None
        task.save()
    else:
        task.status = 1
        task.completed_date = date.today()
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
    task = get_object_or_404(Task, pk=id, user=request.user)
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
