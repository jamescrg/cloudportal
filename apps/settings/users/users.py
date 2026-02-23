from accounts.models import CustomUser
from apps.management.pagination import CustomPaginator
from apps.settings.users.filters import UserFilter

DEFAULT_USER_FILTER = {"is_active": "True"}


def get_user_list(request):
    queryset = CustomUser.objects.all()

    filter_data = request.session.get("users_filter", DEFAULT_USER_FILTER)
    user_filter = UserFilter(filter_data, queryset=queryset)
    users = user_filter.qs

    current_order = filter_data.get("sort", "username")
    valid_sorts = (
        "username",
        "-username",
        "email",
        "-email",
        "role",
        "-role",
        "is_active",
        "-is_active",
    )
    if current_order in valid_sorts:
        users = users.order_by(current_order)
    else:
        users = users.order_by("username")

    session_key = "users_page"
    trigger_key = "userListReload"
    pagination = CustomPaginator(users, 10, request, session_key)

    return {
        "subapp": "users",
        "users": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": session_key,
        "trigger_key": trigger_key,
        "current_order": current_order,
    }
