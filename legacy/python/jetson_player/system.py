"""파일 관리자 연동, Jetson 하드웨어 상태, 네트워크 주소 등 시스템 유틸리티"""
import glob
import os
import socket
import subprocess
from urllib.request import pathname2url


def open_file_location(filepath):
    """지정된 파일이 위치한 폴더를 리눅스 기본 파일 관리자(Nautilus 등)로 열고 포커스합니다."""
    if not filepath:
        return False
    target = os.path.abspath(filepath)
    if not os.path.exists(target):
        folder = os.path.dirname(target)
        if not os.path.exists(folder):
            return False
        target = folder
    else:
        folder = target if os.path.isdir(target) else os.path.dirname(target)

    # 1. dbus FileManager1 ShowItems 시도 (파일 선택 포커스)
    if os.path.isfile(target):
        try:
            res = subprocess.run(
                ["dbus-send", "--session", "--dest=org.freedesktop.FileManager1",
                 "--type=method_call", "/org/freedesktop/FileManager1",
                 "org.freedesktop.FileManager1.ShowItems",
                 f"array:string:file://{pathname2url(target)}", "string:"],
                capture_output=True, timeout=2
            )
            if res.returncode == 0:
                return True
        except Exception:
            pass

    # 2. xdg-open 폴더 열기
    try:
        subprocess.Popen(["xdg-open", folder])
        return True
    except Exception:
        pass

    # 3. gio open 폴더 열기
    try:
        subprocess.Popen(["gio", "open", folder])
        return True
    except Exception:
        pass

    return False


def get_jetson_hw_stats():
    """Jetson 하드웨어(SoC 온도, GPU 로드, RAM 사용량) 상태를 안전하게 파싱합니다."""
    stats = {}
    try:
        cpu_temps = []
        gpu_temps = []
        for tz in glob.glob("/sys/devices/virtual/thermal/thermal_zone*"):
            type_file = os.path.join(tz, "type")
            temp_file = os.path.join(tz, "temp")
            if os.path.exists(type_file) and os.path.exists(temp_file):
                try:
                    with open(type_file, "r") as f:
                        ztype = f.read().strip().lower()
                    with open(temp_file, "r") as f:
                        temp_val = float(f.read().strip()) / 1000.0
                    if "cpu" in ztype:
                        cpu_temps.append(temp_val)
                    elif "gpu" in ztype:
                        gpu_temps.append(temp_val)
                except Exception:
                    continue
        if cpu_temps:
            stats["cpu_temp"] = sum(cpu_temps) / len(cpu_temps)
        if gpu_temps:
            stats["gpu_temp"] = sum(gpu_temps) / len(gpu_temps)
    except Exception:
        pass

    gpu_load_paths = [
        "/sys/devices/platform/gpu.0/load",
        "/sys/devices/gpu.0/load",
        "/sys/devices/platform/17000000.ga10b/load",
        "/sys/devices/platform/17000000.gv11b/load"
    ]
    for p in gpu_load_paths:
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    raw = float(f.read().strip())
                    stats["gpu_load"] = raw / 10.0 if raw > 100 else raw
                break
            except Exception:
                continue

    try:
        mem_total = 0
        mem_avail = 0
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable:"):
                    mem_avail = int(line.split()[1]) * 1024
        if mem_total > 0:
            mem_used = mem_total - mem_avail
            stats["ram_used_gb"] = mem_used / (1024 ** 3)
            stats["ram_total_gb"] = mem_total / (1024 ** 3)
            stats["ram_percent"] = (mem_used / mem_total) * 100.0
    except Exception:
        pass

    return stats


def get_local_ip():
    """스마트폰 접속을 위한 현재 머신의 로컬 네트워크 IPv4 주소를 감지합니다."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"
