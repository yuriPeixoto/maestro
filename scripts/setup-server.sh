#!/bin/bash
# Executar como root no servidor: bash scripts/setup-server.sh
set -euo pipefail

echo "=== Maestro — Setup inicial do servidor ==="

# Dependências
apt-get install -y rsync
echo "✓ rsync instalado"

# Estrutura de diretórios
mkdir -p /opt/maestro/{agent,api,frontend}
chown -R deploy:deploy /opt/maestro
echo "✓ /opt/maestro criado (dono: deploy)"

# Nginx
cat > /etc/nginx/sites-available/maestro << 'NGINX_EOF'
server {
    listen 80;
    server_name _;

    root /opt/maestro/frontend;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
NGINX_EOF

ln -sf /etc/nginx/sites-available/maestro /etc/nginx/sites-enabled/maestro
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
echo "✓ Nginx configurado"

# maestro-api.service
cat > /etc/systemd/system/maestro-api.service << 'SYSTEMD_EOF'
[Unit]
Description=Maestro API
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=deploy
WorkingDirectory=/opt/maestro/api
ExecStart=/opt/maestro/api/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SYSTEMD_EOF

# maestro-agent.service
cat > /etc/systemd/system/maestro-agent.service << 'SYSTEMD_EOF'
[Unit]
Description=Maestro Agent
After=network.target maestro-api.service

[Service]
Type=simple
User=deploy
ExecStart=/opt/maestro/agent/maestro-agent
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SYSTEMD_EOF

systemctl daemon-reload
systemctl enable maestro-api maestro-agent
echo "✓ Serviços systemd configurados (maestro-api, maestro-agent)"

# Sudoers: deploy pode reiniciar os serviços sem senha
echo 'deploy ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart maestro-api, /usr/bin/systemctl restart maestro-agent' > /etc/sudoers.d/deploy-maestro
chmod 440 /etc/sudoers.d/deploy-maestro
echo "✓ Sudoers: deploy autorizado a reiniciar os serviços"

echo ""
echo "=== Setup concluído. Push para main dispara o deploy automático. ==="
