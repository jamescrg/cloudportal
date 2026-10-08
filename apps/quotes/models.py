from django.db import models

from accounts.models import CustomUser


class Quote(models.Model):
    """A quote the user keeps for the home page's Quote of the Day.

    Attributes:
        user (int): whose quote it is
        text (str): the quote itself
        author (str): who said it, when the user gave one; blank otherwise
        always (bool): shown every day, before the day's own quote
        position (int): the order the quotes were given in, which is the
            order they show in when the mode is serial
    """

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    text = models.TextField()
    author = models.CharField(max_length=200, blank=True, default="")
    always = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "app_quote"
        ordering = ["position", "id"]

    def __str__(self):
        return self.text[:60]
