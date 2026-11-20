import subprocess


def shut_down_pi():
    subprocess.run(
        ["sudo", "/sbin/shutdown", "-h", "now"],
        check=True
    )
    