from flask import request


def get_pagination(default_per_page: int = 20, max_per_page: int = 100):
    try:
        page = int(request.args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(request.args.get("per_page", default_per_page))
    except (TypeError, ValueError):
        per_page = default_per_page
    page = max(1, page)
    per_page = max(1, min(max_per_page, per_page))
    offset = (page - 1) * per_page
    return page, per_page, offset


def wants_pagination() -> bool:
    """True se o cliente explicitou page/per_page via querystring.
    Mantém comportamento atual: só aplica LIMIT/OFFSET quando solicitado.
    """
    args = request.args
    return ("page" in args) or ("per_page" in args)
