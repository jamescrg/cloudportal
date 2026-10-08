from django import forms

from apps.quotes.models import Quote


class QuoteForm(forms.ModelForm):
    class Meta:
        model = Quote
        fields = ["text", "author", "always"]
        labels = {"text": "Quote", "author": "Author", "always": "Show every day"}
        widgets = {
            "text": forms.Textarea(attrs={"rows": 3}),
        }
