#!/bin/bash

# 🔒 HomeVPN - Настройка безопасности VPN сервера
# Запускать ПОСЛЕ install-vpn-server.sh. Усиливает безопасность: fail2ban, SSH hardening, Portsentry, sysctl.
#
# Использование:
#   sudo ./security-setup.sh           # Режим разработки (dev)
#   sudo ./security-setup.sh --dev     # Режим разработки (dev)
#   sudo ./security-setup.sh --prod    # Режим продакшена (prod)
#   sudo ./security-setup.sh --help    # Показать справку

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

show_help() {
    echo "🔒 HomeVPN - Настройка безопасности VPN сервера"
    echo ""
    echo "Использование: sudo ./security-setup.sh [РЕЖИМ]"
    echo ""
    echo "Режимы: --dev (по умолчанию), --prod, --help"
    echo ""
    echo "Что настраивается (только безопасность, без дублирования install-vpn-server.sh):"
    echo "  ✅ fail2ban — защита от брутфорса SSH"
    echo "  ✅ SSH hardening — только ключи, отключение паролей"
    echo "  ✅ Portsentry — защита от сканирования портов"
    echo "  ✅ Доп. правила firewall, iptables, sysctl"
    echo ""
    echo "Запускать ПОСЛЕ install-vpn-server.sh!"
    exit 0
}

# Параметры
MODE="dev"
[ "$1" == "--help" ] || [ "$1" == "-h" ] && show_help
[ "$1" == "--prod" ] || [ "$1" == "--production" ] && MODE="prod"

# Проверка root
[ "$EUID" -ne 0 ] && { error "Запустите с правами root (sudo)"; exit 1; }

# ═══════════════════════════════════════════════════════════════
# ⚠️  ОБЯЗАТЕЛЬНОЕ ПРЕДУПРЕЖДЕНИЕ ПЕРЕД НАЧАЛОМ
# ═══════════════════════════════════════════════════════════════
clear
echo -e "${YELLOW}${BOLD}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║  ⚠️  ВАЖНО: ПРОВЕРЬТЕ ПОДКЛЮЧЕНИЕ ПО SSH КЛЮЧУ!            ║"
echo "╠════════════════════════════════════════════════════════════╣"
echo "║  Этот скрипт отключит аутентификацию по паролю и root     ║"
echo "║  без ключа. Если SSH по ключу не настроен — вы потеряете  ║"
echo "║  доступ к серверу!                                        ║"
echo "║                                                            ║"
echo "║  Убедитесь, что:                                           ║"
echo "║  • SSH ключ добавлен (ssh-copy-id user@server)             ║"
echo "║  • Вход по ключу работает во второй сессии                 ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo ""
read -p "SSH по ключу настроен и проверен? Продолжить? (y/N): " -n 1 -r < /dev/tty
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    info "Отменено. Запустите скрипт после настройки SSH ключа."
    exit 0
fi
echo ""

# ═══════════════════════════════════════════════════════════════
# Шаги (без дублирования install-vpn-server.sh)
# install уже сделал: apt update, базовые пакеты, Docker, firewall (22, 433, 8080 для CORE_API_IP)
# ═══════════════════════════════════════════════════════════════
STEP_COUNT=1
TOTAL_STEPS=4

# Шаг 1: fail2ban
info "Шаг $STEP_COUNT/$TOTAL_STEPS: Установка fail2ban (защита от брутфорса)..."
if ! command -v fail2ban-client &> /dev/null; then
    apt install -y -qq fail2ban
    cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime = 3600
findtime = 600
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
    systemctl enable fail2ban
    systemctl start fail2ban
    success "fail2ban установлен"
else
    warning "fail2ban уже установлен"
fi
echo ""
((STEP_COUNT++))

# Шаг 2: SSH hardening
info "Шаг $STEP_COUNT/$TOTAL_STEPS: Настройка SSH безопасности..."
SSH_CONFIG="/etc/ssh/sshd_config"
SSH_BACKUP="/etc/ssh/sshd_config.backup.$(date +%Y%m%d_%H%M%S)"
cp "$SSH_CONFIG" "$SSH_BACKUP"
info "Резервная копия: $SSH_BACKUP"

sed -i 's/^#PermitRootLogin.*/PermitRootLogin prohibit-password/' "$SSH_CONFIG"
sed -i 's/^PermitRootLogin.*/PermitRootLogin prohibit-password/' "$SSH_CONFIG"
sed -i 's/^#PasswordAuthentication.*/PasswordAuthentication no/' "$SSH_CONFIG"
sed -i 's/^PasswordAuthentication.*/PasswordAuthentication no/' "$SSH_CONFIG"
sed -i 's/^#PubkeyAuthentication.*/PubkeyAuthentication yes/' "$SSH_CONFIG"
sed -i 's/^PubkeyAuthentication.*/PubkeyAuthentication yes/' "$SSH_CONFIG"
sed -i 's/^#PermitEmptyPasswords.*/PermitEmptyPasswords no/' "$SSH_CONFIG"
sed -i 's/^PermitEmptyPasswords.*/PermitEmptyPasswords no/' "$SSH_CONFIG"
sed -i 's/^#MaxAuthTries.*/MaxAuthTries 3/' "$SSH_CONFIG"
sed -i 's/^MaxAuthTries.*/MaxAuthTries 3/' "$SSH_CONFIG"
sed -i 's/^#X11Forwarding.*/X11Forwarding no/' "$SSH_CONFIG"
sed -i 's/^X11Forwarding.*/X11Forwarding no/' "$SSH_CONFIG"
grep -q "^ClientAliveInterval" "$SSH_CONFIG" || echo "ClientAliveInterval 300" >> "$SSH_CONFIG"
grep -q "^ClientAliveCountMax" "$SSH_CONFIG" || echo "ClientAliveCountMax 2" >> "$SSH_CONFIG"

if sshd -t 2>/dev/null; then
    systemctl restart ssh
    success "SSH настроен безопасно"
else
    cp "$SSH_BACKUP" "$SSH_CONFIG"
    systemctl restart ssh
    error "Ошибка SSH конфига, восстановлено из резервной копии"
fi
echo ""
((STEP_COUNT++))

# Шаг 3: Portsentry
info "Шаг $STEP_COUNT/$TOTAL_STEPS: Portsentry (защита от сканирования портов)..."
if ! command -v portsentry &> /dev/null; then
    apt install -y -qq portsentry
    sed -i 's/BLOCK_TCP="0"/BLOCK_TCP="1"/' /etc/portsentry/portsentry.conf
    sed -i 's/BLOCK_UDP="0"/BLOCK_UDP="1"/' /etc/portsentry/portsentry.conf
    # iptables вместо route для блокировки (более надёжно)
    sed -i 's|KILL_ROUTE=.*|KILL_ROUTE="/sbin/iptables -I INPUT -s $TARGET$ -j DROP"|' /etc/portsentry/portsentry.conf
    systemctl enable portsentry
    systemctl start portsentry
    success "Portsentry установлен"
else
    warning "Portsentry уже установлен"
fi
echo ""
((STEP_COUNT++))

# Шаг 4: Дополнительные правила firewall, iptables, sysctl
info "Шаг $STEP_COUNT/$TOTAL_STEPS: Дополнительная защита (firewall, iptables, sysctl)..."

if command -v ufw &> /dev/null; then
    ufw limit ssh/tcp comment 'SSH rate limit' 2>/dev/null || true
    ufw deny 23/tcp comment 'Block Telnet' 2>/dev/null || true
    ufw deny 135/tcp comment 'Block RPC' 2>/dev/null || true
    ufw deny 139/tcp comment 'Block NetBIOS' 2>/dev/null || true
    ufw deny 445/tcp comment 'Block SMB' 2>/dev/null || true
    ufw deny 1433/tcp comment 'Block MSSQL' 2>/dev/null || true
    ufw deny 3306/tcp comment 'Block MySQL' 2>/dev/null || true
    success "Дополнительные правила firewall применены"
fi

if command -v iptables &> /dev/null; then
    if ! iptables -C INPUT -p tcp --dport ssh -m state --state NEW -m recent --set --name SSH 2>/dev/null; then
        iptables -A INPUT -p tcp --dport ssh -m state --state NEW -m recent --set --name SSH
        iptables -A INPUT -p tcp --dport ssh -m state --state NEW -m recent --update --seconds 60 --hitcount 4 --name SSH -j DROP
        success "Rate limiting SSH (iptables)"
    fi
    if ! iptables -C INPUT -p tcp --syn -m limit --limit 1/s --limit-burst 3 -j ACCEPT 2>/dev/null; then
        iptables -I INPUT -p tcp --syn -m limit --limit 1/s --limit-burst 3 -j ACCEPT
        iptables -A INPUT -p tcp --syn -j DROP
        success "Защита от SYN flood"
    fi
    if ! iptables -C INPUT -s 127.0.0.0/8 ! -i lo -j DROP 2>/dev/null; then
        iptables -A INPUT -s 127.0.0.0/8 ! -i lo -j DROP
        iptables -A INPUT -s 0.0.0.0/8 -j DROP
        iptables -A INPUT -d 0.0.0.0/8 -j DROP
        iptables -A INPUT -d 255.255.255.255 -j DROP
        success "Защита от IP spoofing"
    fi
fi

grep -q "net.ipv4.tcp_syncookies" /etc/sysctl.conf 2>/dev/null || cat >> /etc/sysctl.conf << 'EOF'

# HomeVPN security
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_max_syn_backlog = 2048
net.ipv4.tcp_synack_retries = 2
net.ipv4.tcp_syn_retries = 5
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.default.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv6.conf.all.accept_source_route = 0
net.ipv6.conf.default.accept_source_route = 0
net.ipv4.conf.all.log_martians = 1
net.ipv4.conf.default.log_martians = 1
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.icmp_ignore_bogus_error_responses = 1
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
EOF
sysctl -p > /dev/null 2>&1
success "sysctl настроен"
echo ""

# Итог
success "═══════════════════════════════════════════════════════════"
success "  Настройка безопасности завершена! 🔒"
success "═══════════════════════════════════════════════════════════"
echo ""
info "fail2ban:     sudo fail2ban-client status sshd"
info "firewall:     sudo ufw status verbose"
echo ""
