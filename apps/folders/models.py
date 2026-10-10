from django.db import models

from accounts.models import CustomUser
from apps.common.models import TimestampMixin


class Folder(TimestampMixin, models.Model):
    """A folder for categorizing favorites, contacts, notes or other data.

    Attributes:
        id (int): the unique identifier for the folder
        user (int): the user who created and owns the folder
        page (str): the page to which the folder belongs
        name (str): the name or title of the folder
        home_column (int): whether the folder is shown on the home page: set
            when it is, 0 or null when not (the name is from the page's old
            fixed columns; task folders may still carry 2 to 5)
        home_rank (int): the folder's place in the owner's sequence of folders
            on the home page
        selected (int): for tasks folders,
            whether the folder has been selected to be displayed
        active (int): for task folders,
            whether the folder is active for new task entries
        editors: the list of users with access to edit the contents of the folder
    """

    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="folder_owner"
    )
    page = models.CharField(max_length=50)
    name = models.CharField(max_length=50)
    home_column = models.IntegerField(blank=True, null=True)
    home_rank = models.IntegerField(blank=True, null=True)
    selected = models.IntegerField(blank=True, null=True)
    active = models.IntegerField(blank=True, null=True)
    editors = models.ManyToManyField(CustomUser, related_name="folder_editors")

    fillable = [
        "name",
        "home_column",
        "home_rank",
        "selected",
        "active",
    ]

    def __str__(self):
        return f"{self.name}"

    class Meta:
        db_table = "app_folder"
