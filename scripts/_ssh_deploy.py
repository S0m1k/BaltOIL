"""SSH deploy helper. Runs a shell script on the remote host."""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import paramiko

HOST = "5.42.118.110"
USER = "root"
PASSWORD = "s8.u-5HnDd6xFC"


def run(script: str, timeout: int = 600) -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=20, allow_agent=False, look_for_keys=False)
    try:
        # Send the whole script via stdin to bash -s
        chan = client.get_transport().open_session()
        chan.settimeout(timeout)
        chan.exec_command("bash -s")
        chan.sendall(script.encode("utf-8"))
        chan.shutdown_write()
        # Stream until EOF on both stdout and stderr. recv() returning b''
        # is the only reliable signal that the remote side has closed the stream.
        import time, select
        out_open = True
        err_open = True
        while out_open or err_open:
            r, _, _ = select.select([chan], [], [], 1.0)
            if chan.recv_ready():
                data = chan.recv(65536)
                if not data:
                    out_open = False
                else:
                    sys.stdout.write(data.decode("utf-8", errors="replace"))
                    sys.stdout.flush()
            if chan.recv_stderr_ready():
                data = chan.recv_stderr(65536)
                if not data:
                    err_open = False
                else:
                    sys.stdout.write(data.decode("utf-8", errors="replace"))
                    sys.stdout.flush()
            if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                # Give a short grace period for any final bytes
                time.sleep(0.2)
                if not chan.recv_ready() and not chan.recv_stderr_ready():
                    break
        rc = chan.recv_exit_status()
        sys.stdout.write(f"\n--- exit: {rc} ---\n")
        return rc
    finally:
        client.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: _ssh_deploy.py <script-file>")
        sys.exit(2)
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        script = f.read()
    sys.exit(run(script))
