#!/usr/bin/env python3

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from .utils import find_login_url


def require_jwt_login(view):
    def _view(request, *args, **kwargs):
        if "FORCE_LOGIN" in os.environ:
            request.session["jwt_userdata"] = {
                "uid": os.environ["FORCE_LOGIN"],
                "displayName": os.environ["FORCE_LOGIN"],
            }

        elif "jwt_userdata" not in request.session:
            full_path = request.get_full_path()

            try:
                return redirect(find_login_url(full_path))
            except ValueError:
                raise PermissionDenied

        userdata = request.session["jwt_userdata"]
        request.jwt_user_id = userdata["uid"]
        request.jwt_user_display = userdata["displayName"]

        return view(request, *args, **kwargs)

    return _view
