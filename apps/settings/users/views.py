from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from accounts.models import CustomUser
from apps.settings.users.filters import UserFilter
from apps.settings.users.forms import CreateUserForm, UserForm
from apps.settings.users.users import DEFAULT_USER_FILTER, get_user_list


@login_required
def users_index(request):
    context = {"page": "settings"}
    context.update(get_user_list(request))
    return render(request, "settings/users/index.html", context)


@login_required
def user_list(request):
    context = {"page": "settings"}
    context.update(get_user_list(request))
    return render(request, "settings/users/user-table.html", context)


@login_required
def user_filter(request):
    if request.method == "POST":
        filter_data = {
            k: v for k, v in request.POST.items() if k != "csrfmiddlewaretoken"
        }
        request.session["users_filter"] = filter_data
        return HttpResponse(status=204, headers={"HX-Trigger": "userListReload"})

    filter_data = request.session.get("users_filter", DEFAULT_USER_FILTER)
    user_filter = UserFilter(filter_data)
    return render(request, "settings/users/filter.html", {"filter": user_filter})


@login_required
def user_sort(request, order):
    filter_data = request.session.get("users_filter", DEFAULT_USER_FILTER)
    current_sort = filter_data.get("sort", "username")

    if current_sort == order:
        new_sort = f"-{order}"
    elif current_sort == f"-{order}":
        new_sort = order
    else:
        new_sort = order

    filter_data["sort"] = new_sort
    request.session["users_filter"] = filter_data
    request.session["users_page"] = 1
    request.session.modified = True

    return HttpResponse(status=204, headers={"HX-Trigger": "userListReload"})


@login_required
def change_role(request, user_id, role):
    user = get_object_or_404(CustomUser, pk=user_id)
    if role in ("ADMIN", "USER"):
        user.role = role
        user.save(update_fields=["role"])
    return HttpResponse(status=204, headers={"HX-Trigger": "userListReload"})


@login_required
def switch_status(request, user_id):
    user = get_object_or_404(CustomUser, pk=user_id)
    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    return HttpResponse(status=204, headers={"HX-Trigger": "userListReload"})


@login_required
def add_user(request):
    if request.method == "POST":
        form = CreateUserForm(request.POST)
        if form.is_valid():
            form.save()
            return HttpResponse(status=204, headers={"HX-Trigger": "userListReload"})
    else:
        form = CreateUserForm()

    return render(request, "settings/users/new-user.html", {"form": form})


@login_required
def edit_user(request, user_id):
    user = get_object_or_404(CustomUser, pk=user_id)

    if request.method == "POST":
        form = UserForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            return HttpResponse(status=204, headers={"HX-Trigger": "userListReload"})
    else:
        form = UserForm(instance=user)

    return render(
        request, "settings/users/form.html", {"form": form, "edit_user": user}
    )
