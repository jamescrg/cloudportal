from django import forms

from accounts.models import CustomUser
from config.settings import CustomFormRenderer


class UserForm(forms.ModelForm):
    default_renderer = CustomFormRenderer
    is_active = forms.ChoiceField(
        choices=[("True", "Active"), ("False", "Inactive")],
        label="Status",
    )

    class Meta:
        model = CustomUser
        fields = ["username", "email", "first_name", "last_name", "role", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["is_active"].initial = str(self.instance.is_active)

    def clean_is_active(self):
        return self.cleaned_data["is_active"] == "True"


class CreateUserForm(forms.ModelForm):
    default_renderer = CustomFormRenderer
    password = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = CustomUser
        fields = ["username", "password", "first_name", "last_name", "email", "role"]

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user
