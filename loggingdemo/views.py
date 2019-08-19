from rest_framework.views import APIView
from rest_framework.response import Response
import logging

logger = logging.getLogger("child")

class Login(APIView):
    
    def post(self, request):
        logger.info("Login Started")

        return Response("Login Successful")
