from rest_framework.authentication import BasicAuthentication


class CustomBasicAuthentication(BasicAuthentication):
    def authenticate_header(self, request):
        return None
