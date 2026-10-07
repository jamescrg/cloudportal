import os

from django import template
from django.conf import settings

register = template.Library()


@register.simple_tag
def static_v(file_name):
    """A way to force the client browser to reload a changed static file.
    Normally the client browser will cache a static file and not reload until it's expired.
    This just appends "?v=modification_date" to the url of the file to make the browser think it's a different file.
    Inspired by this SO thread:
    http://stackoverflow.com/questions/118884/how-to-force-browser-to-reload-cached-css-js-files
    """

    # Gets the static file from the /static directory
    static_file = settings.STATIC_URL + file_name
    modified_url = (
        static_file
        + "?v="
        + str(os.path.getmtime(str(settings.BASE_DIR) + static_file))
    )

    return modified_url


@register.simple_tag(takes_context=True)
def static_v_page(context):
    """A way to force the client browser to reload a changed static file.
    Normally the client browser will cache a static file and not reload until it's expired.
    This just appends "?v=modification_date" to the url of the file to make the browser think it's a different file.
    Inspired by this SO thread:
    http://stackoverflow.com/questions/118884/how-to-force-browser-to-reload-cached-css-js-files
    """

    # Gets the static file from the /static directory
    static_file = f"{settings.STATIC_URL}css/app-{context["page"]}.css"
    modified_url = (
        static_file
        + "?v="
        + str(os.path.getmtime(str(settings.BASE_DIR) + static_file))
    )

    return modified_url


@register.simple_tag(takes_context=True)
def static_v_theme(context, name=None):
    """A way to force the client browser to reload a changed static file.
    Normally the client browser will cache a static file and not reload until it's expired.
    This just appends "?v=modification_date" to the url of the file to make the browser think it's a different file.
    Inspired by this SO thread:
    http://stackoverflow.com/questions/118884/how-to-force-browser-to-reload-cached-css-js-files
    """

    # Gets the static file from the /static directory; a variant theme
    # names its base theme's file, or its own
    static_file = f"{settings.STATIC_URL}css/theme-{name or context["theme"]}.css"
    modified_url = (
        static_file
        + "?v="
        + str(os.path.getmtime(str(settings.BASE_DIR) + static_file))
    )

    return modified_url
