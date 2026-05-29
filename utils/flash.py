from utils.messages import flash

__all__ = ["flash_error", "flash_success", "flash_info"]

def flash_error(message: str):
    flash(message, "error")

def flash_success(message: str):
    flash(message, "success")

def flash_info(message: str):
    flash(message, "info")
