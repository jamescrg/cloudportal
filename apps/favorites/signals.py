from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.favorites import site_icons
from apps.favorites.models import Favorite


@receiver(post_save, sender=Favorite)
def fetch_site_icon(sender, instance, **kwargs):
    """A saved favorite's host gets its icon fetched, if it hasn't one."""
    site_icons.ensure(site_icons.host_of(instance.url))
