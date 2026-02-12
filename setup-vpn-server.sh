#!/bin/bash

# Скрипт автоматической настройки VPN сервера Ubuntu 24.04 для VPN платформы
# Использование:
#   sudo bash setup-vpn-server.sh          # Режим разработки (dev)
#   sudo bash setup-vpn-server.sh --dev    # Режим разработки (dev)
#   sudo bash setup-vpn-server.sh --prod   # Режим продакшена (prod)
#   sudo bash setup-vpn-server.sh --help   # Показать справку

set -e  # Остановка при ошибке

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Функция для вывода сообщений
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

# Функция показа справки
show_help() {
    echo "Скрипт автоматической настройки VPN сервера Ubuntu 24.04"
    echo ""
    echo "Использование:"
    echo "  sudo bash setup-vpn-server.sh [РЕЖИМ]"
    echo ""
    echo "Режимы работы:"
    echo "  (без параметров)     Режим разработки (dev)"
    echo "  --dev                Режим разработки (dev)"
    echo "  --prod               Режим продакшена (prod)"
    echo "  --help               Показать эту справку"
    echo ""
    echo "Что устанавливается:"
    echo "  ✅ Базовые инструменты (git, curl, wget, vim, nano, htop и др.)"
    echo "  ✅ Docker + Docker Compose"
    echo "  ✅ Безопасность (Firewall, fail2ban, SSH, Portsentry)"
    echo ""
    echo "Примечание:"
    echo "  Этот скрипт усиливает безопасность хоста (hardening)."
    echo "  Основную установку XRay + Agent выполняет install-vpn-server.sh."
    echo "  VPN сервер не требует Python, PostgreSQL, Redis или Node.js"
    echo "  Все сервисы работают в Docker контейнерах"
    echo ""
    exit 0
}

# Проверка параметров
MODE="dev"
if [ "$1" == "--help" ] || [ "$1" == "-h" ]; then
    show_help
elif [ "$1" == "--dev" ]; then
    MODE="dev"
elif [ "$1" == "--prod" ] || [ "$1" == "--production" ]; then
    MODE="prod"
elif [ -n "$1" ]; then
    error "Неизвестный параметр: $1"
    echo ""
    show_help
fi

# Проверка прав root
if [ "$EUID" -ne 0 ]; then
    error "Пожалуйста, запустите скрипт с правами root (sudo)"
    exit 1
fi

if [ "$MODE" = "dev" ]; then
    MODE_NAME="Режим разработки (dev)"
else
    MODE_NAME="Режим продакшена (prod)"
fi

info "Режим: $MODE_NAME"
echo ""

# Получаем имя текущего пользователя (не root)
if [ -z "$SUDO_USER" ]; then
    CURRENT_USER=$(whoami)
else
    CURRENT_USER=$SUDO_USER
fi

info "Текущий пользователь: $CURRENT_USER"
echo ""

STEP_COUNT=1
TOTAL_STEPS=7  # Обновление системы + базовые инструменты + Docker + 4 шага безопасности

# Шаг 1: Обновление системы
info "Шаг $STEP_COUNT/$TOTAL_STEPS: Обновление системы..."
apt update -qq
apt upgrade -y -qq
success "Система обновлена"
echo ""
((STEP_COUNT++))

# Шаг 2: Установка базовых инструментов
info "Шаг $STEP_COUNT/$TOTAL_STEPS: Установка базовых инструментов..."
apt install -y -qq \
    git \
    curl \
    wget \
    vim \
    nano \
    htop \
    net-tools \
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsb-release
success "Базовые инструменты установлены"
echo ""
((STEP_COUNT++))

# Шаг 3: Установка Docker и Docker Compose
info "Шаг $STEP_COUNT/$TOTAL_STEPS: Установка Docker и Docker Compose..."

# Проверка, установлен ли Docker
if ! command -v docker &> /dev/null; then
    info "Установка Docker из официального репозитория..."

    # Добавление официального репозитория Docker
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt update -qq

    # Установка Docker и Docker Compose
    apt install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # Запуск и автозапуск Docker
    systemctl enable docker
    systemctl start docker

    # Добавление пользователя в группу docker
    usermod -aG docker $CURRENT_USER

    success "Docker установлен и запущен"
else
    warning "Docker уже установлен"
fi

# Проверка версии Docker
DOCKER_VERSION=$(docker --version)
info "Версия Docker: $DOCKER_VERSION"
echo ""
((STEP_COUNT++))

# Настройка безопасности
# Шаг 4: Настройка Firewall (UFW)
info "Шаг $STEP_COUNT/$TOTAL_STEPS: Настройка Firewall..."
if command -v ufw &> /dev/null; then
    # Разрешаем SSH
    ufw allow 22/tcp comment 'SSH' 2>/dev/null || true

    # Разрешаем порты для VPN сервера
    ufw allow 433/tcp comment 'XRay TCP' 2>/dev/null || true
    ufw allow 433/udp comment 'XRay UDP' 2>/dev/null || true

    read -p "CORE_API_IP (IP Core API для доступа к агенту, обязательно): " CORE_API_IP
    if [ -z "$CORE_API_IP" ]; then
        error "CORE_API_IP обязателен. Без него Core API не сможет обращаться к агенту."
        exit 1
    fi
    ufw allow from "$CORE_API_IP" to any port 8080 proto tcp comment 'XRay Agent (Core API)' 2>/dev/null || true

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
((STEP_COUNT++))

# Шаг 5: Установка и настройка fail2ban (защита от брутфорса)
info "Шаг $STEP_COUNT/$TOTAL_STEPS: Установка и настройка fail2ban (защита от брутфорса)..."

if ! command -v fail2ban-client &> /dev/null; then
    apt install -y -qq fail2ban

    # Создаем локальную конфигурацию
    cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
# Время бана (по умолчанию)
bantime = 3600
# Время окна для подсчета попыток
findtime = 600
# Количество попыток перед баном
maxretry = 5

[sshd]
enabled = true
port = ssh
logpath = %(sshd_log)s
backend = %(sshd_backend)s
maxretry = 3
bantime = 7200
findtime = 600

[sshd-ddos]
enabled = true
port = ssh
logpath = %(sshd_log)s
backend = %(sshd_backend)s
maxretry = 10
findtime = 600
bantime = 3600
EOF

    # Запуск fail2ban
    systemctl enable fail2ban
    systemctl start fail2ban

    success "fail2ban установлен и настроен"
    info "fail2ban будет блокировать IP после 3 неудачных попыток SSH в течение 10 минут"
else
    warning "fail2ban уже установлен"
fi
echo ""
((STEP_COUNT++))

# Шаг 6: Настройка SSH безопасности
info "Шаг $STEP_COUNT/$TOTAL_STEPS: Настройка SSH безопасности..."

SSH_CONFIG="/etc/ssh/sshd_config"
SSH_CONFIG_BACKUP="/etc/ssh/sshd_config.backup.$(date +%Y%m%d_%H%M%S)"

# Создаем резервную копию
cp $SSH_CONFIG $SSH_CONFIG_BACKUP
info "Резервная копия SSH конфига создана: $SSH_CONFIG_BACKUP"

# Настройки безопасности SSH
info "Применение настроек безопасности SSH..."

# Отключение root логина через пароль (разрешаем только через ключи)
sed -i 's/^#PermitRootLogin.*/PermitRootLogin prohibit-password/' $SSH_CONFIG
sed -i 's/^PermitRootLogin.*/PermitRootLogin prohibit-password/' $SSH_CONFIG

# Отключение аутентификации по паролю (только ключи)
sed -i 's/^#PasswordAuthentication.*/PasswordAuthentication no/' $SSH_CONFIG
sed -i 's/^PasswordAuthentication.*/PasswordAuthentication no/' $SSH_CONFIG

# Разрешение аутентификации по ключам
sed -i 's/^#PubkeyAuthentication.*/PubkeyAuthentication yes/' $SSH_CONFIG
sed -i 's/^PubkeyAuthentication.*/PubkeyAuthentication yes/' $SSH_CONFIG

# Отключение пустых паролей
sed -i 's/^#PermitEmptyPasswords.*/PermitEmptyPasswords no/' $SSH_CONFIG
sed -i 's/^PermitEmptyPasswords.*/PermitEmptyPasswords no/' $SSH_CONFIG

# Ограничение попыток входа
sed -i 's/^#MaxAuthTries.*/MaxAuthTries 3/' $SSH_CONFIG
sed -i 's/^MaxAuthTries.*/MaxAuthTries 3/' $SSH_CONFIG

# Отключение X11 forwarding (если не нужен)
sed -i 's/^#X11Forwarding.*/X11Forwarding no/' $SSH_CONFIG
sed -i 's/^X11Forwarding.*/X11Forwarding no/' $SSH_CONFIG

# Настройка таймаутов
if ! grep -q "^ClientAliveInterval" $SSH_CONFIG; then
    echo "ClientAliveInterval 300" >> $SSH_CONFIG
fi
if ! grep -q "^ClientAliveCountMax" $SSH_CONFIG; then
    echo "ClientAliveCountMax 2" >> $SSH_CONFIG
fi

# Проверка конфигурации перед применением
if sshd -t; then
    systemctl restart ssh
    success "SSH настроен безопасно"
    warning "ВАЖНО: Убедитесь, что у вас есть SSH ключ для входа!"
    warning "Если SSH ключа нет, создайте его перед выходом из сессии!"
else
    error "Ошибка в конфигурации SSH, восстановление из резервной копии..."
    cp $SSH_CONFIG_BACKUP $SSH_CONFIG
    systemctl restart ssh
    error "SSH конфигурация восстановлена из резервной копии"
fi
echo ""
((STEP_COUNT++))

# Шаг 7: Дополнительная защита от ботсканов
info "Шаг $STEP_COUNT/$TOTAL_STEPS: Дополнительная защита от ботсканов..."

# Установка и настройка Portsentry для защиты от сканирования портов
if ! command -v portsentry &> /dev/null; then
    apt install -y -qq portsentry

    # Настройка Portsentry
    sed -i 's/BLOCK_TCP="0"/BLOCK_TCP="1"/' /etc/portsentry/portsentry.conf
    sed -i 's/BLOCK_UDP="0"/BLOCK_UDP="1"/' /etc/portsentry/portsentry.conf
    sed -i 's/KILL_ROUTE="\/sbin\/route add -host $TARGET$ reject"/KILL_ROUTE="\/sbin\/iptables -I INPUT -s $TARGET$ -j DROP"/' /etc/portsentry/portsentry.conf

    # Запуск Portsentry
    systemctl enable portsentry
    systemctl start portsentry

    success "Portsentry установлен и настроен"
else
    warning "Portsentry уже установлен"
fi

# Дополнительные правила firewall для защиты от ботсканов
if command -v ufw &> /dev/null; then
    info "Настройка дополнительных правил firewall..."

    # Лимит подключений к SSH (защита от брутфорса)
    ufw limit ssh/tcp comment 'SSH rate limit' 2>/dev/null || true

    # Блокировка подозрительных портов
    ufw deny 23/tcp comment 'Block Telnet' 2>/dev/null || true
    ufw deny 135/tcp comment 'Block RPC' 2>/dev/null || true
    ufw deny 139/tcp comment 'Block NetBIOS' 2>/dev/null || true
    ufw deny 445/tcp comment 'Block SMB' 2>/dev/null || true
    ufw deny 1433/tcp comment 'Block MSSQL' 2>/dev/null || true
    ufw deny 3306/tcp comment 'Block MySQL' 2>/dev/null || true

    success "Дополнительные правила firewall применены"
fi

# Настройка rate limiting для SSH через iptables (дополнительная защита)
if command -v iptables &> /dev/null; then
    # Проверяем, не добавлено ли уже правило
    if ! iptables -C INPUT -p tcp --dport ssh -m state --state NEW -m recent --set --name SSH 2>/dev/null; then
        iptables -A INPUT -p tcp --dport ssh -m state --state NEW -m recent --set --name SSH
        iptables -A INPUT -p tcp --dport ssh -m state --state NEW -m recent --update --seconds 60 --hitcount 4 --name SSH -j DROP
        success "Rate limiting для SSH настроен через iptables"
    fi

    # Защита от SYN flood атак
    if ! iptables -C INPUT -p tcp --syn -m limit --limit 1/s --limit-burst 3 -j ACCEPT 2>/dev/null; then
        iptables -I INPUT -p tcp --syn -m limit --limit 1/s --limit-burst 3 -j ACCEPT
        iptables -A INPUT -p tcp --syn -j DROP
        success "Защита от SYN flood настроена через iptables"
    fi

    # Защита от IP spoofing (блокировка пакетов с невалидными исходными IP)
    # Для VPN сервера блокируем только loopback и multicast с внешних интерфейсов
    if ! iptables -C INPUT -s 127.0.0.0/8 ! -i lo -j DROP 2>/dev/null; then
        iptables -A INPUT -s 127.0.0.0/8 ! -i lo -j DROP
        iptables -A INPUT -s 0.0.0.0/8 -j DROP
        iptables -A INPUT -d 0.0.0.0/8 -j DROP
        iptables -A INPUT -d 255.255.255.255 -j DROP
        success "Защита от IP spoofing настроена"
    fi
fi

# Настройка sysctl для защиты от различных атак
info "Настройка системных параметров безопасности (sysctl)..."
cat >> /etc/sysctl.conf << 'EOF'

# Защита от различных сетевых атак
# Защита от SYN flood
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_max_syn_backlog = 2048
net.ipv4.tcp_synack_retries = 2
net.ipv4.tcp_syn_retries = 5

# Защита от IP spoofing
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1

# Отключение перенаправления ICMP (защита от redirect атак)
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0

# Отключение отправки ICMP redirect (защита от redirect атак)
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0

# Защита от source routing атак
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv6.conf.all.accept_source_route = 0
net.ipv6.conf.default.accept_source_route = 0

# Логирование подозрительных пакетов
net.ipv4.conf.all.log_martians = 1
net.ipv4.conf.default.log_martians = 1

# Защита от ping flood (ограничение ICMP)
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.icmp_ignore_bogus_error_responses = 1

# Включение IP forwarding (необходимо для VPN сервера)
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
EOF

sysctl -p > /dev/null 2>&1
success "Системные параметры безопасности настроены"
echo ""

# Итоговая информация
success "Настройка VPN сервера завершена!"
echo ""

info "=== Установленные компоненты ==="
echo ""
echo "✅ Базовые инструменты: установлены"
echo "Docker: $(docker --version | cut -d' ' -f3 | tr -d ',')"
if command -v fail2ban-client &> /dev/null; then
    echo "fail2ban: установлен"
fi
if command -v portsentry &> /dev/null; then
    echo "Portsentry: установлен"
fi
echo ""

info "=== Настройки безопасности ==="
echo ""
info "✅ Firewall (UFW): Открыты порты 22 (SSH), 433 (XRay TCP/UDP), 8080 только для Core API"
info "✅ fail2ban: Защита от брутфорса SSH (3 попытки → бан на 2 часа)"
info "✅ SSH: Отключена аутентификация по паролю (только ключи)"
info "✅ SSH: Отключен root логин по паролю"
info "✅ Portsentry: Защита от сканирования портов"
info "✅ Firewall: Rate limiting для SSH"
info "✅ Firewall: Блокировка неиспользуемых портов"
info "✅ iptables: Защита от SYN flood атак"
info "✅ iptables: Защита от IP spoofing"
info "✅ sysctl: Защита от сетевых атак (SYN flood, IP spoofing, ICMP redirect)"
info "✅ sysctl: IP forwarding включен (необходимо для VPN)"
echo ""

info "=== Следующие шаги ==="
echo ""
info "1. ⚠️  ВАЖНО: Убедитесь, что у вас есть SSH ключ для входа!"
info "   Если SSH ключа нет, создайте его СЕЙЧАС:"
info "   ssh-keygen -t ed25519 -C 'your.email@example.com'"
info "   # Скопируйте публичный ключ на сервер:"
info "   ssh-copy-id user@server-ip"
echo ""
info "2. Перезайдите в систему (или выполните: newgrp docker) для применения изменений групп Docker"
echo ""
info "3. Клонируйте репозиторий:"
info "   git clone https://github.com/Alexjptz/HomeVPN.git"
info "   cd HomeVPN"
echo ""
info "4. Создайте .env файл с переменными окружения для VPN сервера:"
info "   CORE_API_URL=https://ВАШ_ОСНОВНОЙ_СЕРВЕР:8000"
info "   AGENT_API_KEY=СКОПИРУЙТЕ_ИЗ_БД_ПОСЛЕ_СОЗДАНИЯ"
info "   SERVER_ID=ID_СЕРВЕРА_ИЗ_БД"
info "   AGENT_URL=http://IP_СЕРВЕРА:8080"
echo ""
info "5. Запустите XRay Agent и XRay Server:"
info "   docker compose up -d --no-deps xray-agent xray-server"
echo ""
info "Проверить статус fail2ban: sudo fail2ban-client status"
info "Проверить забаненные IP: sudo fail2ban-client status sshd"
info "Проверить статус firewall: sudo ufw status verbose"
echo ""

success "Готово! 🚀"
warning "Не забудьте настроить SSH ключ для безопасного входа!"
warning "После настройки SSH ключа перезайдите в систему для применения группы Docker!"
