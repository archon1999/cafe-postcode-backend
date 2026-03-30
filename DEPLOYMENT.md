# Backend Deployment

## CI/CD

This repository uses:

- `develop` for ongoing development
- `production` for deployment

Deployment runs on every push to `production` via GitHub Actions over SSH.

Required GitHub repository secrets:

- `HOST`
- `PORT`
- `USERNAME`
- `PASSWORD`

The workflow SSHes into the server and runs:

```bash
cd /home/postcode/backend
git checkout production
git pull --ff-only origin production
poetry install --no-root
poetry run python manage.py migrate --noinput
poetry run python manage.py collectstatic --noinput
sudo -n systemctl restart postcode-backend
sudo -n systemctl is-active postcode-backend
```

## Required files on the server

Create `/home/postcode/backend/core/settings/config.env` before the first deploy.
You can start from `core/settings/config.env.example`.

## Runtime port

Run the service on:

- `127.0.0.1:8888`

Put your own Nginx reverse proxy in front of that port.

## Example systemd service

Copy `deploy/postcode-backend.service.example` to `/etc/systemd/system/postcode-backend.service`,
adjust paths if needed, then run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable postcode-backend
sudo systemctl restart postcode-backend
sudo systemctl status postcode-backend
```

## Sudo requirement for CI/CD

The SSH user used by GitHub Actions must be allowed to restart the service without an interactive password.

Example sudoers entry:

```bash
username ALL=(ALL) NOPASSWD: /bin/systemctl restart postcode-backend, /bin/systemctl is-active postcode-backend
```
