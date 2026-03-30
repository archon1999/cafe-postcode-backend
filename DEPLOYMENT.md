# Backend Deployment

## CI/CD

This repository deploys on every push to `main` via GitHub Actions over SSH.

Required GitHub repository secrets:

- `HOST`
- `PORT`
- `USERNAME`
- `PASSWORD`

The workflow SSHes into the server and runs:

```bash
cd /home/postcode/backend
mkdir -p .runtime/staticfiles .runtime/media .runtime/var
git checkout main
git pull --ff-only origin main
docker compose up -d --build --remove-orphans
```

## Required files on the server

Create `/home/postcode/backend/core/settings/config.env` before the first deploy.
You can start from `core/settings/config.env.example`.

## Runtime port

The container is exposed only on localhost:

- `127.0.0.1:8000`

Put your public Nginx reverse proxy in front of that port.

## Example host Nginx config

```nginx
server {
    listen 80;
    server_name cafe-postcode.uz;

    client_max_body_size 20m;

    location /static/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }

    location /media/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
