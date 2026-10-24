"""Read-only production evidence inventory. Never export business inputs or secrets."""
import collections
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

os.umask(0o077)
ROOT = Path('/home/postcode/backend')
COMPOSE = ['docker', 'compose', '--env-file', '.env.production']
DB_SCRIPT = r'''
import json
from django.db import connection, transaction
from django.db.models import Count, Min, Max
from django.db.migrations.recorder import MigrationRecorder
from apps.platform.models import AIUsageLog
from apps.catalog_assistant.models import CatalogDraft, ManagementBotUpdate
from django.utils import timezone
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION READ ONLY')
    migration = MigrationRecorder.Migration.objects.get(app='platform', name='0014_ai_usage_log')
    cutoff = migration.applied
    usage = AIUsageLog.objects.aggregate(count=Count('id'), first=Min('created_at'), last=Max('created_at'))
    drafts = CatalogDraft.objects.filter(created_at__lt=cutoff).order_by('created_at')
    candidates = [{'id': str(d.pk), 'createdAt': d.created_at.isoformat(),
        'restaurantId': str(d.restaurant_id), 'userId': str(d.owner_id),
        'rowCount': len(d.rows) if isinstance(d.rows, list) else None,
        'committedAt': d.committed_at.isoformat() if d.committed_at else None}
        for d in drafts.iterator()]
    print('AI_HISTORY_DB=' + json.dumps({'inspectedAt': timezone.now().isoformat(),
        'cutoff': cutoff.isoformat(), 'usage': usage, 'catalogDrafts': candidates,
        'telegramUpdates': ManagementBotUpdate.objects.aggregate(count=Count('id'), first=Min('created_at'), last=Max('created_at'))}, default=str))
'''


def run(args, **kwargs):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True, timeout=120, **kwargs).stdout


raw = run(COMPOSE + ['exec', '-T', 'web', 'python', 'manage.py', 'shell', '-c', 'import sys; exec(sys.stdin.read())'], input=DB_SCRIPT)
database = json.loads(next(line.split('=', 1)[1] for line in raw.splitlines() if line.startswith('AI_HISTORY_DB=')))
paths = re.compile(r'/(?:catalog-assistant/drafts/|inventory/(?:insights/analyze|documents/ai-preview)/|[^ ?]*service-fee[^ ?]*/ai[^ ?]*/)(?:\?|$)')
combined = re.compile(r'"(?P<method>POST) (?P<path>/[^ ?"]+)(?:\?[^ "]*)? HTTP/[^\"]+" (?P<status>\d{3})')
events = []
coverage = []
counts = collections.Counter()


def inspect_lines(lines, source):
    count = 0
    first = last = None
    for line in lines:
        count += 1
        stamp, _, body = line.partition(' ')
        if re.match(r'^20\d\d-\d\d-\d\dT', stamp):
            first = first or stamp
            last = stamp
        else:
            body, stamp = line, None
            nginx_time = re.search(r'\[(\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\]', line)
            if nginx_time:
                stamp = dt.datetime.strptime(nginx_time.group(1), '%d/%b/%Y:%H:%M:%S %z').isoformat()
                first = first or stamp
                last = stamp
        try:
            record = json.loads(body)
        except (ValueError, TypeError):
            record = None
        event = None
        if isinstance(record, dict):
            path = str(record.get('path') or '')
            message = str(record.get('message') or '')
            if record.get('method') == 'POST' and paths.search(path):
                event = {'kind': 'application_endpoint', 'path': path.split('?')[0],
                    'status': record.get('status_code'), 'durationMs': record.get('latency_ms')}
            elif record.get('name') == 'httpx' and re.search(r'HTTP Request: POST https://api\.openai\.com/v1/responses\b', message):
                status = re.search(r'HTTP/[\d.]+ (\d{3})', message)
                event = {'kind': 'provider_attempt', 'status': int(status.group(1)) if status else None}
            if event:
                for src, target in [('request_id', 'requestId'), ('user_id', 'userId'), ('restaurant_id', 'restaurantId')]:
                    value = str(record.get(src) or '')
                    if re.fullmatch(r'[A-Za-z0-9._-]{1,100}', value):
                        event[target] = value
                event['at'] = stamp or record.get('asctime') or record.get('timestamp')
        else:
            match = combined.search(body)
            if match and paths.search(match.group('path')):
                event = {'kind': 'access_endpoint', 'path': match.group('path'), 'status': int(match.group('status')), 'at': stamp}
        if event:
            event.update(source=source, fingerprint=hashlib.sha256(line.encode()).hexdigest())
            events.append(event)
            counts[(event['kind'], event.get('path', ''), str(event.get('status')))] += 1
    coverage.append({'source': source, 'lines': count, 'first': first, 'last': last})


for service in ('web', 'ws', 'qcluster', 'nginx'):
    try:
        cid = run(COMPOSE + ['ps', '-q', service]).strip()
        if not cid:
            continue
        info = json.loads(run(['docker', 'inspect', '--format', '{"created":{{json .Created}},"logging":{{json .HostConfig.LogConfig}}}', cid]))
        coverage.append({'service': service, 'containerCreatedAt': info['created'],
            'logDriver': info['logging'].get('Type'),
            'rotation': {key: value for key, value in info['logging'].get('Config', {}).items() if key in ('max-size', 'max-file', 'mode')}})
        result = subprocess.run(['docker', 'logs', '--timestamps', '--tail', '250000', cid],
            cwd=ROOT, capture_output=True, text=True, timeout=180)
        inspect_lines((result.stdout + '\n' + result.stderr).splitlines(), 'docker:' + service)
    except (subprocess.SubprocessError, ValueError, KeyError) as error:
        coverage.append({'service': service, 'errorType': type(error).__name__})

for path in sorted(Path('/var/log/nginx').glob('*access*.log*')):
    if not path.is_file():
        continue
    try:
        import gzip
        opener = gzip.open if path.suffix == '.gz' else open
        with opener(path, 'rt', encoding='utf-8', errors='replace') as stream:
            inspect_lines(stream, 'host-nginx:' + path.name)
    except (OSError, ValueError) as error:
        coverage.append({'source': path.name, 'errorType': type(error).__name__})

report = {'schema': 1, 'database': database, 'coverage': coverage, 'events': events}
folder = ROOT / 'var' / 'ai-history-recovery'
folder.mkdir(parents=True, exist_ok=True, mode=0o700)
destination = folder / 'inspection-v1.json'
destination.write_text(json.dumps(report, ensure_ascii=False, indent=2))
destination.chmod(0o600)
print(json.dumps({'cutoff': database['cutoff'], 'existingUsage': database['usage'],
    'historicalCatalogDraftCount': len(database['catalogDrafts']),
    'historicalCatalogDraftSample': database['catalogDrafts'][:30],
    'telegramUpdates': database['telegramUpdates'], 'coverage': coverage,
    'eventCounts': [{'kind': key[0], 'path': key[1], 'status': key[2], 'count': value} for key, value in sorted(counts.items())],
    'eventSample': events[:30], 'privateEvidenceFile': str(destination)}, default=str, ensure_ascii=False))
