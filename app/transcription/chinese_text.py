import ctypes


_map_text = ctypes.WinDLL("kernel32", use_last_error=True).LCMapStringEx
_map_text.argtypes = (
    ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_int,
    ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_longlong,
)
_map_text.restype = ctypes.c_int


def _convert(text, flag):
    if not text:
        return text
    size = _map_text("zh-CN", flag, text, -1, None, 0, None, None, 0)
    if not size:
        raise ctypes.WinError(ctypes.get_last_error())
    result = ctypes.create_unicode_buffer(size)
    if not _map_text("zh-CN", flag, text, -1, result, size, None, None, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return result.value


def simplified(text):
    return _convert(text, 0x02000000)


def traditional(text):
    return _convert(text, 0x04000000)
