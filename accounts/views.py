from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import CreateView

from . import throttle
from .forms import CustomUserCreationForm


class SignUpView(CreateView):
    form_class = CustomUserCreationForm
    success_url = reverse_lazy("login")
    template_name = "registration/signup.html"


def _safe_next_url(request, url):
    """Return ``url`` only if it stays on this site; otherwise ''. The value
    comes from the query string, so an unchecked redirect would let a crafted
    sign-in link bounce the user to another site."""
    if url and url_has_allowed_host_and_scheme(
        url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return url
    return ""


def admin_login(request):
    """Send the admin's sign-in to the site's own, so the admin gets the same
    cooldown (and second step) rather than its own password-only form."""
    next_url = _safe_next_url(request, request.GET.get("next", ""))
    return redirect_to_login(
        next_url or reverse("admin:index"), login_url=reverse("login")
    )


class LoginView(View):
    """Sign in with a username and password, under the failed-attempt
    cooldown (accounts.throttle)."""

    template_name = "registration/login.html"

    def get(self, request):
        if request.user.is_authenticated:
            return redirect(settings.LOGIN_REDIRECT_URL)
        return render(request, self.template_name, {"form": AuthenticationForm()})

    def post(self, request):
        username = request.POST.get("username", "")
        wait = throttle.cooldown_remaining(username)
        if wait:
            # While the wait runs no password is checked, so guessing through
            # it learns nothing
            return self._cooling(request, wait)

        form = AuthenticationForm(request, data=request.POST)
        if not form.is_valid():
            wait = throttle.record_failure(username)
            if wait:
                return self._cooling(request, wait)
            return render(request, self.template_name, {"form": form})

        user = form.get_user()
        throttle.record_success(username)
        next_url = _safe_next_url(
            request, request.POST.get("next") or request.GET.get("next", "")
        )
        login(request, user)
        return redirect(next_url or settings.LOGIN_REDIRECT_URL)

    def _cooling(self, request, wait):
        form = AuthenticationForm(initial={"username": request.POST.get("username")})
        error = f"Too many attempts. Try again in {throttle.describe(wait)}."
        return render(request, self.template_name, {"form": form, "error": error})
