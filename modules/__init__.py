"""
modules/
--------
Namespace package chứa toàn bộ Domain Container (dyeing, knitting, ...).

Đây là package RỖNG có chủ đích: `app.py::_autoload_domains()` chỉ dùng
`modules.__path__` để quét (scan) các sub-package con bằng `pkgutil`, không
import trực tiếp từng Domain ở đây — giữ đúng nguyên tắc "không hardcode".
"""
