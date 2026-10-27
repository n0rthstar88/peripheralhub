import subprocess

from peripheralhub.core.systemd import service_active


def test_service_active_maps_exit_code():
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    assert service_active(run)
    assert calls[0][:3] == ["systemctl", "--user", "is-active"]
    assert not service_active(lambda cmd, **kw: subprocess.CompletedProcess(cmd, 3))


def test_service_active_false_when_systemctl_missing():
    def run(cmd, **kw):
        raise FileNotFoundError(cmd[0])

    assert not service_active(run)
