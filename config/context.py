from . import settings


def env(request):
    return {
        "env": settings.ENV,
    }


def site_handle(request):
    return {
        "site_handle": settings.SITE_NAME,
    }


# The atmospheric variants: each is its base theme's colours, with the
# shared atmosphere (static/css/atmosphere.css) and its own file on top
THEME_VARIANTS = {
    "matcha-lavender": "matcha",
    "hojicha-steam": "hojicha",
}

# Renamed themes, so a session still holding the old name keeps its theme
# Every theme a user may choose
THEMES = {"matcha", "hojicha", "auto", *THEME_VARIANTS}

RENAMED_THEMES = {
    "matcha-mist": "matcha-lavender",
}


def theme(request):
    """The theme is chosen per device, so it lives in the session alone.
    Nothing chosen (a new device, or one just signed in) follows the
    device: light or dark as it is set."""
    name = request.session.get("theme", "") if hasattr(request, "session") else ""
    name = RENAMED_THEMES.get(name, name) or "auto"
    return {
        "theme": name,
        "theme_base": THEME_VARIANTS.get(name, name),
        "theme_variant": name in THEME_VARIANTS,
    }
