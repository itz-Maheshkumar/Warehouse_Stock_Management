import logging

logger = logging.getLogger(__name__)

class RequestLoggingMiddleware:
    """Log each request with user, path, method, and other key metadata."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        logger.info(
            'Incoming request',
            extra={
                'method': request.method,
                'path': request.path,
                'user': request.user.username if request.user.is_authenticated else 'anonymous',
                'query_params': request.GET.dict(),
                'remote_addr': request.META.get('REMOTE_ADDR'),
            }
        )
        response = self.get_response(request)
        logger.info(
            'Request complete',
            extra={
                'status_code': response.status_code,
                'content_type': response.get('Content-Type', ''),
                'path': request.path,
            }
        )
        return response
