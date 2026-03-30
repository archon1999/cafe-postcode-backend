import os

from django.core.asgi import get_asgi_application

import class_settings
from class_settings import env

env.read_env()
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
os.environ.setdefault('DJANGO_SETTINGS_CLASS', 'CoreSettings')
class_settings.setup()

application = get_asgi_application()
