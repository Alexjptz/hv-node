"""gRPC client for XRay HandlerService API."""
import json
import subprocess
from typing import Any

import grpc

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Импортируем сгенерированные proto файлы
try:
    import sys
    from pathlib import Path
    proto_path = Path(__file__).parent.parent / "proto"
    if str(proto_path) not in sys.path:
        sys.path.insert(0, str(proto_path))

    import command_pb2
    import command_pb2_grpc
    from common.protocol import user_pb2
    from common.serial import typed_message_pb2
    from proxy.vless import account_pb2

    PROTO_AVAILABLE = True
except ImportError as e:
    logger.warning("Proto files not available, will use fallback", error=str(e))
    PROTO_AVAILABLE = False


class XRayGRPCClient:
    """gRPC client for XRay HandlerService API.

    Использует прямой gRPC вызов через Python grpc библиотеку.
    Fallback на SIGHUP если gRPC недоступен.
    """

    def __init__(self, api_address: str | None = None):
        """Initialize gRPC client.

        Args:
            api_address: XRay API address (default: from settings)
        """
        self.api_address = api_address or settings.xray_api_address
        # XRay API работает внутри контейнера xray_server на 127.0.0.1:10085
        # Но мы в контейнере xray_agent, поэтому используем имя контейнера
        # Или можно использовать host.docker.internal если доступно
        self.grpc_address = self._get_grpc_address()
        self._channel: grpc.Channel | None = None
        self._stub: command_pb2_grpc.HandlerServiceStub | None = None

        if PROTO_AVAILABLE:
            try:
                self._channel = grpc.insecure_channel(self.grpc_address)
                self._stub = command_pb2_grpc.HandlerServiceStub(self._channel)
                logger.debug("gRPC channel and stub created", address=self.grpc_address)
            except Exception as e:
                logger.warning("Failed to create gRPC channel, will use fallback", error=str(e))
                self._channel = None
                self._stub = None

    def _get_grpc_address(self) -> str:
        """Get gRPC server address.

        XRay API работает внутри контейнера xray_server на 127.0.0.1:10085.
        Из контейнера xray_agent нужно подключиться через docker network.

        Returns:
            gRPC server address
        """
        # Пробуем подключиться через docker network имя контейнера
        # Или используем host.docker.internal если доступно
        # Или используем IP адрес контейнера xray_server
        return "homevpn_xray_server:10085"  # Через docker network

    def _call_xray_api_via_command(self, command: str, user_json: str) -> bool:
        """Call XRay API using xray api command (adu/rmu).

        Args:
            command: Command name ("adu" for add user, "rmu" for remove user)
            user_json: JSON string with user data

        Returns:
            True if successful, False otherwise
        """
        try:
            # Используем команду xray api adu/rmu через docker exec
            # Формат: echo '{"email":"...","level":0,"account":{"id":"...","flow":"..."}}' | xray api adu vless
            cmd = [
                "docker",
                "exec",
                "-i",  # Interactive mode для stdin
                "homevpn_xray_server",
                "xray",
                "api",
                command,
                "vless",
            ]

            result = subprocess.run(
                cmd,
                input=user_json,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                logger.debug("XRay API command successful", command=command)
                return True
            else:
                logger.error(
                    "XRay API command failed",
                    command=command,
                    stderr=result.stderr,
                    stdout=result.stdout,
                    returncode=result.returncode,
                )
                return False

        except subprocess.TimeoutExpired:
            logger.error("XRay API command timeout", command=command)
            return False
        except Exception as e:
            logger.error("Error calling XRay API command", command=command, error=str(e))
            return False

    def add_user(self, tag: str, user_uuid: str, email: str, flow: str = "xtls-rprx-vision") -> bool:
        """Add user to XRay via HandlerService API using direct gRPC call.

        Args:
            tag: Inbound tag (usually "vless")
            user_uuid: UUID for VLESS user
            email: Email for user identification
            flow: Flow type (default: "xtls-rprx-vision")

        Returns:
            True if successful, False otherwise
        """
        if not PROTO_AVAILABLE or not self._stub:
            logger.debug("gRPC not available, will use fallback", user_uuid=user_uuid)
            return False

        try:
            # Создаем VLESS Account
            vless_account = account_pb2.Account()
            vless_account.id = user_uuid
            vless_account.flow = flow

            # Создаем TypedMessage для Account (для User.account)
            # Используем полное имя типа БЕЗ префикса type.googleapis.com/
            account_msg = typed_message_pb2.TypedMessage()
            account_msg.type = vless_account.DESCRIPTOR.full_name
            account_msg.value = vless_account.SerializeToString()

            # Создаем User
            user = user_pb2.User()
            user.email = email
            user.level = 0
            user.account.CopyFrom(account_msg)

            # Создаем AddUserOperation
            add_op = command_pb2.AddUserOperation()
            add_op.user.CopyFrom(user)

            # Создаем TypedMessage для операции AlterInbound
            # Используем полное имя типа БЕЗ префикса type.googleapis.com/
            # XRay ожидает формат: xray.app.proxyman.command.AddUserOperation
            operation_msg = typed_message_pb2.TypedMessage()
            operation_msg.type = add_op.DESCRIPTOR.full_name
            operation_msg.value = add_op.SerializeToString()

            # Создаем AlterInboundRequest
            request = command_pb2.AlterInboundRequest()
            request.tag = tag
            request.operation.CopyFrom(operation_msg)

            # Вызываем gRPC метод
            response = self._stub.AlterInbound(request, timeout=10)

            logger.info("User added via direct gRPC API", user_uuid=user_uuid, email=email)
            return True

        except grpc.RpcError as e:
            logger.error("gRPC error adding user", user_uuid=user_uuid, error=str(e), code=e.code())
            return False
        except Exception as e:
            logger.error("Error adding user via gRPC API", user_uuid=user_uuid, error=str(e))
            return False

    def remove_user(self, tag: str, user_uuid: str, email: str | None = None) -> bool:
        """Remove user from XRay via HandlerService API using direct gRPC call.

        Args:
            tag: Inbound tag (usually "vless")
            user_uuid: UUID of user to remove
            email: Email of user (if None, will be found from config)

        Returns:
            True if successful, False otherwise
        """
        if not PROTO_AVAILABLE or not self._stub:
            logger.debug("gRPC not available, will use fallback", user_uuid=user_uuid)
            return False

        try:
            # Если email не передан, найти его по UUID из конфига
            if not email:
                email = self._find_email_by_uuid(user_uuid, tag)
                if not email:
                    logger.warning("Could not find email for user UUID, using fallback", user_uuid=user_uuid)
                    return False

            # Создаем RemoveUserOperation
            remove_op = command_pb2.RemoveUserOperation()
            remove_op.email = email

            # Создаем TypedMessage для операции AlterInbound
            # Используем полное имя типа БЕЗ префикса type.googleapis.com/
            # XRay ожидает формат: xray.app.proxyman.command.RemoveUserOperation
            operation_msg = typed_message_pb2.TypedMessage()
            operation_msg.type = remove_op.DESCRIPTOR.full_name
            operation_msg.value = remove_op.SerializeToString()

            # Создаем AlterInboundRequest
            request = command_pb2.AlterInboundRequest()
            request.tag = tag
            request.operation.CopyFrom(operation_msg)

            # Вызываем gRPC метод
            response = self._stub.AlterInbound(request, timeout=10)

            logger.info("User removed via direct gRPC API", user_uuid=user_uuid, email=email)
            return True

        except grpc.RpcError as e:
            logger.error("gRPC error removing user", user_uuid=user_uuid, error=str(e), code=e.code())
            return False
        except Exception as e:
            logger.error("Error removing user via gRPC API", user_uuid=user_uuid, error=str(e))
            return False

    def _find_email_by_uuid(self, user_uuid: str, tag: str = "vless") -> str | None:
        """Find user email by UUID from XRay config.

        Args:
            user_uuid: UUID of user
            tag: Inbound tag (usually "vless")

        Returns:
            Email if found, None otherwise
        """
        try:
            from app.services.xray_manager import load_xray_config

            config = load_xray_config()
            for inbound in config.get("inbounds", []):
                if inbound.get("tag") == tag or inbound.get("protocol") == "vless":
                    clients = inbound.get("settings", {}).get("clients", [])
                    for client in clients:
                        if client.get("id") == user_uuid:
                            return client.get("email")
            return None
        except Exception as e:
            logger.error("Error finding email by UUID", user_uuid=user_uuid, error=str(e))
            return None

    def is_available(self) -> bool:
        """Проверить доступность gRPC API.

        Returns:
            True если API доступен, False иначе
        """
        if not PROTO_AVAILABLE:
            return False

        try:
            # Пробуем подключиться через socket
            import socket
            host, port = self.grpc_address.split(":")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((host, int(port)))
            sock.close()
            return result == 0

        except Exception as e:
            logger.debug("Error checking gRPC availability", error=str(e))
            return False


# Глобальный экземпляр клиента
grpc_client = XRayGRPCClient()
