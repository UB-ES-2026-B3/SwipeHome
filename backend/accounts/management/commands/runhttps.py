"""Local HTTPS only; certificate and key stay outside version control."""
import ssl
from wsgiref.simple_server import WSGIRequestHandler, make_server

from django.core.management.base import BaseCommand, CommandError
from django.core.wsgi import get_wsgi_application


class HTTPSHandler(WSGIRequestHandler):
    def get_environ(self):
        environ = super().get_environ()
        environ["HTTPS"] = "on"
        return environ

    def log_message(self, format, *args):
        # Do not log request paths, cookies or bodies.
        pass


def https_server(cert, key, port=8443):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    server = make_server("127.0.0.1", port, get_wsgi_application(), handler_class=HTTPSHandler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    return server


class Command(BaseCommand):
    help = "Serve local development over HTTPS on loopback (no autoreload)."

    def add_arguments(self, parser):
        parser.add_argument("--cert", required=True)
        parser.add_argument("--key", required=True)
        parser.add_argument("--port", type=int, default=8443)

    def handle(self, *args, **options):
        try:
            server = https_server(options["cert"], options["key"], options["port"])
        except (OSError, ssl.SSLError):
            raise CommandError("Cannot start local HTTPS: check certificate, key and port.") from None
        self.stdout.write(f"Local HTTPS: https://localhost:{server.server_port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
