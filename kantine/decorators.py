#!/usr/bin/env python3

import os
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from .utils import find_login_url


def require_jwt_login(view):
    jwt_url_parts = os.environ.get("JWT_LOGINURL", "").split("|")
    if len(jwt_url_parts) % 2 > 0:
        jwt_url_parts.insert(len(jwt_url_parts) - 1, "")

    jwt_urls = list(zip(*[iter(jwt_url_parts)] * 2))

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
