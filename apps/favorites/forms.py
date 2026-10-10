from django import forms

from config.settings import CustomFormRenderer

from .models import Favorite

# The longest name a favorite can have: the width of its column. The
# extension popup trims a page title to it, so the form never opens with a
# name it cannot save.
NAME_LENGTH = Favorite._meta.get_field("name").max_length


class FavoriteFormBase(forms.ModelForm):
    """What every favorite form checks. Each text field may be as long as
    its column, no matter which form it comes in by, so a favorite saved
    from the extension popup can be edited on the favorites page. Only the
    wording of the too-long messages is ours."""

    default_renderer = CustomFormRenderer

    class Meta:
        # The model is named by each form's Meta, which lists its fields
        error_messages = {
            "name": {"max_length": "Name can be up to %(limit_value)d characters"},
            "url": {"max_length": "URL can be up to %(limit_value)d characters"},
            "description": {
                "max_length": "Description can be up to %(limit_value)d characters"
            },
        }


class FavoriteExtensionForm(FavoriteFormBase):
    """The form in the browser extension's popup."""

    class Meta(FavoriteFormBase.Meta):
        model = Favorite
        fields = ("folder", "name", "url")


class FavoriteForm(FavoriteFormBase):
    """The form on the favorites page, and in its modal."""

    use_required_attribute = False

    class Meta(FavoriteFormBase.Meta):
        model = Favorite
        fields = ("folder", "name", "url", "description")
        widgets = {
            "name": forms.TextInput(attrs={"class": "span2"}),
            "url": forms.TextInput(attrs={"class": "span2"}),
            "description": forms.Textarea(attrs={"class": "span2"}),
        }

    def __iter__(self):
        for field in super().__iter__():
            if field.name != "folder":
                yield field
