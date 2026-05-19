from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage


def build_storage_location(path: str) -> str:
    prefix = settings.AWS_S3_MEDIA_PREFIX.strip('/')
    suffix = path.strip('/')
    if not prefix:
        return suffix
    if not suffix:
        return prefix
    return f'{prefix}/{suffix}'


class CatalogImageStorage(S3Boto3Storage):
    bucket_name = settings.AWS_STORAGE_BUCKET_NAME
    custom_domain = settings.AWS_S3_CUSTOM_DOMAIN
    default_acl = settings.AWS_DEFAULT_ACL
    file_overwrite = settings.AWS_S3_FILE_OVERWRITE
    object_parameters = settings.AWS_S3_OBJECT_PARAMETERS
    querystring_auth = settings.AWS_QUERYSTRING_AUTH


class CatalogCategoryImageStorage(CatalogImageStorage):
    location = build_storage_location('catalog/categories')


class CatalogItemImageStorage(CatalogImageStorage):
    location = build_storage_location('catalog/items')


class RestaurantAuthBackgroundStorage(CatalogImageStorage):
    location = build_storage_location('restaurants/auth-backgrounds')
