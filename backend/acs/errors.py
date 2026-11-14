class Conflict(Exception):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def require(condition, code, message, status=409):
    if not condition:
        raise Conflict(code, message, status)
