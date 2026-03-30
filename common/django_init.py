import os
import class_settings
from class_settings import env

from django.core.management import execute_from_command_line

env.read_env()
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
os.environ.setdefault('DJANGO_SETTINGS_CLASS', 'CoreSettings')
class_settings.setup()
execute_from_command_line()
