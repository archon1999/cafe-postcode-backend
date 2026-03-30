import os

import class_settings
from class_settings import env
from django.core.wsgi import get_wsgi_application

env.read_env()
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
os.environ.setdefault('DJANGO_SETTINGS_CLASS', 'CoreSettings')
class_settings.setup()

application = get_wsgi_application()
