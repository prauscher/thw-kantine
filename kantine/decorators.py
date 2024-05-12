#!/usr/bin/env python3

import os
from django.shortcuts import redirect


def require_jwt_login(view):
    jwt_url = os.environ.get("JWT_LOGINURL")

    def _view(request, *args, **kwargs):
        if "jwt_userdata" not in request.session:
            if jwt_url is None:
                raise PermissionDenied
            return redirect(jwt_url.rstrip("/") + request.get_full_path())

        return view(request, *args, **kwargs)

    return _view
