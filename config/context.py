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
    "matcha-mist": "matcha",
    "hojicha-steam": "hojicha",
}


def theme(request):
    if hasattr(request, "session") and "theme" in request.session:
        name = request.session["theme"]
    elif hasattr(request, "user") and request.user.is_authenticated:
        name = request.user.theme
    else:
        name = ""
    return {
        "theme": name,
        "theme_base": THEME_VARIANTS.get(name, name),
        "theme_variant": name in THEME_VARIANTS,
    }
