"""Upload a single local file to the remote server via SFTP."""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import paramiko

HOST = "5.42.118.110"
USER = "root"
PASSWORD = "s8.u-5HnDd6xFC"


def main():
    if len(sys.argv) != 3:
        print("usage: _ssh_upload.py <local-path> <remote-path>")
        return 2
    local, remote = sys.argv[1], sys.argv[2]
    transport = paramiko.Transport((HOST, 22))
    transport.connect(username=USER, password=PASSWORD)
    try:
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.put(local, remote)
        st = sftp.stat(remote)
        print(f"uploaded {local} -> {remote} ({st.st_size} bytes)")
        sftp.close()
    finally:
        transport.close()


if __name__ == "__main__":
    sys.exit(main() or 0)
