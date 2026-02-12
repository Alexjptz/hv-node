# HomeVPN — VPN Node

Пакет для поднятия VPN-ноды в один клик. Подключается к HomeVPN Core API и управляется через админ-панель.

## Что здесь находится
- `install-vpn-server.sh` — основной установщик (ставит Docker, поднимает `xray-server` + `xray-agent`, создает `.env`, настраивает firewall)
- `setup-vpn-server.sh` — дополнительное усиление безопасности хоста (fail2ban, SSH hardening, portsentry, sysctl, iptables)
- `xray-agent/` — код агента, который регистрируется в Core API и принимает команды

## Что нужно подготовить заранее
- 1 VPS с Ubuntu и доступом по SSH
- данные из вашей админки/базы:
  - `CORE_API_URL` (например `https://api.example.com:8000`)
  - `CORE_API_IP` (IP сервера Core API; только ему будет открыт доступ к порту `8080`)
  - `AGENT_API_KEY`
  - `SERVER_ID`

## Шаг 1. Подключиться к серверу
```bash
ssh root@YOUR_SERVER_IP
```

## Шаг 2. Установить VPN-ноду (основной шаг)
```bash
curl -sSL https://raw.githubusercontent.com/Alexjptz/HomeVPN-VPN-Node/main/install-vpn-server.sh | bash
```

Скрипт спросит:
- `CORE_API_URL` (обязательно)
- `CORE_API_IP` (обязательно)
- `AGENT_API_KEY`
- `SERVER_ID`

Что сделает скрипт:
- установит Docker и Docker Compose (если их нет)
- откроет порт `433/tcp` и `433/udp` для VPN
- откроет `8080/tcp` только для `CORE_API_IP`
- запустит `xray-server` и `xray-agent`

## Шаг 3. Проверить, что всё запущено
```bash
cd /root/homevpn-vpn-server
docker compose ps
curl http://localhost:8080/health
```

Ожидаемо:
- сервисы в статусе `Up`
- health check возвращает `{"status":"healthy","service":"xray-agent"}`

## Шаг 4 (опционально, но рекомендуется). Усилить безопасность хоста
```bash
curl -sSL https://raw.githubusercontent.com/Alexjptz/HomeVPN-VPN-Node/main/setup-vpn-server.sh -o setup-vpn-server.sh
chmod +x setup-vpn-server.sh
sudo ./setup-vpn-server.sh --prod
```

Этот шаг настраивает:
- fail2ban
- SSH только по ключам
- portsentry
- дополнительные правила UFW/iptables/sysctl

## Что актуально использовать
- Для запуска новой ноды: `install-vpn-server.sh`
- Для дополнительной защиты после запуска: `setup-vpn-server.sh`

## Важно
- Текущий рабочий VPN-порт в установщике: `433` (TCP/UDP)
- Порт `8080` не открыт в интернет, доступ только с `CORE_API_IP`
