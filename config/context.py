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
# shared atmosphere (static/css/atmosphere.css) and its own file on top.
# Auto's follows the device, as Auto does: Matcha Lavender in the light,
# Hojicha Steam in the dark (base.html loads both, each behind a media
# condition).
THEME_VARIANTS = {
    "matcha-lavender": "matcha",
    "hojicha-steam": "hojicha",
    "auto-atmosphere": "auto",
}

# The same the other way about: the atmospheric variant of each base theme
VARIANT_OF = {base: variant for variant, base in THEME_VARIANTS.items()}

# A device with nothing chosen: Auto, with the atmosphere
DEFAULT_THEME = "auto-atmosphere"

# Every theme a user may choose
THEMES = {"matcha", "hojicha", "auto", *THEME_VARIANTS}

# Renamed themes, so a session still holding the old name keeps its theme

RENAMED_THEMES = {
    "matcha-mist": "matcha-lavender",
}


def theme(request):
    """The theme is chosen per device, so it lives in the session alone.
    Nothing chosen (a new device, or one just signed in) follows the
    device, light or dark as it is set, with the atmosphere on."""
    name = request.session.get("theme", "") if hasattr(request, "session") else ""
    name = RENAMED_THEMES.get(name, name) or DEFAULT_THEME
    return {
        "theme": name,
        "theme_base": THEME_VARIANTS.get(name, name),
        "theme_variant": name in THEME_VARIANTS,
    }
