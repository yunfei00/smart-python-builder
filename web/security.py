from starlette.responses import JSONResponse
from .uploads import MAX_UPLOAD


class UploadTooLarge(Exception):pass


class RequestLimitsMiddleware:
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        limit=MAX_UPLOAD+1024*1024
        headers=dict(scope.get('headers',[]))
        try:length=int(headers.get(b'content-length',b'0'))
        except ValueError:length=limit+1
        if length>limit:
            return await JSONResponse({'detail':'上传超过大小限制'},status_code=413)(scope,receive,send)
        total=0
        async def bounded_receive():
            nonlocal total
            message=await receive()
            total+=len(message.get('body',b''))
            if total>limit:raise UploadTooLarge()
            return message
        try:await self.app(scope,bounded_receive,send)
        except UploadTooLarge:
            await JSONResponse({'detail':'上传超过大小限制'},status_code=413)(scope,receive,send)
