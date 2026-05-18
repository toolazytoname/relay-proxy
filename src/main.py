"""
Relay Server - FastAPI 主入口
整合 Auth + Permission Engine + SSH Client + Audit Logger
"""

import os
import time
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .auth import AuthLayer
from .permission_engine import PermissionEngine, CheckResult
from .ssh_client import SSHClientPool
from .audit_logger import AuditLogger

try:
    from paramiko import Ed25519Key
except ImportError:
    Ed25519Key = None


# ============================================================
# 配置
# ============================================================

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "dev-admin-token-change-me")
MANIFEST_PATH = Path(os.environ.get("MANIFEST_PATH", "/opt/relay-proxy/config/permission_manifest.yaml"))

# 从环境变量加载 SSH 私钥
SSH_KEYS = {}
for key, value in os.environ.items():
    if key.startswith("SSH_KEY_"):
        server_name = key[8:].lower().replace("_", "-")
        SSH_KEYS[server_name] = value


# ============================================================
# 生命周期
# ============================================================

auth_layer = AuthLayer()
perm_engine = PermissionEngine(MANIFEST_PATH) if MANIFEST_PATH.exists() else PermissionEngine()
ssh_pool = SSHClientPool()
audit_logger = AuditLogger()

# 注册 SSH 密钥
for server_name, key in SSH_KEYS.items():
    ssh_pool.register_key(server_name, key)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时：加载权限清单
    if MANIFEST_PATH.exists():
        perm_engine.load_manifest(MANIFEST_PATH)
    yield
    # 关闭时：关闭所有 SSH 连接
    ssh_pool.close_all()


# ============================================================
# FastAPI App
# ============================================================

app = FastAPI(
    title="Relay Proxy",
    description="AI Agent 服务器授信操作中间层",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# 请求模型
# ============================================================

class AuthRequest(BaseModel):
    agent_id: str
    scope: list[str]  # 服务器列表


class AuthResponse(BaseModel):
    token: str
    session_id: str
    expires_in: int


class ExecRequest(BaseModel):
    server: str
    command: str
    timeout: int = 30


class ExecResponse(BaseModel):
    status: str  # success / denied / error
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None
    reason: Optional[str] = None
    suggestion: Optional[dict] = None
    log_id: Optional[str] = None


class IntentGenerateRequest(BaseModel):
    description: str


class IntentResponse(BaseModel):
    matched_intents: list[str]
    policy: dict
    warnings: list[str]


class PendingApproveRequest(BaseModel):
    permanent: bool = True


# ============================================================
# 辅助函数
# ============================================================

def verify_admin(token: Optional[str] = Header(None)) -> bool:
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="管理员认证失败")
    return True


# ============================================================
# API 路由
# ============================================================

# ---- 公开接口（Agent 调用）----

@app.post("/auth/request", response_model=AuthResponse)
async def auth_request(body: AuthRequest):
    """申请临时 Token"""
    token = auth_layer.create_token(
        agent_id=body.agent_id,
        scope=body.scope,
    )
    return AuthResponse(
        token=token.token,
        session_id=token.session_id,
        expires_in=8 * 3600,
    )


@app.post("/auth/refresh")
async def auth_refresh(authorization: str = Header(...)):
    """刷新 Token"""
    token_str = authorization.replace("Bearer ", "")
    valid, token, reason = auth_layer.verify_token(token_str)
    if not valid:
        raise HTTPException(status_code=401, detail=reason)

    # 创建新 Token，同一 session
    new_token = auth_layer.create_token(
        agent_id=token.agent_id,
        scope=token.scope,
    )
    return {"token": new_token.token, "expires_in": 8 * 3600}


@app.post("/exec", response_model=ExecResponse)
async def exec_command(body: ExecRequest, authorization: str = Header(...)):
    """执行命令"""
    # 1. 验证 Token
    token_str = authorization.replace("Bearer ", "")
    valid, token, reason = auth_layer.verify_token(token_str)
    if not valid:
        raise HTTPException(status_code=401, detail=reason)

    if body.server not in token.scope:
        raise HTTPException(status_code=403, detail=f"该服务器不在授权范围: {body.server}")

    # 2. 权限检查
    check = perm_engine.check(body.command, body.server)

    # 3. 获取服务器配置
    server_config = None
    for srv in perm_engine.manifest.servers:
        if srv.get("name") == body.server:
            server_config = srv
            break

    # 4. 审计日志（记录请求）
    start_ms = int(time.time() * 1000)

    if check.status == CheckResult.DENIED:
        # 拒绝：记录拒绝日志
        log_id = audit_logger.log(
            session_id=token.session_id,
            token_id=token.token,
            request_raw=body.command,
            request_parsed={"action": body.command},
            server=body.server,
            policy_matched=body.server,
            command_checked=body.command,
            policy_allowed=False,
            policy_reason=check.reason,
            status="denied",
            message=check.reason,
        )

        # 运行时权限发现：加入待确认队列
        if check.suggestion:
            perm_engine.add_pending_permission(
                session_id=token.session_id,
                agent_id=token.agent_id,
                server=body.server,
                denied_command=body.command,
                suggestion=check.suggestion,
            )

        return ExecResponse(
            status="denied",
            reason=check.reason,
            suggestion=check.suggestion,
            log_id=log_id,
        )

    # 5. 通过权限检查，执行命令
    if server_config is None:
        return ExecResponse(
            status="error",
            reason=f"未找到服务器配置: {body.server}",
        )

    exit_code, stdout, stderr = ssh_pool.execute(
        server_name=body.server,
        server_config=server_config,
        command=body.command,
        timeout=body.timeout,
    )

    duration_ms = int(time.time() * 1000) - start_ms

    # 6. 记录执行日志
    log_id = audit_logger.log(
        session_id=token.session_id,
        token_id=token.token,
        request_raw=body.command,
        request_parsed={"action": body.command},
        server=body.server,
        policy_matched=body.server,
        command_checked=body.command,
        policy_allowed=True,
        policy_reason="OK",
        status="success" if exit_code == 0 else "error",
        message="命令执行完成",
        ssh_session_id=body.server,
        command_executed=body.command,
        exit_code=exit_code,
        duration_ms=duration_ms,
    )

    return ExecResponse(
        status="success",
        stdout=stdout[:5000],  # 限制输出长度
        stderr=stderr[:2000],
        exit_code=exit_code,
        duration_ms=duration_ms,
        log_id=log_id,
    )


@app.get("/status")
async def status(authorization: Optional[str] = Header(None)):
    """服务器在线状态（Token 验证可选）"""
    servers = []
    for srv in perm_engine.manifest.servers:
        name = srv.get("name")
        host = srv.get("host")
        # 简单的 ping 检测
        start = time.time()
        try:
            exit_code, _, _ = ssh_pool.execute(name, srv, "echo ok", timeout=5)
            latency = int((time.time() - start) * 1000)
            servers.append({
                "name": name,
                "host": host,
                "online": exit_code == 0,
                "latency_ms": latency,
            })
        except Exception:
            servers.append({
                "name": name,
                "host": host,
                "online": False,
                "latency_ms": None,
            })
    return {"servers": servers}


# ---- 管理接口（管理员调用）----

@app.get("/admin/sessions")
async def admin_sessions(admin_token: str = Header(None, alias="X-Admin-Token")):
    """列出活跃会话"""
    verify_admin(admin_token)
    sessions = auth_layer.list_active_sessions()
    return {
        "sessions": [
            {
                "session_id": s.session_id,
                "agent_id": s.agent_id,
                "scope": s.scope,
                "created_at": s.created_at,
                "expires_at": s.expires_at,
            }
            for s in sessions
        ]
    }


@app.post("/admin/sessions/revoke/{session_id}")
async def admin_revoke_session(
    session_id: str,
    admin_token: str = Header(None, alias="X-Admin-Token"),
):
    """撤销指定会话"""
    verify_admin(admin_token)
    ok, msg = auth_layer.revoke_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail=msg)
    return {"status": "ok", "message": f"会话已撤销: {session_id}"}


@app.post("/admin/sessions/revoke/all")
async def admin_revoke_all(admin_token: str = Header(None, alias="X-Admin-Token")):
    """撤销所有会话"""
    verify_admin(admin_token)
    count = auth_layer.revoke_all()
    return {"status": "ok", "revoked_count": count}


@app.get("/admin/audit")
async def admin_audit(
    admin_token: str = Header(None, alias="X-Admin-Token"),
    session_id: Optional[str] = None,
    server: Optional[str] = None,
    status_filter: Optional[str] = None,
    date: Optional[str] = None,
    limit: int = 100,
):
    """查询审计日志"""
    verify_admin(admin_token)
    logs = audit_logger.query(
        date=date,
        session_id=session_id,
        server=server,
        status=status_filter,
        limit=limit,
    )
    return {"logs": logs}


@app.get("/admin/pending")
async def admin_pending(admin_token: str = Header(None, alias="X-Admin-Token")):
    """查看待确认权限请求"""
    verify_admin(admin_token)
    return {"pending": perm_engine.list_pending()}


@app.post("/admin/pending/{pending_id}/approve")
async def admin_pending_approve(
    pending_id: str,
    body: PendingApproveRequest,
    admin_token: str = Header(None, alias="X-Admin-Token"),
):
    """批准待确认权限请求"""
    verify_admin(admin_token)
    # pending_id 中包含了目标服务器信息，需要从 pending 列表中找到
    pending_list = perm_engine.list_pending()
    target = None
    for p in pending_list:
        if p["pending_id"] == pending_id:
            target = p
            break
    if not target:
        raise HTTPException(status_code=404, detail="未找到待确认请求")

    ok, msg = perm_engine.approve_pending(pending_id, target["server"], body.permanent)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "ok", "message": msg}


@app.post("/admin/intent/generate", response_model=IntentResponse)
async def intent_generate(
    body: IntentGenerateRequest,
    admin_token: str = Header(None, alias="X-Admin-Token"),
):
    """根据意图生成权限配置（方案1）"""
    verify_admin(admin_token)
    result = perm_engine.generate_policy_from_intent(body.description)
    return IntentResponse(**result)


@app.post("/admin/keys/generate")
async def generate_key(
    server_name: str,
    admin_token: str = Header(None, alias="X-Admin-Token"),
):
    """为指定服务器生成 SSH 密钥对（需要 admin token）"""
    verify_admin(admin_token)
    if Ed25519Key is None:
        raise HTTPException(status_code=500, detail="paramiko 未安装")

    # 生成密钥对
    key = Ed25519Key.generate()
    from io import StringIO
    private_io = StringIO()
    key.write_private_key(private_io)
    private_key = private_io.getvalue()
    public_key = f"{key.get_name()} {key.get_base64()} relay-proxy-{server_name}"

    # 保存密钥
    keys_dir = Path("/opt/relay-proxy/keys")
    keys_dir.mkdir(parents=True, exist_ok=True)

    private_path = keys_dir / f"{server_name}_ed25519"
    private_path.write_text(private_key)
    private_path.chmod(0o600)

    public_path = keys_dir / f"{server_name}_ed25519.pub"
    public_path.write_text(public_key + "\n")
    public_path.chmod(0o644)

    # 注册到 SSH 连接池
    ssh_pool.register_key(server_name, private_key)

    return {"server_name": server_name, "public_key": public_key}


@app.get("/pubkey/{server_name}")
async def get_server_pubkey(server_name: str):
    """返回指定服务器的 SSH 公钥"""
    keys_dir = Path("/opt/relay-proxy/keys")
    public_path = keys_dir / f"{server_name}_ed25519.pub"
    if public_path.exists():
        return public_path.read_text().strip()
    raise HTTPException(status_code=404, detail=f"未找到 {server_name} 的公钥")


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok", "version": "1.0.0"}
