#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import jwt
from django.shortcuts import redirect


def jwt_login(request):
    pubkey = os.environ.get("JWT_PUBKEY", "")
    token = request.GET.get("jwt", "")
    decoded = jwt.decode(token, pubkey, algorithms=["ES256"])
    request.session["jwt_userdata"] = decoded.get("userdata")
    return redirect('abfrage.start')
