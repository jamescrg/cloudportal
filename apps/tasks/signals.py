"""Signals the tasks app sends."""

from django.dispatch import Signal

# Tasks were moved out of folders, by a save or a bulk update: ``moved`` is
# a list of (task id, owner id, the folder it left), ``folder_id`` the
# folder they went to (None for the Inbox)
tasks_moved = Signal()
