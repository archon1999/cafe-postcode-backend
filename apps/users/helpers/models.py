from django.apps import apps


def get_auth_session_model():
    return apps.get_model('users', 'AuthSession')


def get_employee_profile_model():
    return apps.get_model('users', 'EmployeeProfile')


def get_permission_model():
    return apps.get_model('users', 'Permission')


def get_permission_endpoint_model():
    return apps.get_model('users', 'PermissionEndpoint')


def get_restaurant_profile_model():
    return apps.get_model('users', 'RestaurantProfile')


def get_role_model():
    return apps.get_model('users', 'Role')


def get_user_model():
    return apps.get_model('users', 'User')
