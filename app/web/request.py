from flask import request


def _is_ajax_request() -> bool:
    return request.headers.get("X-Requested-With", "").lower() == "xmlhttprequest"
