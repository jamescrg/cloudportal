"""Reading the document an app publishes to say who it is (its client ID
metadata document), for django-oauth-toolkit.

The toolkit takes an app to have one way of signing in besides refreshing,
and refuses a document that lists more. claude.ai's lists two: the usual
authorization code, which it signs in to CloudPortal with, and a JWT bearer
grant it uses elsewhere. Only the grants CloudPortal offers are kept, so
the document is read for what it can do here.
"""

from oauth2_provider.cimd import SafeMetadataFetcher

OFFERED = ("authorization_code", "refresh_token")


class OfferedGrantsFetcher(SafeMetadataFetcher):
    """The toolkit's guarded fetcher, keeping only the offered grants."""

    def fetch(self, client_id):
        metadata, max_age = super().fetch(client_id)
        grants = metadata.get("grant_types")
        if isinstance(grants, list):
            offered = [grant for grant in grants if grant in OFFERED]
            # A document offering none of them is left as it is, for the
            # toolkit to refuse
            if offered:
                metadata = {**metadata, "grant_types": offered}
        return metadata, max_age
