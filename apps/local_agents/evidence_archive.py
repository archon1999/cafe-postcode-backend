"""Private, immutable JSONL+gzip bundles with mandatory upload/readback verification."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.db import connection

from apps.local_agents.evidence_store import EvidenceUnavailable, canonical_bytes, checksum

MAX_BUNDLE_BYTES = 16 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
MAX_RECORDS = 1000


def assert_outside_transaction():
    if connection.in_atomic_block:
        raise EvidenceUnavailable('Archive I/O inside a database transaction is forbidden.')


def _valid_key(key):
    path = PurePosixPath(key)
    if (path.is_absolute() or '..' in path.parts or '\\' in key or not key.startswith('v1/')
            or not key.endswith('.jsonl.gz')):
        raise EvidenceUnavailable('Invalid archive key.')
    return path


class FileArchiveStore:
    """A private shared volume, independent of the public media/static volumes."""
    name = 'file'

    def _path(self, key):
        relative = _valid_key(key)
        configured = str(getattr(settings, 'AGENT_EVIDENCE_ARCHIVE_ROOT', '') or '')
        if not configured or not Path(configured).is_absolute():
            raise EvidenceUnavailable('A private absolute archive root must be configured.')
        root = Path(configured).resolve()
        for public_root in (settings.MEDIA_ROOT, settings.STATIC_ROOT):
            if root.is_relative_to(Path(public_root).resolve()):
                raise EvidenceUnavailable('Evidence archives cannot use public media/static storage.')
        target = root.joinpath(*relative.parts).resolve()
        if not target.is_relative_to(root):
            raise EvidenceUnavailable('Archive path escapes the private volume.')
        return root, target

    def put(self, key, data):
        assert_outside_transaction()
        root, path = self._path(key)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != 'nt':
            root.chmod(0o700)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Exclusive create: never replace an immutable verified object.
        with path.open('xb') as stream:
            if os.name != 'nt':
                os.chmod(path, 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name != 'nt':
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def get(self, key):
        assert_outside_transaction()
        _, path = self._path(key)
        with path.open('rb') as stream:
            data = stream.read(MAX_BUNDLE_BYTES + 1)
        if len(data) > MAX_BUNDLE_BYTES:
            raise EvidenceUnavailable('Archive bundle exceeds the read limit.')
        return data


class S3ArchiveStore:
    name = 's3'

    def __init__(self):
        import boto3
        from botocore.config import Config
        self.bucket = getattr(settings, 'AGENT_EVIDENCE_S3_BUCKET', '')
        if not self.bucket or self.bucket == settings.AWS_STORAGE_BUCKET_NAME:
            raise EvidenceUnavailable('A separate private archive bucket is required.')
        self.client = boto3.client(
            's3', region_name=getattr(settings, 'AGENT_EVIDENCE_S3_REGION', 'us-east-1'),
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
            config=Config(connect_timeout=3, read_timeout=5, retries={'total_max_attempts': 2}),
        )

    def put(self, key, data):
        assert_outside_transaction()
        _valid_key(key)
        block = self.client.get_public_access_block(Bucket=self.bucket)['PublicAccessBlockConfiguration']
        if not all(block.get(name) is True for name in (
            'BlockPublicAcls', 'IgnorePublicAcls', 'BlockPublicPolicy', 'RestrictPublicBuckets',
        )):
            raise EvidenceUnavailable('S3 archive bucket must block all public access.')
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType='application/gzip',
            ServerSideEncryption='AES256', IfNoneMatch='*',
        )

    def get(self, key):
        assert_outside_transaction()
        _valid_key(key)
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        stream = response['Body']
        try:
            data = stream.read(MAX_BUNDLE_BYTES + 1)
        finally:
            stream.close()
        if len(data) > MAX_BUNDLE_BYTES:
            raise EvidenceUnavailable('Archive bundle exceeds the read limit.')
        return data


def archive_store(backend=None):
    name = backend or getattr(settings, 'AGENT_EVIDENCE_ARCHIVE_BACKEND', '')
    if name == 'file':
        return FileArchiveStore()
    if name == 's3':
        return S3ArchiveStore()
    raise EvidenceUnavailable('Private archive storage is not configured.')


def build_bundle(payloads):
    records = []
    for payload in payloads:
        if payload.content is None or checksum(payload.content['body']) != payload.checksum:
            raise EvidenceUnavailable('Only verified hot payloads can be archived.')
        records.append({
            'v': 1, 'id': str(payload.pk), 'restaurantId': str(payload.restaurant_id),
            'operationId': payload.operation_id, 'sha256': payload.checksum,
            'byteLength': payload.byte_length, 'content': payload.content,
        })
    if not 0 < len(records) <= MAX_RECORDS:
        raise EvidenceUnavailable('Invalid archive batch size.')
    raw = b'\n'.join(canonical_bytes(record) for record in records) + b'\n'
    if len(raw) > MAX_UNCOMPRESSED_BYTES:
        raise EvidenceUnavailable('Archive batch exceeds the uncompressed limit; use a smaller batch.')
    data = gzip.compress(raw, compresslevel=6, mtime=0)
    if len(data) > MAX_BUNDLE_BYTES:
        raise EvidenceUnavailable('Archive batch exceeds the compressed limit.')
    return data


def decode_bundle(*, data, archive):
    if (len(data) != archive.byte_length or hashlib.sha256(data).hexdigest() != archive.checksum
            or archive.format_version != 1):
        raise EvidenceUnavailable('Archive manifest checksum/length/version mismatch.')
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
        raw = stream.read(MAX_UNCOMPRESSED_BYTES + 1)
    if len(raw) > MAX_UNCOMPRESSED_BYTES:
        raise EvidenceUnavailable('Archive decompression limit exceeded.')
    records = {}
    for line in raw.splitlines():
        record = json.loads(line)
        content = record['content']
        if (record['v'] != 1 or record['restaurantId'] != str(archive.restaurant_id)
                or record['id'] in records or set(content) != {'body'}
                or checksum(content['body']) != record['sha256']
                or len(canonical_bytes(content['body'])) != record['byteLength']):
            raise EvidenceUnavailable('Archive record checksum/identity mismatch.')
        records[record['id']] = content
    if len(records) != archive.record_count or len(records) > MAX_RECORDS:
        raise EvidenceUnavailable('Archive record count mismatch.')
    return records


def read_archive(archive):
    try:
        assert_outside_transaction()
        return decode_bundle(data=archive_store(archive.backend).get(archive.object_key), archive=archive)
    except EvidenceUnavailable:
        raise
    except Exception as error:
        # Provider messages may contain credentials/URLs: never expose them to POS.
        raise EvidenceUnavailable('Private archive is unavailable or corrupt.') from error
