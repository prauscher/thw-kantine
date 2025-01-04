from collections.abc import Callable

from django.http import HttpRequest, HttpResponse


# see https://stackoverflow.com/questions/27720254/django-allowed-hosts-with-el
# b-healthcheck - this Middleware reacts to all requests beyond /healthcheck.
# This allows for ignoring of other middlewares, which would check remote IP,
# Host-Header etc, which are not valid for healthcheck requests
def health_check_middleware(get_response: Callable[[HttpRequest],
                                                   HttpResponse],
                            ) -> Callable[[HttpRequest], HttpResponse]:
    def _middleware(request: HttpRequest) -> HttpResponse:
        if request.path_info.startswith("/healthcheck"):
            return HttpResponse("ok")
        return get_response(request)

    return _middleware
