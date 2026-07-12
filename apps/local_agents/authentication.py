from apps.local_agents.models import LocalAgent


def authenticate_local_agent(request):
    token = str(request.headers.get('Authorization', '')).removeprefix('Bearer ').strip()
    if not token:
        token = str(request.query_params.get('token', '')).strip()
    return LocalAgent.authenticate_token(token) if token else None
