import secrets
import string


AUTH_CODE_ALPHABET = string.ascii_letters + string.digits


def generate_restaurant_auth_code():
    return ''.join(secrets.choice(AUTH_CODE_ALPHABET) for _ in range(6))
