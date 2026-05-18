"""Reliable upload: stream local file to remote via ssh + cat."""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import paramiko
from pathlib import Path

HOST = "5.42.118.110"
USER = "root"
PASSWORD = "s8.u-5HnDd6xFC"


def upload(local: str, remote: str) -> int:
    data = Path(local).read_bytes()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=20, allow_agent=False, look_for_keys=False)
    try:
        chan = client.get_transport().open_session()
        chan.settimeout(60)
        # Use a temp file then atomic rename — avoids partial writes.
        tmp = remote + ".tmp.upload"
        chan.exec_command(f"cat > {tmp} && mv {tmp} {remote} && echo OK")
        chan.sendall(data)
        chan.shutdown_write()
        out = b""
        err = b""
        while True:
            if chan.recv_ready():
                out += chan.recv(65536)
            if chan.recv_stderr_ready():
                err += chan.recv_stderr(65536)
            if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                break
        rc = chan.recv_exit_status()
        print(f"{local} -> {remote}: rc={rc} out={out.decode(errors='replace').strip()!r} err={err.decode(errors='replace').strip()!r}")
        return rc
    finally:
        client.close()


if __name__ == "__main__":
    # args: pairs of local remote
    args = sys.argv[1:]
    if len(args) % 2 != 0 or not args:
        print("usage: _ssh_upload2.py <local> <remote> [<local> <remote> ...]")
        sys.exit(2)
    rc = 0
    for i in range(0, len(args), 2):
        r = upload(args[i], args[i+1])
        if r != 0:
            rc = r
    sys.exit(rc)
