#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import jwt
from django.utils.http import url_has_allowed_host_and_scheme
from django.shortcuts import redirect
from django.urls import reverse
from .utils import find_login_url


def jwt_login(request, token, next=""):
    pubkey = os.environ.get("JWT_PUBKEY", "")

    if next.rstrip("/") == "" or not url_has_allowed_host_and_scheme(url=next, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next = reverse("abfrage:start")

    try:
        decoded = jwt.decode(token, pubkey, algorithms=["ES256"], leeway=10)
    except jwt.exceptions.ExpiredSignatureError:
        # Signature expired, try relogin
        next = find_login_url(next)
    else:
        request.session["jwt_userdata"] = decoded.get("userdata")

    return redirect(next)
