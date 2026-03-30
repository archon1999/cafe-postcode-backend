from django.db import models


def composite_index(*fields: str, name: str) -> models.Index:
    return models.Index(fields=list(fields), name=name)


def scoped_status_index(scope_field: str, *, status_field: str = 'status', name: str) -> models.Index:
    return composite_index(scope_field, status_field, name=name)


def scoped_timestamp_index(scope_field: str, timestamp_field: str, *, name: str) -> models.Index:
    return composite_index(scope_field, timestamp_field, name=name)


def state_timestamp_index(state_field: str, timestamp_field: str, *, name: str) -> models.Index:
    return composite_index(state_field, timestamp_field, name=name)
