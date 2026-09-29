"""Bound actual request bytes, including chunked uploads, before multipart spooling.

FastAPI's multipart parser can wrap an exception raised by receive() as a generic 400.
This bounded prebuffer rejects directly at ASGI level, preserving an explicit 413 response.
There is one bytearray bounded by the configured request cap, not an unbounded chunk queue.
"""
from starlette.responses import JSONResponse


class RequestBodyLimitMiddleware:
    def __init__(self, app, upload_limit: int = 10 * 1024 * 1024 + 65_536,
                 json_limit: int = 131_072):
        self.app = app
        self.upload_limit = upload_limit
        self.json_limit = json_limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return
        limit = self.upload_limit if scope.get("path") == "/api/documents" else self.json_limit
        buffered = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] == "http.request":
                chunk = message.get("body", b"")
                if len(buffered) + len(chunk) > limit:
                    await JSONResponse({"detail": "The request body exceeds the permitted size."},
                                       status_code=413)(scope, receive, send)
                    return
                buffered.extend(chunk)
                if not message.get("more_body", False):
                    break
        delivered = False
        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(buffered), "more_body": False}
            return await receive()
        await self.app(scope, bounded_receive, send)
