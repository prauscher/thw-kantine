from django.utils.log import AdminEmailHandler


class CustomEmailHandler(AdminEmailHandler):
    """Custom Handler that ignores 404 errors instead of sending them by email"""

    def _check_ignore_url(self, path):
        return True

    def handle(self, record):
        if record.__dict__.get("status_code", 200) == 404:
            message_args = record.args
            if len(message_args) == 2 and message_args[0] == "Not Found":
                return
        super().handle(record)


def find_login_url(path):
    jwt_url_parts = os.environ.get("JWT_LOGINURL", "").split("|")
    if len(jwt_url_parts) % 2 > 0:
        jwt_url_parts.insert(len(jwt_url_parts) - 1, "")

    jwt_urls = list(zip(*[iter(jwt_url_parts)] * 2))

    for path_prefix, jwt_url in jwt_urls:
        if path.startswith(path_prefix):
            return jwt_url.rstrip("/") + "/" + path[len(path_prefix):].lstrip("/")

    raise ValueError
