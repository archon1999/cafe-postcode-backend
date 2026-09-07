import re


SECRET_PATTERNS = (
    re.compile(r'(?i)(bearer\s+)[a-z0-9._~+/-]+=*'),
    re.compile(
        r'(?i)(authorization|agent[_ -]?token|enrollment[_ -]?token|local[_ -]?api[_ -]?token|'
        r'restaurant[_ -]?(?:auth[_ -]?)?code)(["\'=:\s]+)([^\s,}"\']+)'
    ),
    re.compile(r'\bcp[ae]_[A-Za-z0-9_-]+\b'),
)


def sanitize_remote_text(value):
    text = str(value or '')[:4000]
    text = SECRET_PATTERNS[0].sub(r'\1[REDACTED]', text)
    text = SECRET_PATTERNS[1].sub(r'\1\2[REDACTED]', text)
    return SECRET_PATTERNS[2].sub('[REDACTED]', text)


def sanitize_remote_logs_result(result):
    result = result if isinstance(result, dict) else {}
    lines = result.get('lines') if isinstance(result.get('lines'), list) else []
    return {
        'available': result.get('available') is True,
        'lines': [sanitize_remote_text(line) for line in lines[-100:]],
        'detail': sanitize_remote_text(result.get('detail')),
    }


def sanitize_support_result(value):
    if isinstance(value, dict):
        return {key: '[REDACTED]' if any(word in key.lower() for word in (
            'password', 'token', 'secret', 'authorization', 'privatekey', 'pinhash',
        )) else sanitize_support_result(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_support_result(item) for item in value[:500]]
    if isinstance(value, str):
        return sanitize_remote_text(value)
    return value
