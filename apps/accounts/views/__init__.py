from .logout import LogoutView
from .permission_list import PermissionListView
from .pos_me import PosMeView
from .pos_pin_login import PosPinLoginView
from .pos_restaurant_code import PosRestaurantCodeView
from .role_list import RoleListView
from .user_list_create import UserListCreateView
from .user_retrieve_update import UserRetrieveUpdateView

__all__ = [
    'LogoutView',
    'PermissionListView',
    'PosMeView',
    'PosPinLoginView',
    'PosRestaurantCodeView',
    'RoleListView',
    'UserListCreateView',
    'UserRetrieveUpdateView',
]
