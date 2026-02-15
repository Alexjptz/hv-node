#!/bin/bash
# 🚀 HomeVPN - Автоустановщик VPN сервера
# Быстрая установка и настройка VPN сервера с XRay Agent
#
# Использование:
#   curl -sSL https://raw.githubusercontent.com/Alexjptz/hv-node/main/install-vpn-server.sh | bash
#   или
#   wget -qO- https://raw.githubusercontent.com/Alexjptz/hv-node/main/install-vpn-server.sh | bash

set -euo pipefail

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Функции для вывода
info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

step() {
    echo -e "${CYAN}${BOLD}▶ $1${NC}"
}

# Проверка прав root
if [ "$EUID" -ne 0 ]; then
    error "Пожалуйста, запустите скрипт с правами root (sudo)"
    exit 1
fi

# Переменные
INSTALL_DIR="/root/hv-node"
GITHUB_REPO="https://github.com/Alexjptz/hv-node.git"
BRANCH="main"

# Определение публичного IP (только IPv4 для AGENT_URL)
get_public_ip() {
    PUBLIC_IP=$(curl -4 -s --max-time 5 ifconfig.me 2>/dev/null || \
               curl -4 -s --max-time 5 icanhazip.com 2>/dev/null || \
               curl -4 -s --max-time 5 ipinfo.io/ip 2>/dev/null || \
               hostname -I | tr ' ' '\n' | grep -v ':' | head -1 || \
               echo "")
    echo "$PUBLIC_IP"
}

# Заголовок
clear
echo -e "${BLUE}${BOLD}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║                                                            ║"
echo "║        🚀 HomeVPN - Автоустановщик VPN сервера             ║"
echo "║                                                            ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo ""

# Шаг 1: Обновление системы
step "Шаг 1/8: Обновление системы..."
apt update -qq
apt upgrade -y -qq
success "Система обновлена"
echo ""

# Шаг 1.5: Синхронизация времени (NTP) — критично для VLESS Reality, иначе timeout
step "Настройка NTP (синхронизация времени)..."
if command -v timedatectl &> /dev/null; then
    timedatectl set-ntp true 2>/dev/null || true
    systemctl enable systemd-timesyncd 2>/dev/null || true
    systemctl start systemd-timesyncd 2>/dev/null || true
    info "Текущее время: $(date -Iseconds)"
    success "NTP включён (важно для VLESS Reality — рассинхрон даёт timeout)"
else
    apt install -y -qq chrony 2>/dev/null && systemctl enable chrony && systemctl start chrony || warning "NTP не настроен — при timeout проверьте время: date"
fi
echo ""

# Шаг 2: Установка базовых инструментов
step "Шаг 2/8: Установка базовых инструментов..."
apt install -y -qq \
    git \
    curl \
    wget \
    ca-certificates \
    apt-transport-https \
    gnupg \
    lsb-release \
    jq
success "Базовые инструменты установлены"
echo ""

# Шаг 3: Установка Docker и Docker Compose
step "Шаг 3/8: Установка Docker и Docker Compose..."
if ! command -v docker &> /dev/null; then
    info "Установка Docker из официального репозитория..."

    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt update -qq
    apt install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    systemctl enable docker
    systemctl start docker

    success "Docker установлен и запущен"
else
    warning "Docker уже установлен"
fi

DOCKER_VERSION=$(docker --version)
info "Версия Docker: $DOCKER_VERSION"
echo ""

# Шаг 4: Настройка Firewall
step "Шаг 4/8: Настройка Firewall (UFW)..."
if command -v ufw &> /dev/null; then
    # Разрешаем SSH
    ufw allow 22/tcp comment 'SSH' 2>/dev/null || true

    # Разрешаем порты для VPN сервера
    ufw allow 433/tcp comment 'XRay TCP' 2>/dev/null || true
    ufw allow 433/udp comment 'XRay UDP' 2>/dev/null || true

    # Включаем firewall (только если еще не включен)
    if ! ufw status | grep -q "Status: active"; then
        ufw --force enable
        success "Firewall включен"
    else
        warning "Firewall уже включен"
    fi

    info "Правила firewall:"
    ufw status numbered
else
    warning "UFW не найден, пропускаем настройку firewall"
fi
echo ""

# Шаг 5: Создание директории и клонирование репозитория
step "Шаг 5/8: Подготовка файлов VPN сервера..."
if [ -d "$INSTALL_DIR" ]; then
    warning "Директория $INSTALL_DIR уже существует"
    read -p "Перезаписать? (y/N): " -n 1 -r < /dev/tty
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$INSTALL_DIR"
    else
        info "Используем существующую директорию"
    fi
fi

if [ ! -d "$INSTALL_DIR" ]; then
    mkdir -p "$INSTALL_DIR"

    # Клонируем только нужные части репозитория
    info "Клонирование репозитория..."
    git clone --depth 1 --branch "$BRANCH" --filter=blob:none --sparse "$GITHUB_REPO" "$INSTALL_DIR" 2>/dev/null || \
    git clone --depth 1 --branch "$BRANCH" "$GITHUB_REPO" "$INSTALL_DIR"

    cd "$INSTALL_DIR"

    # Настройка sparse checkout (если поддерживается)
    if [ -d ".git" ]; then
        git sparse-checkout init --cone >/dev/null 2>&1 || true
        git sparse-checkout set xray-agent >/dev/null 2>&1 || true
    fi
fi

XRAY_AGENT_REL="xray-agent"
if [ -d "$INSTALL_DIR/xray-agent" ]; then
    XRAY_AGENT_REL="xray-agent"
else
    error "Не найдена директория xray-agent. Проверьте репозиторий и доступ к GitHub."
    exit 1
fi

cd "$INSTALL_DIR"
success "Файлы подготовлены"
echo ""

# Шаг 6: Создание docker-compose.yml для VPN сервера
step "Шаг 6/8: Создание конфигурации Docker Compose..."
cat > "$INSTALL_DIR/docker-compose.yml" << 'EOF'
version: '3.8'

services:
  xray-agent:
    build:
      context: __XRAY_AGENT_DIR__
      dockerfile: Dockerfile
    container_name: homevpn_xray_agent
    environment:
      CORE_API_URL: ${CORE_API_URL}
      AGENT_API_KEY: ${AGENT_API_KEY}
      SERVER_ID: ${SERVER_ID}
      AGENT_URL: ${AGENT_URL}
      AGENT_PORT: 8080
      XRAY_CONFIG_PATH: /etc/xray/config.json
      XRAY_RELOAD_COMMAND: docker exec homevpn_xray_server xray -test -config /etc/xray/config.json && docker exec homevpn_xray_server kill -SIGHUP 1 || true
      XRAY_API_ADDRESS: 127.0.0.1:10085
      ENVIRONMENT: production
      LOG_LEVEL: INFO
    ports:
      - "8080:8080"
    depends_on:
      xray-server:
        condition: service_started
    volumes:
      - xray_config:/etc/xray
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./logs/xray-agent:/app/logs
    networks:
      - homevpn_network
    restart: unless-stopped
    healthcheck:
      test: [ "CMD", "curl", "-f", "http://localhost:8080/health" ]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  xray-server:
    image: teddysun/xray:1.8.11
    container_name: homevpn_xray_server
    ports:
      - "433:433"
      - "433:433/udp"
    volumes:
      - xray_config:/etc/xray
      - ./certs:/etc/xray/certs:ro
      - ./logs/xray-server:/var/log/xray
    networks:
      - homevpn_network
    restart: unless-stopped
    cap_add:
      - NET_ADMIN
    sysctls:
      - net.ipv4.ip_forward=1
      - net.ipv6.conf.all.forwarding=1

volumes:
  xray_config:

networks:
  homevpn_network:
    driver: bridge
EOF
sed -i "s|__XRAY_AGENT_DIR__|./${XRAY_AGENT_REL}|g" "$INSTALL_DIR/docker-compose.yml"

success "docker-compose.yml создан"
echo ""

# Шаг 7: Создание .env файла
step "Шаг 7/8: Настройка переменных окружения..."
PUBLIC_IP=$(get_public_ip)

if [ -z "$PUBLIC_IP" ]; then
    warning "Не удалось определить публичный IP автоматически"
    read -p "Введите публичный IP сервера: " PUBLIC_IP < /dev/tty
fi

info "Введите данные для подключения к Core API:"
read -p "CORE_API_URL (например, https://api.example.com:8000): " CORE_API_URL < /dev/tty
if [ -z "$CORE_API_URL" ]; then
    error "CORE_API_URL обязателен. Без него агент не сможет подключиться к Core API."
    exit 1
fi
read -p "CORE_API_IP (IP Core API для доступа к агенту, обязательно): " CORE_API_IP < /dev/tty
if [ -z "$CORE_API_IP" ]; then
    error "CORE_API_IP обязателен. Без него Core API не сможет обращаться к агенту."
    exit 1
fi
read -p "AGENT_API_KEY (получите из админ-панели после создания сервера): " AGENT_API_KEY < /dev/tty
read -p "SERVER_ID (ID сервера из базы данных): " SERVER_ID < /dev/tty

AGENT_URL="http://${PUBLIC_IP}:8080"

cat > "$INSTALL_DIR/.env" << EOF
# Core API connection
CORE_API_URL=${CORE_API_URL}
AGENT_API_KEY=${AGENT_API_KEY}
SERVER_ID=${SERVER_ID}

# Agent settings
AGENT_URL=${AGENT_URL}
AGENT_PORT=8080

# XRay Configuration
XRAY_CONFIG_PATH=/etc/xray/config.json
XRAY_RELOAD_COMMAND=docker exec homevpn_xray_server xray -test -config /etc/xray/config.json && docker exec homevpn_xray_server kill -SIGHUP 1 || true
XRAY_API_ADDRESS=127.0.0.1:10085

# Environment
ENVIRONMENT=production
LOG_LEVEL=INFO
EOF

chmod 600 "$INSTALL_DIR/.env"
success ".env файл создан"
echo ""

# Ограничиваем доступ к агенту только IP Core API
if command -v ufw &> /dev/null; then
    ufw allow from "$CORE_API_IP" to any port 8080 proto tcp comment 'XRay Agent (Core API)' 2>/dev/null || true
    success "Доступ к агенту открыт только для Core API: $CORE_API_IP"
else
    warning "UFW не найден, правило для 8080 не применено"
fi
echo ""

# Шаг 8: Создание директорий и запуск сервисов
step "Шаг 8/8: Запуск VPN сервера..."
cd "$INSTALL_DIR"

# Создаем необходимые директории
mkdir -p logs/xray-agent logs/xray-server certs

# Генерируем базовый конфиг XRay если его нет
if [ ! -f "xray_config/config.json" ]; then
    mkdir -p xray_config
    info "Создание базового конфига XRay..."
    # Базовый конфиг будет создан агентом при первом запуске
fi

# Собираем и запускаем контейнеры
info "Сборка и запуск контейнеров..."
docker compose build xray-agent
docker compose up -d

# Ожидание запуска
info "Ожидание запуска сервисов..."
sleep 10

# Проверка статуса
if docker compose ps | grep -q "Up"; then
    success "VPN сервер запущен!"
    echo ""
    info "Статус сервисов:"
    docker compose ps
    echo ""
    info "Проверка health check агента..."
    sleep 5
    if curl -s http://localhost:8080/health > /dev/null 2>&1; then
        success "XRay Agent работает и отвечает на health check"
    else
        warning "XRay Agent еще не готов, проверьте логи: docker compose logs xray-agent"
    fi
else
    error "Ошибка при запуске сервисов"
    info "Проверьте логи: docker compose logs"
    exit 1
fi

echo ""
success "═══════════════════════════════════════════════════════════"
success "  Установка завершена успешно! 🎉"
success "═══════════════════════════════════════════════════════════"
echo ""
info "Полезные команды:"
echo "  Проверить статус:     cd $INSTALL_DIR && docker compose ps"
echo "  Просмотр логов:       cd $INSTALL_DIR && docker compose logs -f"
echo "  Остановить сервер:    cd $INSTALL_DIR && docker compose down"
echo "  Перезапустить:        cd $INSTALL_DIR && docker compose restart"
echo ""
info "Конфигурация:"
echo "  Директория:           $INSTALL_DIR"
echo "  .env файл:            $INSTALL_DIR/.env"
echo "  Логи:                 $INSTALL_DIR/logs/"
echo ""
info "Примечание:"
echo "  VPN сервер установлен в домашней директории root: $INSTALL_DIR"
echo ""
info "Следующие шаги:"
echo "  1. Убедитесь, что сервер зарегистрирован в Core API"
echo "  2. Проверьте статус агента: curl http://localhost:8080/health"
echo "  3. Проверьте метрики в админ-панели"
echo ""
warning "⚠️  ВАЖНО: Убедитесь, что AGENT_API_KEY и SERVER_ID корректны!"
warning "⚠️  Если агент не регистрируется, проверьте CORE_API_URL и доступность Core API"
echo ""
