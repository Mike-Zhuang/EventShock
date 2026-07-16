"""不会向客户端泄露内部路径或堆栈的稳定业务错误。"""

from __future__ import annotations


class ApiError(Exception):
    def __init__(self, code: str, statusCode: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.statusCode = statusCode
        self.message = message
