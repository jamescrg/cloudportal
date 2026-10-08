from django.contrib.auth.backends import ModelBackend

from .models import CustomUser


class EmailBackend(ModelBackend):
    """Sign in by email address, in any case. Only a call that passes
    ``email`` comes here (the sign-in form); one that passes a username
    goes on to Django's own backend, as code and tests that sign in
    directly still do."""

    def authenticate(self, request, email=None, password=None, **kwargs):
        if not email or password is None:
            return None
        user = CustomUser.objects.filter(email__iexact=email.strip()).first()
        if user is None:
            # Hash anyway, so an unknown address takes as long as a known one
            # and the timing doesn't tell which addresses have accounts
            CustomUser().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
