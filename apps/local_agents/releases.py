import base64
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from common.api.throttling import LocalAgentRateThrottle

from apps.local_agents.authentication import authenticate_local_agent


SHA256_PATTERN = re.compile(r'^[0-9a-f]{64}$')
MAX_MANIFEST_BYTES = 64 * 1024
VERSION_PATTERN = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$')


def _validated_release_manifest(payload):
    if not isinstance(payload, dict) or payload.get('schemaVersion') != 1:
        raise ValueError('Unsupported release manifest schema.')

    required_strings = ('version', 'platform', 'architecture', 'downloadUrl', 'sha256', 'signature')
    for field in required_strings:
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ValueError(f'Release manifest field {field} is required.')

    if payload['platform'] != 'windows' or payload['architecture'] != 'amd64':
        raise ValueError('Release manifest target is unsupported.')
    if not SHA256_PATTERN.fullmatch(payload['sha256'].lower()):
        raise ValueError('Release manifest SHA-256 is invalid.')
    try:
        signature = base64.b64decode(payload['signature'], validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError('Release manifest signature is invalid.') from error
    if len(signature) != 64:
        raise ValueError('Release manifest signature is invalid.')

    size = payload.get('size')
    if not isinstance(size, int) or size <= 0 or size > 100 * 1024 * 1024:
        raise ValueError('Release manifest size is invalid.')
    return payload


def fetch_release_manifest():
    manifest_url = str(getattr(settings, 'LOCAL_AGENT_RELEASE_MANIFEST_URL', '') or '').strip()
    if not manifest_url:
        return None
    request = Request(manifest_url, headers={'Accept': 'application/json', 'User-Agent': 'CafePostcodeBackend/1'})
    with urlopen(request, timeout=5) as response:
        content = response.read(MAX_MANIFEST_BYTES + 1)
    if len(content) > MAX_MANIFEST_BYTES:
        raise ValueError('Release manifest is too large.')
    return _validated_release_manifest(json.loads(content.decode('utf-8')))


def compare_release_versions(left, right):
    def parse(value):
        match = VERSION_PATTERN.fullmatch(str(value or '').strip())
        if match is None:
            return None
        return tuple(int(match.group(index)) for index in range(1, 4)), match.group(4) or ''

    left_version = parse(left)
    right_version = parse(right)
    if left_version is None or right_version is None:
        return 0
    if left_version[0] != right_version[0]:
        return 1 if left_version[0] > right_version[0] else -1
    if left_version[1] == right_version[1]:
        return 0
    if not left_version[1]:
        return 1
    if not right_version[1]:
        return -1
    return 1 if left_version[1] > right_version[1] else -1


def agent_update_status(agent):
    current_version = str(getattr(agent, 'version', '') or '').strip()
    try:
        manifest = fetch_release_manifest()
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
        return {
            'status': 'unavailable',
            'currentVersion': current_version,
            'latestVersion': '',
            'mandatory': False,
            'detail': str(error),
        }
    if manifest is None:
        return {
            'status': 'disabled',
            'currentVersion': current_version,
            'latestVersion': '',
            'mandatory': False,
            'detail': '',
        }
    latest_version = manifest['version']
    pending = (
        VERSION_PATTERN.fullmatch(current_version) is None
        or compare_release_versions(latest_version, current_version) > 0
    )
    return {
        'status': 'pending' if pending else 'up_to_date',
        'currentVersion': current_version,
        'latestVersion': latest_version,
        'mandatory': bool(manifest.get('mandatory')),
        'detail': '',
    }


class LocalAgentLatestReleaseView(APIView):
    permission_classes = []
    throttle_classes = [LocalAgentRateThrottle]

    def get(self, request):
        if authenticate_local_agent(request) is None:
            return Response({'detail': 'Invalid local agent token.'}, status=status.HTTP_401_UNAUTHORIZED)
        try:
            manifest = fetch_release_manifest()
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            return Response(
                {'detail': 'Local Agent release manifest is temporarily unavailable.', 'error': str(error)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if manifest is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(manifest)
