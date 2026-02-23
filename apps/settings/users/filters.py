import django_filters

from accounts.models import CustomUser


class UserFilter(django_filters.FilterSet):
    username = django_filters.CharFilter(lookup_expr="icontains")
    email = django_filters.CharFilter(lookup_expr="icontains")
    role = django_filters.ChoiceFilter(
        choices=CustomUser.ROLE_OPTIONS,
        empty_label="All",
    )
    is_active = django_filters.ChoiceFilter(
        choices=(("True", "Active"), ("False", "Inactive")),
        empty_label="All",
        method="filter_is_active",
    )

    class Meta:
        model = CustomUser
        fields = ["username", "email", "role", "is_active"]

    def filter_is_active(self, queryset, name, value):
        if value == "True":
            return queryset.filter(is_active=True)
        elif value == "False":
            return queryset.filter(is_active=False)
        return queryset
