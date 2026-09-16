from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from oauth2_provider.models import Application


class Command(BaseCommand):
    help = "Register a predefined confidential ChatGPT OAuth client. Copy the exact redirect URI from ChatGPT."

    def add_arguments(self, parser):
        parser.add_argument("--name", default="Cafe Postcode ChatGPT")
        parser.add_argument("--redirect-uri", required=True)

    def handle(self, *args, **options):
        uri = options["redirect_uri"]
        parsed = urlsplit(uri)
        local = (
            parsed.scheme == "http"
            and parsed.hostname in {"localhost", "127.0.0.1"}
            and not settings.DJANGO_PRODUCTION
        )
        if (
            not parsed.netloc
            or parsed.fragment
            or parsed.username
            or (parsed.scheme != "https" and not local)
        ):
            raise CommandError(
                "Use an exact HTTPS redirect URI (HTTP loopback allowed only in development)."
            )
        if Application.objects.filter(name=options["name"]).exists():
            raise CommandError(
                "Client name already exists. Use a distinct name; existing credentials are not overwritten."
            )
        application = Application(
            name=options["name"],
            redirect_uris=uri,
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
        )
        secret = application.client_secret
        application.save()
        self.stdout.write(
            f"Client ID: {application.client_id}\nClient secret (shown once): {secret}"
        )
