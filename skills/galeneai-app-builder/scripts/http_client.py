"""HTTP helpers for authenticated Galene API calls."""

from __future__ import annotations

import urllib.request


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so bearer credentials cannot leave the chosen origin."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_no_redirect(request: urllib.request.Request, *, timeout: int = 30):
    opener = urllib.request.build_opener(NoRedirectHandler())
    return opener.open(request, timeout=timeout)
