from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

LOCALE_PATHS = (
    '/usr/local/lib/python3.10/site-packages/django/contrib/humanize/locale/',
    (BASE_DIR / 'core' / 'locale').as_posix(),
)
