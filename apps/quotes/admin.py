from django.contrib import admin

from apps.quotes.models import Quote


@admin.register(Quote)
class QuoteAdmin(admin.ModelAdmin):
    list_display = ("text", "author", "user", "always", "position")
    list_filter = ("always",)
    search_fields = ("text", "author")
