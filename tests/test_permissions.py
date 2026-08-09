from pathlib import Path
import pytest
from boltpy.agent.permissions import PermissionDecision, PermissionManager, PermissionRequest, PermissionStore

@pytest.mark.asyncio
async def test_allow_permanently_persists_exact_shell_command(tmp_path: Path):
    store = PermissionStore(tmp_path / "permissions.toml")
    manager = PermissionManager(store=store, handler=lambda request: PermissionDecision.ALLOW_PERMANENT)
    request = PermissionRequest("run_shell", "shell.execute", {"command": "git status"})
    assert await manager.authorize(request) == PermissionDecision.ALLOW_PERMANENT
    assert "git status" in (tmp_path / "permissions.toml").read_text()
    restored = PermissionManager(store=PermissionStore(tmp_path / "permissions.toml"))
    assert await restored.authorize(request) == PermissionDecision.ALLOW_PERMANENT
    other = PermissionRequest("run_shell", "shell.execute", {"command": "git diff"})
    assert await restored.authorize(other) == PermissionDecision.DENY

@pytest.mark.asyncio
async def test_ssh_permanent_scope_includes_target(tmp_path: Path):
    store = PermissionStore(tmp_path / "permissions.toml")
    manager = PermissionManager(store=store, handler=lambda request: PermissionDecision.ALLOW_PERMANENT)
    request = PermissionRequest("ssh", "ssh.execute", {"host": "dev", "command": "df -h", "user": "alice", "port": 22})
    assert await manager.authorize(request) == PermissionDecision.ALLOW_PERMANENT
    restored = PermissionManager(store=PermissionStore(tmp_path / "permissions.toml"))
    assert await restored.authorize(request) == PermissionDecision.ALLOW_PERMANENT
    different_host = PermissionRequest("ssh", "ssh.execute", {"host": "prod", "command": "df -h", "user": "alice", "port": 22})
    assert await restored.authorize(different_host) == PermissionDecision.DENY
    assert restored.remove_permanent("ssh", "dev|alice|22|df -h")
    assert await restored.authorize(request) == PermissionDecision.DENY
