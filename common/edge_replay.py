"""Request-local replay context; never enabled by a public request header."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from django.utils import timezone


_event_time = ContextVar('edge_event_time', default=None)
_historical_floor = ContextVar('historical_floor', default=None)


@dataclass(frozen=True)
class HistoricalFloorScope:
    restaurant_id: str
    session_ids: frozenset
    table_ids: frozenset


def event_time():
    return _event_time.get() or timezone.now()


def historical_floor_scope():
    return _historical_floor.get()


def historical_session(session_id):
    scope = historical_floor_scope()
    return scope is not None and str(session_id) in scope.session_ids


@contextmanager
def edge_event_time(occurred_at):
    token = _event_time.set(occurred_at)
    try:
        yield
    finally:
        _event_time.reset(token)


@contextmanager
def historical_floor_projection(scope):
    token = _historical_floor.set(scope)
    try:
        yield
    finally:
        _historical_floor.reset(token)
