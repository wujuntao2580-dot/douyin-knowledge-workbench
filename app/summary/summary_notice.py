import ctypes


def show_notice(title, message, warning=False):
    message_box = ctypes.WinDLL("user32", use_last_error=True).MessageBoxW
    message_box.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint)
    message_box.restype = ctypes.c_int
    flags = 0x40000 | (0x30 if warning else 0x40)
    if not message_box(None, message, title, flags):
        raise ctypes.WinError(ctypes.get_last_error())
