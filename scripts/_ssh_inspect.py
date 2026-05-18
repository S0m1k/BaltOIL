"""Quick SSH inspection helper. Reads commands from argv and runs them via paramiko."""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import paramiko

HOST = "5.42.118.110"
USER = "root"
PASSWORD = "s8.u-5HnDd6xFC"


def main():
    cmds = sys.argv[1:]
    if not cmds:
        print("usage: _ssh_inspect.py 'cmd1' ['cmd2' ...]")
        return 2

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=20, allow_agent=False, look_for_keys=False)
    try:
        for cmd in cmds:
            print(f"\n===== $ {cmd} =====")
            stdin, stdout, stderr = client.exec_command(cmd, timeout=60)
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            rc = stdout.channel.recv_exit_status()
            sys.stdout.write(out)
            if err:
                sys.stdout.write("--- stderr ---\n" + err)
            print(f"--- exit: {rc} ---")
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
