import time

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import CreateView

from . import throttle, totp
from .forms import CustomUserCreationForm
from .models import CustomUser

# How long the second step waits for its code before the password has to
# be given again
PENDING_FOR = 5 * 60


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
    cooldown (accounts.throttle). A user with an authenticator app goes on
    to give a code from it (VerifyCodeView) before being signed in."""

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
        next_url = _safe_next_url(
            request, request.POST.get("next") or request.GET.get("next", "")
        )
        if user.totp_secret:
            # The password is right, but the slate isn't cleared until the
            # code is too: wrong codes count against the same cooldown
            request.session["pending_user_id"] = user.pk
            request.session["pending_since"] = time.time()
            request.session["login_next_url"] = next_url
            return redirect("login-verify")

        throttle.record_success(username)
        login(request, user)
        return redirect(next_url or settings.LOGIN_REDIRECT_URL)

    def _cooling(self, request, wait):
        form = AuthenticationForm(initial={"username": request.POST.get("username")})
        error = f"Too many attempts. Try again in {throttle.describe(wait)}."
        return render(request, self.template_name, {"form": form, "error": error})


def _pending_user(request):
    """The user who has given their password and owes a code, if the wait
    for it hasn't run out."""
    user_id = request.session.get("pending_user_id")
    since = request.session.get("pending_since", 0)
    if not user_id or time.time() - since > PENDING_FOR:
        return None
    return CustomUser.objects.filter(pk=user_id).exclude(totp_secret="").first()


def _forget_pending(request):
    for key in ("pending_user_id", "pending_since", "login_next_url"):
        request.session.pop(key, None)


class VerifyCodeView(View):
    """The second step: a code from the authenticator app (or a recovery
    code), under the same cooldown as the password."""

    template_name = "registration/verify_code.html"

    def get(self, request):
        if _pending_user(request) is None:
            _forget_pending(request)
            return redirect("login")
        return render(request, self.template_name)

    def post(self, request):
        user = _pending_user(request)
        if user is None:
            _forget_pending(request)
            return redirect("login")

        wait = throttle.cooldown_remaining(user.username)
        if wait:
            return self._cooling(request, wait)

        if not totp.accept(user, request.POST.get("code", "")):
            wait = throttle.record_failure(user.username)
            if wait:
                return self._cooling(request, wait)
            return render(
                request, self.template_name, {"error": "That code didn't work."}
            )

        throttle.record_success(user.username)
        next_url = request.session.get("login_next_url", "")
        _forget_pending(request)
        login(request, user)
        return redirect(next_url or settings.LOGIN_REDIRECT_URL)

    def _cooling(self, request, wait):
        # Past the free attempts the password has to be given again, after
        # the wait
        _forget_pending(request)
        error = f"Too many attempts. Try again in {throttle.describe(wait)}."
        return render(request, self.template_name, {"error": error, "ended": True})
