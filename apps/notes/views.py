import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.folders.folders import get_folders_for_page, select_folder
from apps.management.pagination import CustomPaginator

from .forms import NoteForm
from .models import Note

NOTES_ALLOWED_ORDER_FIELDS = {"title", "created_at", "updated_at"}


def _get_notes_list_context(request):
    """Helper to build context for notes list partial."""
    user = request.user
    selected_folder = select_folder(request, "notes")
    notes_folder_all = request.session.get("notes_all", False)

    queryset = Note.objects.filter(user=user)

    if notes_folder_all:
        pass  # show all notes
    elif selected_folder:
        queryset = queryset.filter(folder_id=selected_folder.id)
    else:
        queryset = queryset.filter(folder_id__isnull=True)

    # Keyword filter
    filter_data = request.session.get("notes_filter", {})
    keyword = filter_data.get("keyword", "")
    if keyword:
        queryset = queryset.filter(title__icontains=keyword)

    # Ordering
    current_order = filter_data.get("order_by", "-updated_at")
    bare_field = current_order.lstrip("-")
    if bare_field not in NOTES_ALLOWED_ORDER_FIELDS:
        current_order = "-updated_at"
        bare_field = "updated_at"
    queryset = queryset.order_by(current_order)

    # Folders for sidebar
    folders = get_folders_for_page(request, "notes")

    session_key = "notes_page"
    trigger_key = "notesChanged"
    pagination = CustomPaginator(queryset, 20, request, session_key)

    base_count_qs = Note.objects.filter(user=user)

    return {
        "page": "notes",
        "notes": pagination.get_object_list(),
        "number_notes": queryset.count(),
        "current_order": bare_field,
        "keyword": keyword,
        "selected_folder": selected_folder,
        "notes_folder_all": notes_folder_all,
        "folders": folders,
        "pagination": pagination,
        "session_key": session_key,
        "trigger_key": trigger_key,
        "all_count": base_count_qs.count(),
        "inbox_count": base_count_qs.filter(folder__isnull=True).count(),
    }


# =============================================================================
# List Views
# =============================================================================


@login_required
def notes_index(request):
    """Main notes list view."""
    context = _get_notes_list_context(request)
    return render(request, "notes/main.html", context)


@login_required
def notes_list(request):
    """HTMX partial for notes card (used by notesChanged)."""
    context = _get_notes_list_context(request)
    return render(request, "notes/list.html", context)


@login_required
def notes_all(request):
    """Select 'All' folder view and return updated notes with folders OOB."""
    request.session["notes_all"] = True
    request.user.notes_folder = 0
    request.user.save()
    context = _get_notes_list_context(request)
    return render(request, "notes/notes-with-folders-oob.html", context)


@login_required
def notes_add(request):
    """Add a new note via modal."""
    if request.method == "POST":
        form = NoteForm(request.POST, request=request, use_required_attribute=False)
        if form.is_valid():
            note = form.save(commit=False)
            note.user = request.user
            note.save()

            note_url = reverse("notes:note-view", args=[note.id])
            return HttpResponse(
                f'<script>window.location.href = "{note_url}";</script>',
                headers={"HX-Trigger": "notesChanged"},
            )
    else:
        form = NoteForm(request=request, use_required_attribute=False)

    context = {
        "page": "notes",
        "form": form,
        "action": "Add",
        "folders": get_folders_for_page(request, "notes"),
        "selected_folder_id": request.user.notes_folder,
    }
    return render(request, "notes/form.html", context)


@login_required
def notes_order_by(request, order):
    """Sort notes by field."""
    filter_data = request.session.get("notes_filter", {})

    current_order = filter_data.get("order_by", "")
    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["notes_filter"] = filter_data
    request.session["notes_page"] = 1
    request.session.modified = True

    return redirect("notes:list")


@login_required
def notes_filter_keyword(request):
    """Filter notes by keyword."""
    filter_data = request.session.get("notes_filter", {})
    keyword = request.GET.get("keyword", "").strip()

    if keyword:
        filter_data["keyword"] = keyword
    else:
        filter_data.pop("keyword", None)

    request.session["notes_filter"] = filter_data
    request.session["notes_page"] = 1
    request.session.modified = True

    context = _get_notes_list_context(request)
    return render(request, "notes/table.html", context)


# =============================================================================
# Editor Views
# =============================================================================


@login_required
def note_view(request, note_id):
    """Editor view for a note."""
    note = get_object_or_404(Note, pk=note_id, user=request.user)
    context = {
        "page": "notes",
        "note": note,
    }
    return render(request, "notes/editor.html", context)


@login_required
def note_edit(request, note_id):
    """Edit note metadata (title + folder)."""
    note = get_object_or_404(Note, pk=note_id, user=request.user)

    if request.method == "POST":
        form = NoteForm(
            request.POST, instance=note, request=request, use_required_attribute=False
        )
        if form.is_valid():
            form.save()
            return HttpResponse(status=204, headers={"HX-Trigger": "notesChanged"})
    else:
        form = NoteForm(instance=note, request=request, use_required_attribute=False)

    context = {
        "page": "notes",
        "note": note,
        "form": form,
        "action": "Edit",
        "folders": get_folders_for_page(request, "notes"),
    }
    return render(request, "notes/form.html", context)


@login_required
@require_POST
def note_delete(request, note_id):
    """Delete a note."""
    note = get_object_or_404(Note, pk=note_id, user=request.user)
    note.delete()
    return HttpResponse(status=204, headers={"HX-Trigger": "notesChanged"})


@login_required
@require_POST
def note_autosave(request, note_id):
    """Autosave endpoint for the editor."""
    note = get_object_or_404(Note, pk=note_id, user=request.user)

    content = request.POST.get("content", "")
    note.content = content
    update_fields = ["content", "updated_at"]

    is_encrypted = request.POST.get("is_encrypted")
    if is_encrypted is not None:
        note.is_encrypted = is_encrypted == "true"
        update_fields.append("is_encrypted")

    note.save(update_fields=update_fields)

    return JsonResponse({"saved": True, "updated_at": note.updated_at.isoformat()})


@login_required
@require_POST
def note_title(request, note_id):
    """Update note title."""
    note = get_object_or_404(Note, pk=note_id, user=request.user)

    title = request.POST.get("title", "").strip()
    if title:
        note.title = title
        note.save(update_fields=["title", "updated_at"])
        return JsonResponse({"saved": True, "title": note.title})

    return JsonResponse({"saved": False, "error": "Title cannot be empty"}, status=400)


@login_required
def notes_shortcuts(request):
    """Show keyboard shortcuts modal."""
    return render(request, "notes/shortcuts-modal.html")


@login_required
def note_import_modal(request, note_id):
    """Show import markdown modal."""
    return render(request, "notes/import-modal.html")


@login_required
@require_POST
def notes_bulk_delete(request):
    """Bulk delete notes."""
    data = json.loads(request.body)
    note_ids = data.get("note_ids", [])
    Note.objects.filter(user=request.user, id__in=note_ids).delete()
    return HttpResponse(status=204, headers={"HX-Trigger": "notesChanged"})


@login_required
@require_POST
def notes_bulk_move_folder(request):
    """Bulk move notes to a folder."""
    data = json.loads(request.body)
    note_ids = data.get("note_ids", [])
    folder_id = data.get("folder_id")
    Note.objects.filter(user=request.user, id__in=note_ids).update(folder_id=folder_id)
    return HttpResponse(status=204, headers={"HX-Trigger": "notesChanged"})
