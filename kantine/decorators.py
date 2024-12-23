#!/usr/bin/env python3

import os
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def require_jwt_login(view):
    jwt_url_parts = os.environ.get("JWT_LOGINURL", "").split("|")
    if len(jwt_url_parts) % 2 > 0:
        jwt_url_parts.insert(len(jwt_url_parts) - 1, "")

    jwt_urls = list(zip(*[iter(jwt_url_parts)] * 2))

    def _view(request, *args, **kwargs):
        if "jwt_userdata" not in request.session:
            full_path = request.get_full_path()

            for path_prefix, jwt_url in jwt_urls:
                if full_path.startswith(path_prefix):
                    break
            else:
                raise PermissionDenied

            return redirect(jwt_url.rstrip("/") + "/" + full_path[len(path_prefix):].lstrip("/"))

        userdata = request.session["jwt_userdata"]
        request.jwt_user_id = userdata["uid"]
        request.jwt_user_display = userdata["displayName"]

        return view(request, *args, **kwargs)

    return _view
