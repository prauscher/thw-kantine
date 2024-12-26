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
