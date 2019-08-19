from django.utils.deprecation import MiddlewareMixin
from django.http import request
from rest_framework.request import Request
from rest_framework.response import Response
from google.cloud.logging.resource import Resource
from google.cloud import logging
from google.cloud.logging.handlers.app_engine import AppEngineHandler
import logging as app_logging
import time, threading

_thread_locals = threading.local()

_GAE_APP_RESOURCE = Resource(type='gae_app', labels={"module_id": "default"})
client = logging.Client.from_service_account_json('service-account-logging.json')

client.setup_logging()

request_start_time = ''
request_time = ''
parent_logger = client.logger("parent")
logger = app_logging.getLogger("child")

def get_current_request():
    return getattr(_thread_locals, 'request', None)

# override appengine logging handler for set the trace value in logs
class GCPHandler(AppEngineHandler):
    def __init__(self, logName):
        self.logName = logName
        self.logger = client.logger(logName)
        super(AppEngineHandler, self).__init__(client)

    def emit(self, record):
        trace = ""
        try:
            record.request = get_current_request()

            # request contains 'HTTP_X_CLOUD_TRACE_CONTEXT' Meta in live API
            if 'HTTP_X_CLOUD_TRACE_CONTEXT' in record.request.META and record.request.META['HTTP_X_CLOUD_TRACE_CONTEXT'] != "":
                trace = record.request.META['HTTP_X_CLOUD_TRACE_CONTEXT'].split('/')[0]
            else:
                # For test logging from local update the below trace value for every request
                trace = "80a8891891eb0c4725bdcebd8df55418"
            
            msg = self.format(record)
            TEXT = msg
            SEVERITY = record.levelname
            TRACE = "projects/{}/traces/{}".format(client.project, trace)

            if len(TEXT) > 8000:
                TEXT = TEXT[0:8000]

            self.logger.name = "appengine.googleapis.com%2Fapp"
            self.logger.log_text(TEXT, client=client, severity=SEVERITY, trace=TRACE, resource=_GAE_APP_RESOURCE)
        except Exception as e:
            print(e)
            TRACE = "projects/{}/traces/{}".format(client.project, trace)
            self.logger.log_text(str(e), client=client, severity='ERROR', trace=TRACE, resource=_GAE_APP_RESOURCE)

class LoggingMiddleware(MiddlewareMixin):
    """
    Provides full logging of requests and responses
    """
    _initial_http_body = None

    def process_request(self, request):
        _thread_locals.request = request
        request_start_time = time.time()
        request_time = "%.5fs" % (time.time() - request_start_time)
        request.META['HTTP_X_UPSTREAM_SERVICE_TIME'] = request_time
        self._initial_http_body = request.body

    def process_response(self, request, response):
        """
        Adding request and response logging
        """
        request_time = request.META['HTTP_X_UPSTREAM_SERVICE_TIME']
        REQUEST_DATACONTENT = ''
        RESPONSE_DATACONTENT = ''
        trace = ""

        # request contains 'HTTP_X_CLOUD_TRACE_CONTEXT' Meta in live API
        if 'HTTP_X_CLOUD_TRACE_CONTEXT' in request.META and request.META['HTTP_X_CLOUD_TRACE_CONTEXT'] != "":
            trace = request.META['HTTP_X_CLOUD_TRACE_CONTEXT'].split('/')[0]
        else:
            # For test logging from local update the below trace value for every request
            trace = "80a8891891eb0c4725bdcebd8df55418"

        SEVERITY = 'INFO'
        TRACE = "projects/{}/traces/{}".format(client.project, trace)
        content_length = len(response.content)
        REQUEST = {
            'requestMethod': request.method,
            'requestUrl': request.get_full_path(),
            'status': response.status_code,
            'userAgent': request.META['HTTP_USER_AGENT'],
            'responseSize': content_length,
            'latency': request_time,
            'remoteIp': request.META['REMOTE_ADDR']
        }

        if request.method == 'GET':    
            REQUEST_DATACONTENT = request.GET
            if len(REQUEST_DATACONTENT) > 8000:
                REQUEST_DATACONTENT = REQUEST_DATACONTENT[0:8000]
        else:
            REQUEST_DATACONTENT = self._initial_http_body
            if len(REQUEST_DATACONTENT) > 8000:
                REQUEST_DATACONTENT = REQUEST_DATACONTENT[0:8000]
            
        RESPONSE_DATACONTENT = response.content
        if len(RESPONSE_DATACONTENT) > 8000:
            RESPONSE_DATACONTENT = RESPONSE_DATACONTENT[0:8000]

        parent_logger.name = "appengine.googleapis.com%2Fnginx.request"
        
        parent_logger.log_struct({
            'REQUEST':str(REQUEST_DATACONTENT),
            'RESPONSE':str(RESPONSE_DATACONTENT)
        }, client=client, severity=SEVERITY, http_request=REQUEST, trace=TRACE, resource=_GAE_APP_RESOURCE)
        logger.info(RESPONSE_DATACONTENT)
        return response