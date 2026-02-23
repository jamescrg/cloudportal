from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path

from apps.contacts import views as contacts
from apps.favorites import views as favorites
from apps.finance import views as finance
from apps.folders import views as folders
from apps.home import views as home
from apps.lab import views as lab
from apps.management.pagination import change_page
from apps.search import views as search
from apps.settings import views as settings
from apps.tasks import views as tasks
from apps.weather import views as weather

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "pagination/change-page/<str:session_key>/<str:trigger_key>/<int:page>/",
        change_page,
        name="change-page",
    ),
    path("accounts/", include("accounts.urls")),
    path("accounts/", include("django.contrib.auth.urls")),
    # folders
    path("folders/home/<int:id>/<str:page>", folders.home, name="folder-home"),
    path("folders/<int:id>/<str:page>", folders.select, name="folder-select"),
    path("folders/insert/<str:page>", folders.insert, name="folder-insert"),
    path("folders/update/<int:id>/<str:page>", folders.update, name="folder-update"),
    path("folders/delete/<int:id>/<str:page>", folders.delete, name="folder-delete"),
    path("folders/share/<int:id>/<str:page>", folders.share, name="folder-share"),
    # folders htmx
    path("folders/tree/", folders.folder_tree, name="folders-tree"),
    path("folders/form/<str:page>", folders.folder_form, name="folder-form"),
    path(
        "folders/form/<int:id>/<str:page>", folders.folder_form, name="folder-form-edit"
    ),
    path(
        "folders/<int:id>/<str:page>/select",
        folders.select_htmx,
        name="folder-select-htmx",
    ),
    path(
        "folders/<int:id>/<str:page>/home",
        folders.home_htmx,
        name="folder-home-htmx",
    ),
    path(
        "folders/<int:id>/<str:page>/delete",
        folders.delete_htmx,
        name="folder-delete-htmx",
    ),
    # home
    path("", home.index, name="home-index"),
    path("home/", home.index, name="home"),
    path("home/folder/<int:id>/<str:direction>/", home.folder, name="home-folder"),
    path(
        "home/favorite/<int:id>/<str:direction>/", home.favorite, name="home-favorite"
    ),
    path("home/toggle/<str:section>", home.toggle, name="home-toggle"),
    path(
        "home/update-folder-column/",
        home.update_folder_column,
        name="home-update-folder-column",
    ),
    path(
        "home/swap-folder-positions/",
        home.swap_folder_positions,
        name="home-swap-folder-positions",
    ),
    path(
        "home/insert-folder-at-position/",
        home.insert_folder_at_position,
        name="home-insert-folder-at-position",
    ),
    path(
        "home/swap-favorite-positions/",
        home.swap_favorite_positions,
        name="home-swap-favorite-positions",
    ),
    path(
        "home/reorder-favorites/",
        home.reorder_favorites,
        name="home-reorder-favorites",
    ),
    path(
        "home/insert-favorite-at-position/",
        home.insert_favorite_at_position,
        name="home-insert-favorite-at-position",
    ),
    path(
        "home/move-favorite-to-folder/",
        home.move_favorite_to_folder,
        name="home-move-favorite-to-folder",
    ),
    # favorites
    path("favorites/", favorites.index, name="favorites"),
    path("favorites/add", favorites.add, name="favorites-add"),
    path("favorites/<int:id>/edit", favorites.edit, name="favorites-edit"),
    path("favorites/delete/<int:id>", favorites.delete, name="favorites-delete"),
    path("favorites/home/<int:id>", favorites.home, name="favorites-home"),
    path("favorites/api/add", favorites.api_add, name="favorites-api-add"),
    path("favorites/api/folders", favorites.api_folders, name="favorites-api-folders"),
    path("favorites/extension", favorites.extension_add, name="favorites-extension"),
    # favorites htmx
    path("favorites/all/", favorites.favorites_all, name="favorites-all"),
    path("favorites/list/", favorites.favorites_list, name="favorites-list"),
    path(
        "favorites/filter/keyword/",
        favorites.favorites_filter_keyword,
        name="favorites-filter-keyword",
    ),
    path(
        "favorites/order-by/<str:order>/",
        favorites.favorites_order_by,
        name="favorites-order-by",
    ),
    path("favorites/form", favorites.favorites_form, name="favorites-form"),
    path(
        "favorites/<int:id>/form", favorites.favorites_form, name="favorites-form-edit"
    ),
    path(
        "favorites/<int:id>/delete-htmx",
        favorites.delete_htmx,
        name="favorites-delete-htmx",
    ),
    path(
        "favorites/<int:id>/home-htmx", favorites.home_htmx, name="favorites-home-htmx"
    ),
    path("favorites/bulk-delete/", favorites.bulk_delete, name="favorites-bulk-delete"),
    path(
        "favorites/bulk-move-folder/",
        favorites.bulk_move_folder,
        name="favorites-bulk-move-folder",
    ),
    # tasks
    path("tasks/", tasks.index, name="tasks"),
    path("tasks/add", tasks.add, name="tasks-add"),
    path("tasks/<int:id>/edit", tasks.edit, name="tasks-edit"),
    path("tasks/<int:id>/delete", tasks.delete, name="tasks-delete"),
    path("tasks/<int:id>/complete", tasks.status, name="tasks-complete"),
    path("tasks/<int:id>/complete/<str:origin>", tasks.status, name="tasks-complete"),
    path("tasks/clear", tasks.clear, name="tasks-clear"),
    # tasks htmx
    path("tasks/all/", tasks.tasks_all, name="tasks-all"),
    path("tasks/due/", tasks.tasks_due, name="tasks-due"),
    path("tasks/order-by/<str:order>/", tasks.tasks_order_by, name="tasks-order-by"),
    path("tasks/filter", tasks.task_filter, name="tasks-filter"),
    path(
        "tasks/filter/default", tasks.task_filter_default, name="tasks-filter-default"
    ),
    path("tasks/list/", tasks.task_list, name="tasks-list"),
    path("tasks/add-htmx", tasks.add_htmx, name="tasks-add-htmx"),
    path("tasks/<int:id>/form", tasks.task_form, name="tasks-form"),
    path("tasks/<int:id>/status", tasks.status_htmx, name="tasks-status"),
    path("tasks/<int:id>/priority", tasks.priority_htmx, name="tasks-priority"),
    path("tasks/<int:id>/delete-htmx", tasks.delete_htmx, name="tasks-delete-htmx"),
    path("tasks/bulk-status", tasks.bulk_status_htmx, name="tasks-bulk-status"),
    path("tasks/clear-htmx", tasks.clear_htmx, name="tasks-clear-htmx"),
    path(
        "tasks/delete-completed-htmx",
        tasks.delete_completed_htmx,
        name="tasks-delete-completed-htmx",
    ),
    path(
        "tasks/move-folder-htmx",
        tasks.move_folder_htmx,
        name="tasks-move-folder-htmx",
    ),
    path(
        "tasks/filter-priority/<int:priority_value>/",
        tasks.filter_priority_htmx,
        name="tasks-filter-priority",
    ),
    path(
        "tasks/add-editor/<int:folder_id>/<int:user_id>",
        tasks.add_editor,
        name="folder-add-editor",
    ),
    path(
        "tasks/remove-editor/<int:folder_id>/<int:user_id>",
        tasks.remove_editor,
        name="folder-remove-editor",
    ),
    # contacts
    path("contacts/", contacts.index, name="contacts"),
    path("contacts/<int:id>", contacts.select, name="contacts-select"),
    path("contacts/add", contacts.add, name="contacts-add"),
    path("contacts/<int:id>/edit", contacts.edit, name="contacts-edit"),
    path("contacts/<int:id>/delete", contacts.delete, name="contacts-delete"),
    path(
        "contacts/<int:id>/google-toggle",
        contacts.google_toggle,
        name="contacts-google-toggle",
    ),
    path("contacts/google-list", contacts.google_list, name="contacts-google-list"),
    # contacts htmx
    path("contacts/all/", contacts.contacts_all, name="contacts-all"),
    path("contacts/list-htmx/", contacts.contacts_list_htmx, name="contacts-list-htmx"),
    path(
        "contacts/detail-htmx/",
        contacts.contact_detail_htmx,
        name="contacts-detail-htmx",
    ),
    path(
        "contacts/<int:id>/select-htmx",
        contacts.select_htmx,
        name="contacts-select-htmx",
    ),
    path("contacts/form-htmx", contacts.contacts_form_htmx, name="contacts-form-htmx"),
    path(
        "contacts/<int:id>/form-htmx",
        contacts.contacts_form_htmx,
        name="contacts-form-htmx-edit",
    ),
    path(
        "contacts/<int:id>/delete-htmx",
        contacts.delete_htmx,
        name="contacts-delete-htmx",
    ),
    path(
        "contacts/<int:id>/google-toggle-htmx",
        contacts.google_toggle_htmx,
        name="contacts-google-toggle-htmx",
    ),
    # notes
    path("notes/", include("apps.notes.urls")),
    # weather
    path("weather/", weather.index, name="weather"),
    path("weather/zip", weather.zip, name="weather-zip"),
    # finance
    path("crypto/", finance.crypto, name="crypto"),
    path("crypto/<str:ord>", finance.crypto, name="crypto"),
    path("securities/", finance.securities, name="securities"),
    path("securities/<str:ord>", finance.securities, name="securities"),
    path("positions/", finance.positions, name="positions"),
    # search
    path("search/", search.index, name="search"),
    path("search/results", search.results, name="search-results"),
    # settings
    path("settings/", settings.index, name="settings"),
    path("settings/homepage/", settings.homepage_index, name="settings-homepage"),
    path("settings/google/", settings.google_index, name="settings-google"),
    path("settings/session/", settings.session_index, name="settings-session"),
    path(
        "settings/notifications/",
        settings.notifications_index,
        name="settings-notifications",
    ),
    path(
        "settings/notification-options/<str:option>/<str:value>",
        settings.notification_options,
        name="settings-notification-options",
    ),
    path(
        "settings/notification-email",
        settings.notification_email,
        name="settings-notification-email",
    ),
    path(
        "settings/encryption/",
        settings.encryption_index,
        name="settings-encryption",
    ),
    path(
        "settings/encryption/save-salt",
        settings.encryption_save_salt,
        name="settings-encryption-save-salt",
    ),
    path(
        "settings/encryption/clear-salt",
        settings.encryption_clear_salt,
        name="settings-encryption-clear-salt",
    ),
    path(
        "settings/encryption/notes",
        settings.encryption_notes_list,
        name="settings-encryption-notes",
    ),
    path(
        "settings/encryption/notes/update",
        settings.encryption_notes_bulk_update,
        name="settings-encryption-notes-update",
    ),
    path("settings/google/login", settings.google_login, name="settings-google-login"),
    path("settings/google/store", settings.google_store, name="settings-google-store"),
    path(
        "settings/google/logout", settings.google_logout, name="settings-google-logout"
    ),
    path("settings/theme", settings.theme, name="settings-theme"),
    path(
        "settings/search-engine", settings.search_engine, name="settings-search-engine"
    ),
    path(
        "settings/home-options/<str:option>/<str:value>",
        settings.home_options,
        name="settings-home-options",
    ),
    path(
        "settings/crypto-symbols/",
        settings.crypto_symbols,
        name="settings-crypto-symbols",
    ),
    path(
        "settings/crypto-symbols/add",
        settings.crypto_symbol_add,
        name="settings-crypto-symbol-add",
    ),
    path(
        "settings/crypto-symbols/<int:id>/edit",
        settings.crypto_symbol_edit,
        name="settings-crypto-symbol-edit",
    ),
    path(
        "settings/crypto-symbols/<int:id>/delete",
        settings.crypto_symbol_delete,
        name="settings-crypto-symbol-delete",
    ),
    path(
        "settings/securities-symbols/",
        settings.securities_symbols,
        name="settings-securities-symbols",
    ),
    path(
        "settings/securities-symbols/add",
        settings.securities_symbol_add,
        name="settings-securities-symbol-add",
    ),
    path(
        "settings/securities-symbols/<int:id>/edit",
        settings.securities_symbol_edit,
        name="settings-securities-symbol-edit",
    ),
    path(
        "settings/securities-symbols/<int:id>/delete",
        settings.securities_symbol_delete,
        name="settings-securities-symbol-delete",
    ),
    # lab
    path("lab/", lab.index, name="lab"),
    path("lab/email", lab.email_test, name="email-test"),
    path("lab/sms/", lab.sms_test, name="sms-test"),
]

urlpatterns += staticfiles_urlpatterns()
