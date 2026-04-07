from .dining_table_detail import DiningTableDetailView
from .dining_table_list_create import DiningTableListCreateView
from apps.floor.api.pos.views.dining_table_reserve import DiningTableReserveView
from .hall_detail import HallDetailView
from .hall_list_create import HallListCreateView
from apps.floor.api.pos.views.table_session_detail import TableSessionDetailView
from apps.floor.api.pos.views.table_session_list_create import TableSessionListCreateView
from apps.floor.api.pos.views.table_session_merge import TableSessionMergeView
from apps.floor.api.pos.views.table_session_move import TableSessionMoveView
from .zone_detail import ZoneDetailView
from .zone_list_create import ZoneListCreateView
from .hall_constructor import HallConstructorView

__all__ = [
    'DiningTableDetailView',
    'DiningTableListCreateView',
    'DiningTableReserveView',
    'HallDetailView',
    'HallListCreateView',
    'TableSessionDetailView',
    'TableSessionListCreateView',
    'TableSessionMergeView',
    'TableSessionMoveView',
    'ZoneDetailView',
    'ZoneListCreateView',
    'HallConstructorView',
]
