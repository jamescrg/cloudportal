import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

import apps.contacts.google as google
from apps.contacts.forms import ContactForm
from apps.contacts.models import Contact
from apps.folders.folders import get_folders_for_page, select_folder
from apps.management.pagination import CustomPaginator


def _get_contacts_context(request):
    """Helper to build context for contacts partials."""
    user = request.user
    selected_folder = select_folder(request, "contacts")
    contacts_folder_all = request.session.get("contacts_all", False)

    if contacts_folder_all:
        contacts = Contact.objects.filter(user=user)
    elif selected_folder:
        contacts = Contact.objects.filter(user=user, folder=selected_folder)
    else:
        contacts = Contact.objects.filter(user=user, folder_id__isnull=True)

    contacts = contacts.order_by("name")

    session_key = "contacts_page"
    trigger_key = "contactsChanged"
    pagination = CustomPaginator(contacts, 20, request, session_key)

    selected_contact_id = user.contacts_contact
    try:
        selected_contact = Contact.objects.filter(pk=selected_contact_id).get()
    except ObjectDoesNotExist:
        selected_contact = None

    google_enabled = bool(user.google_credentials)

    base_count_qs = Contact.objects.filter(user=user)

    return {
        "page": "contacts",
        "contacts": pagination.get_object_list(),
        "selected_contact": selected_contact,
        "selected_folder": selected_folder,
        "contacts_folder_all": contacts_folder_all,
        "google": google_enabled,
        "pagination": pagination,
        "session_key": session_key,
        "trigger_key": trigger_key,
        "all_count": base_count_qs.count(),
        "inbox_count": base_count_qs.filter(folder__isnull=True).count(),
    }


@login_required
def index(request):
    """Display a list of folders and contacts, along with a contact.

    Notes:
        Always displays folders.
        If a folder is selected, displays the contacts for a folder.
        If a contact is selected, displays the contact.

    """

    context = {
        "edit": False,
        "folders": get_folders_for_page(request, "contacts"),
    } | _get_contacts_context(request)

    return render(request, "contacts/content.html", context)


@login_required
def select(request, id):
    """Select a contact for display, redirect to index.

    Args:
        id (int): a Contact instance id

    """

    user = request.user
    user.contacts_contact = id

    # Switch to the contact's folder
    try:
        contact = Contact.objects.get(pk=id, user=user)
        user.contacts_folder = contact.folder_id or 0
    except Contact.DoesNotExist:
        pass

    user.save()
    return redirect("/contacts/")


@login_required
def add(request):
    """Add a new contact.

    Notes:
        GET: Display new contact form.
        POST: Add contact to database.

    """

    # load initial page values (user, folders, selected folder)
    user = request.user
    folders = get_folders_for_page(request, "contacts")

    selected_folder = select_folder(request, "contacts")

    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = ContactForm(request.POST)
        if form.is_valid():
            # initialize contact data
            contact = form.save(commit=False)
            contact.user = user

            # save contact to database
            contact.save()

            # deselect previously selected contact, if one exists
            try:
                old = Contact.objects.filter(user=user, selected=1).get()
            except Contact.DoesNotExist:
                pass
            else:
                old.selected = 0
                old.save()

            # select newest contact for user
            new = Contact.objects.filter(user=user).latest("id")
            new.selected = 1
            new.save()

            return redirect("contacts")

    # if no post data has been submitted, show the contact form
    else:
        if selected_folder:
            form = ContactForm(initial={"folder": selected_folder.id})
        else:
            form = ContactForm()

    form.fields["folder"].queryset = get_folders_for_page(request, "contacts")

    context = {
        "page": "contacts",
        "edit": False,
        "add": True,
        "action": "/contacts/add",
        "folders": folders,
        "form": form,
        "phone_labels": ["Mobile", "Home", "Work", "Fax", "Other"],
    }

    return render(request, "contacts/content.html", context)


@login_required
def edit(request, id):
    """Edit a contact.

    Args:
        id (int): A Contact instance id

    Notes:
        GET: Display contact form.
        POST: Update contact in database.

    """

    user = request.user
    folders = get_folders_for_page(request, "contacts")

    selected_folder = select_folder(request, "contacts")

    contact = get_object_or_404(Contact, pk=id)

    if request.method == "POST":
        try:
            contact = Contact.objects.filter(user=user, pk=id).get()
        except ObjectDoesNotExist:
            raise Http404("Record not found.")

        form = ContactForm(request.POST, instance=contact)
        form.fields["folder"].queryset = get_folders_for_page(request, "contacts")

        if form.is_valid():
            contact = form.save(commit=False)
            contact.user = user

            if user.google_credentials and contact.google_id:
                google.delete_contact(contact)
                contact.google_id = google.add_contact(contact)

            contact.save()

            return redirect("contacts")

    else:
        if selected_folder:
            form = ContactForm(instance=contact, initial={"folder": selected_folder.id})
        else:
            form = ContactForm(instance=contact)

    form.fields["folder"].queryset = get_folders_for_page(request, "contacts")

    context = {
        "page": "contacts",
        "edit": True,
        "add": False,
        "action": f"/contacts/{id}/edit",
        "folders": folders,
        "selected_folder": selected_folder,
        "contact": contact,
        "form": form,
    }

    return render(request, "contacts/content.html", context)


@login_required
def delete(request, id):
    """Delete a contact.

    Args:
        id (int):  a Contact instance id

    """

    try:
        contact = Contact.objects.filter(user=request.user, pk=id).get()
    except ObjectDoesNotExist:
        raise Http404("Record not found.")
    if contact.google_id:
        google.delete_contact(contact)
    contact.delete()
    return redirect("contacts")


@login_required
def google_toggle(request, id):
    """Add a contact to Google account, update the contact with its google_id.

    Args:
        id (int): a Contact instance id

    Notes:
        Invoked by a link under the contact,
        which is displayed if the contact does not have a google_id.

    """

    contact = get_object_or_404(Contact, pk=id)
    if contact.google_id:
        google.delete_contact(contact)
        contact.google_id = ""
    else:
        contact.google_id = google.add_contact(contact)

    contact.save()
    return redirect("contacts")


@login_required
def google_list(request):

    contacts = Contact.objects.all()
    # for contact in contacts:
    #     contact.google_id = ""
    #     contact.save()

    context = {
        "page": "contacts",
        "contacts": contacts,
    }

    return render(request, "contacts/google.html", context)


# HTMX Views


@login_required
def contacts_all(request):
    """Select 'All' folder view and return updated contacts with folders OOB."""
    request.session["contacts_all"] = True
    request.user.contacts_folder = 0
    request.user.save()
    context = _get_contacts_context(request)
    return render(request, "contacts/contacts-with-folders-oob.html", context)


@login_required
def contacts_list_htmx(request):
    """Return contacts list partial for htmx."""
    context = _get_contacts_context(request)
    return render(request, "contacts/list.html", context)


@login_required
def contact_detail_htmx(request):
    """Return contact detail partial for htmx."""
    context = _get_contacts_context(request)
    if context["selected_contact"]:
        return render(request, "contacts/contact.html", context)
    return HttpResponse("")


@login_required
def select_htmx(request, id):
    """Select contact via htmx, return detail + updated list (oob)."""
    user = request.user
    user.contacts_contact = id
    user.save()

    context = _get_contacts_context(request)
    return render(request, "contacts/contact-with-list-oob.html", context)


@login_required
def contacts_form_htmx(request, id=None):
    """Return contact form in modal for htmx, or process form submission."""
    user = request.user
    contact = None

    if id:
        try:
            contact = Contact.objects.filter(user=user, pk=id).get()
        except ObjectDoesNotExist:
            raise Http404("Record not found.")

    if request.method == "POST":
        if contact:
            form = ContactForm(request.POST, instance=contact)
        else:
            form = ContactForm(request.POST)

        form.fields["folder"].queryset = get_folders_for_page(request, "contacts")

        if form.is_valid():
            saved_contact = form.save(commit=False)
            saved_contact.user = user
            saved_contact.save()

            # Handle Google sync for edits
            if contact and user.google_credentials and saved_contact.google_id:
                google.delete_contact(saved_contact)
                saved_contact.google_id = google.add_contact(saved_contact)
                saved_contact.save()

            # Select the saved contact and switch to its folder
            user.contacts_contact = saved_contact.id
            user.contacts_folder = saved_contact.folder_id or 0
            user.save()

            return HttpResponse(
                status=204,
                headers={
                    "HX-Trigger": json.dumps(
                        {
                            "contactsChanged": "",
                            "contactDetailChanged": "",
                            "foldersChanged": "",
                        }
                    )
                },
            )
    else:
        if contact:
            form = ContactForm(instance=contact, use_required_attribute=False)
        else:
            form = ContactForm(use_required_attribute=False)

    context = {
        "page": "contacts",
        "edit": id is not None,
        "contact": contact,
        "form": form,
        "action": f"/contacts/{id}/form-htmx" if id else "/contacts/form-htmx",
        "folders": get_folders_for_page(request, "contacts"),
        "selected_folder_id": user.contacts_folder,
    }

    return render(request, "contacts/modal-form.html", context)


@login_required
def delete_htmx(request, id):
    """Delete contact via htmx."""
    user = request.user

    try:
        contact = Contact.objects.filter(user=user, pk=id).get()
    except ObjectDoesNotExist:
        raise Http404("Record not found.")

    if contact.google_id:
        google.delete_contact(contact)
    contact.delete()

    # Clear selected contact
    user.contacts_contact = 0
    user.save()

    return HttpResponse(
        status=204,
        headers={
            "HX-Trigger": json.dumps(
                {"contactsChanged": "", "contactDetailChanged": ""}
            )
        },
    )


@login_required
def google_toggle_htmx(request, id):
    """Toggle Google sync for contact via htmx."""
    user = request.user
    contact = get_object_or_404(Contact, pk=id, user=user)

    if contact.google_id:
        google.delete_contact(contact)
        contact.google_id = ""
    else:
        contact.google_id = google.add_contact(contact)

    contact.save()

    return HttpResponse(
        status=204,
        headers={
            "HX-Trigger": json.dumps(
                {"contactsChanged": "", "contactDetailChanged": ""}
            )
        },
    )
