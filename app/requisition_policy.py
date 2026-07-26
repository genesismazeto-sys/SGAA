import datetime


def _parse_optional_processing_datetime(data_processamento):
    raw = str(data_processamento or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(raw[:19], fmt)
        except ValueError:
            continue
    try:
        return datetime.datetime.strptime(raw[:10], "%Y-%m-%d")
    except ValueError:
        return None


def can_student_edit_requisition(status, data_processamento):
    status_norm = str(status or "").strip()
    if status_norm == "Pendente":
        return True
    if status_norm != "Devolvida":
        return False
    processed_at = _parse_optional_processing_datetime(data_processamento)
    if not processed_at:
        return False
    return datetime.datetime.now() <= (processed_at + datetime.timedelta(days=14))


def can_student_delete_requisition(status, data_processamento):
    return can_student_edit_requisition(status, data_processamento)
