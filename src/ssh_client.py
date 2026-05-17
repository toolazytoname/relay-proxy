"""
SSH Client - Paramiko SSH 连接池管理
参考: 最小权限账号 + 连接复用
"""

import threading
import time
from typing import Optional
from dataclasses import dataclass
from paramiko import SSHClient, AutoAddPolicy

# 锁，保证连接池线程安全
_pool_lock = threading.Lock()


@dataclass
class SSHConnection:
    """SSH 连接包装"""
    client: SSHClient
    server_name: str
    last_used: float
    in_use: bool = False


class SSHClientPool:
    """
    SSH 连接池
    - 每台服务器一个连接
    - 空闲 5 分钟自动关闭
    - 线程安全
    """

    POOL_TIMEOUT = 300  # 5 分钟空闲超时

    def __init__(self):
        self._pool: dict[str, SSHConnection] = {}
        self._keys: dict[str, str] = {}  # server_name -> private_key

    def register_key(self, server_name: str, private_key: str) -> None:
        """注册服务器的 SSH 私钥（从 Fly.io Secrets 加载到内存）"""
        self._keys[server_name] = private_key

    def execute(
        self,
        server_name: str,
        server_config: dict,
        command: str,
        timeout: int = 30,
    ) -> tuple[int, str, str]:
        """
        在服务器上执行命令
        Returns: (exit_code, stdout, stderr)
        """
        with _pool_lock:
            # 获取或创建连接
            conn = self._get_conn(server_name, server_config)
            if conn is None:
                return -1, "", f"无法连接到服务器: {server_name}"

        # 执行命令（不在锁内执行，避免阻塞）
        try:
            stdin, stdout, stderr = conn.client.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            return exit_code, out, err
        except Exception as e:
            return -1, "", str(e)
        finally:
            # 标记连接为空闲
            with _pool_lock:
                if server_name in self._pool:
                    self._pool[server_name].in_use = False
                    self._pool[server_name].last_used = time.time()

    def _get_conn(self, server_name: str, server_config: dict) -> Optional[SSHConnection]:
        """获取或创建 SSH 连接"""
        now = time.time()

        # 检查现有连接
        if server_name in self._pool:
            conn = self._pool[server_name]
            # 检查空闲超时
            if now - conn.last_used > self.POOL_TIMEOUT:
                conn.client.close()
                del self._pool[server_name]
            elif not conn.in_use:
                conn.in_use = True
                conn.last_used = now
                return conn

        # 创建新连接
        if server_name not in self._keys:
            return None

        client = SSHClient()
        client.set_host_keys_policy(AutoAddPolicy())

        host = server_config.get("host")
        port = server_config.get("port", 22)
        user = server_config.get("user", "relay")
        key_str = self._keys[server_name]

        # 解析私钥（支持 Ed25519 / RSA）
        from io import StringIO
        from paramiko import Ed25519Key, RSAKey

        try:
            # 尝试 Ed25519
            key = Ed25519Key.from_private_key(StringIO(key_str))
        except Exception:
            try:
                # 尝试 RSA
                key = RSAKey.from_private_key(StringIO(key_str))
            except Exception:
                # 尝试 OpenSSL 格式
                from paramiko import PKey
                key = PKey.from_private_key_file(StringIO(key_str))

        client.connect(
            hostname=host,
            port=port,
            username=user,
            pkey=key,
            timeout=10,
            look_for_keys=False,
            allow_agent=False,
        )

        conn = SSHConnection(
            client=client,
            server_name=server_name,
            last_used=now,
            in_use=True,
        )
        self._pool[server_name] = conn
        return conn

    def close(self, server_name: str) -> None:
        """关闭指定服务器的连接"""
        with _pool_lock:
            if server_name in self._pool:
                self._pool[server_name].client.close()
                del self._pool[server_name]

    def close_all(self) -> None:
        """关闭所有连接"""
        with _pool_lock:
            for conn in self._pool.values():
                conn.client.close()
            self._pool.clear()
