from __future__ import annotations
import os
import time
from typing import Dict, List, Optional

from fastapi import FastAPI, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from openstack import connection
from openstack import exceptions as os_exc

# =========================
# Load .env & Config
# =========================
load_dotenv()

API_KEY = os.getenv("API_KEY", "changeme")
DEFAULT_THRESHOLD = float(os.getenv("MAX_MEM_UTIL", "0.7"))
MIGRATION_SLEEP_SEC = int(os.getenv("MIGRATION_SLEEP_SEC", "5"))
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "10"))
MIGRATION_TIMEOUT_SEC = int(os.getenv("MIGRATION_TIMEOUT_SEC", "1800"))  # 30m
MAX_MOVES_PER_RUN = int(os.getenv("MAX_MOVES_PER_RUN", "20"))
OS_CLOUD = os.getenv("OS_CLOUD")

# =========================
# OpenStack connection
# =========================
def build_connection():
    if OS_CLOUD:
        return connection.from_config(cloud=OS_CLOUD)

    required = [
        "OS_AUTH_URL", "OS_USERNAME", "OS_PASSWORD",
        "OS_PROJECT_NAME", "OS_USER_DOMAIN_NAME", "OS_PROJECT_DOMAIN_NAME"
    ]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise RuntimeError(
            f"Missing OpenStack envs: {', '.join(missing)}. "
            "Isi .env atau gunakan OS_CLOUD + clouds.yaml."
        )

    return connection.Connection(
        auth_url=os.getenv("OS_AUTH_URL"),
        username=os.getenv("OS_USERNAME"),
        password=os.getenv("OS_PASSWORD"),
        project_name=os.getenv("OS_PROJECT_NAME"),
        user_domain_name=os.getenv("OS_USER_DOMAIN_NAME", "Default"),
        project_domain_name=os.getenv("OS_PROJECT_DOMAIN_NAME", "Default"),
        region_name=os.getenv("OS_REGION_NAME"),
        compute_api_version="2.79",
        identity_interface="public",
    )

conn = build_connection()

# =========================
# FastAPI
# =========================
app = FastAPI(title="OpenStack Instance Rebalancer (Memory + Wait)", version="0.5.0")

# =========================
# Models
# =========================
class GrafanaAlert(BaseModel):
    status: str
    commonLabels: Dict[str, str] = Field(default_factory=dict)
    commonAnnotations: Dict[str, str] = Field(default_factory=dict)
    alerts: List[Dict] = Field(default_factory=list)
    target_threshold: Optional[float] = None  # override 0..1

class Host(BaseModel):
    name: str
    mem_total_mb: int
    mem_used_mb: int
    @property
    def util(self) -> float:
        t = max(self.mem_total_mb, 1)
        return self.mem_used_mb / t
    @property
    def free_mb(self) -> int:
        return max(self.mem_total_mb - self.mem_used_mb, 0)

class Instance(BaseModel):
    id: str
    name: str
    ram_mb: int
    host: str

class WebhookResult(BaseModel):
    accepted: bool
    operation_id: str
    message: str

# =========================
# Helpers
# =========================
def _auth(api_key: str):
    if api_key != API_KEY:
        raise HTTPException(401, "invalid api key")

def list_hypervisors() -> List[Host]:
    hosts: List[Host] = []
    for h in conn.compute.hypervisors(details=True):
        total = int(getattr(h, "memory_mb", 0) or 0)
        used = int(getattr(h, "memory_mb_used", 0) or 0)
        hosts.append(Host(name=h.hypervisor_hostname, mem_total_mb=total, mem_used_mb=used))
    return hosts

def get_host(name: str) -> Optional[Host]:
    for h in list_hypervisors():
        if h.name == name:
            return h
    return None

def list_instances_on_host(host: str) -> List[Instance]:
    res: List[Instance] = []
    for s in conn.compute.servers(all_projects=True):
        if not getattr(s, "OS-EXT-SRV-ATTR:host", None):
            s = conn.compute.get_server(s.id)
        srv_host = getattr(s, "OS-EXT-SRV-ATTR:host", None)
        if srv_host != host:
            continue
        # RAM via flavor
        ram_mb = 0
        flav_id = (s.flavor or {}).get("id")
        if flav_id:
            f = conn.compute.get_flavor(flav_id)
            ram_mb = int(getattr(f, "ram", 0) or 0)
        if ram_mb <= 0:
            ram_mb = 512  # fallback
        res.append(Instance(id=s.id, name=s.name, ram_mb=ram_mb, host=srv_host))
    return res

def choose_target_host(src_host: str, threshold: float) -> Optional[Host]:
    hosts = list_hypervisors()
    below = [h for h in hosts if h.name != src_host and h.util < threshold]
    if below:
        return sorted(below, key=lambda h: (h.util, -h.free_mb))[0]
    candidates = [h for h in hosts if h.name != src_host]
    if not candidates:
        return None
    return sorted(candidates, key=lambda h: (h.util, -h.free_mb))[0]

def migrate_instance(inst: Instance, dest_host: str):
    conn.compute.live_migrate_server(
        server=inst.id,
        host=dest_host,
        block_migration=True,   # tidak perlu shared storage
        disk_over_commit=False
    )

def wait_for_migration(server_id: str, expect_host: Optional[str], timeout: int, poll: int):
    """
    Tunggu hingga migrasi selesai (INSTANCE kembali ACTIVE), dan (opsional) host berubah ke expect_host.
    Raise error kalau status ERROR atau timeout.
    """
    deadline = time.time() + timeout
    last_status = ""
    while time.time() < deadline:
        try:
            srv = conn.compute.get_server(server_id)
        except os_exc.ResourceNotFound:
            raise RuntimeError(f"server {server_id} not found")

        status = (srv.status or "").upper()
        host_now = getattr(srv, "OS-EXT-SRV-ATTR:host", None)

        # Logging ringan (opsional: ganti ke logger)
        if status != last_status:
            print(f"[wait] {server_id} status={status} host={host_now}")
            last_status = status

        if status == "ERROR":
            raise RuntimeError(f"Migration failed for {server_id}")
        # Selesai saat ACTIVE & (host match kalau expect_host diberikan)
        if status == "ACTIVE" and (expect_host is None or host_now == expect_host):
            return
        time.sleep(poll)

    raise TimeoutError(f"Timeout waiting migration for {server_id} (wanted host={expect_host})")

# =========================
# Rebalancing core
# =========================
def rebalance_instances_until_below(src_host: str, threshold: float, op_id: str):
    """
    - Pilih target host (di bawah threshold bila ada, atau paling rendah).
    - Pindahkan instance RAM terbesar yg MUAT ke target tanpa membuat target > threshold.
    - Tunggu migrasi SELESAI (polling) sebelum lanjut.
    - Ulangi sampai src_host.util < threshold atau mencapai MAX_MOVES_PER_RUN.
    """
    moves = 0
    while moves < MAX_MOVES_PER_RUN:
        src = get_host(src_host)
        if not src:
            print(f"[{op_id}] source host {src_host} not found")
            return

        print(f"[{op_id}] source {src_host} util={src.util:.3f} (used {src.mem_used_mb}/{src.mem_total_mb} MB)")
        if src.util < threshold:
            print(f"[{op_id}] done: {src_host} below threshold ({threshold:.2f})")
            return

        target = choose_target_host(src_host, threshold)
        if not target:
            print(f"[{op_id}] no target host available")
            return

        insts = list_instances_on_host(src_host)
        if not insts:
            print(f"[{op_id}] no instances on {src_host}")
            return
        # Prioritas RAM terbesar (mengurangi beban paling signifikan)
        insts.sort(key=lambda i: i.ram_mb, reverse=True)

        moved = False
        for inst in insts:
            # Jangan buat target melampaui threshold pasca-migrasi
            if inst.ram_mb <= target.free_mb and \
               (target.mem_used_mb + inst.ram_mb) / max(target.mem_total_mb, 1) <= threshold:
                print(f"[{op_id}] migrating {inst.name} ({inst.id}) {inst.ram_mb}MB → {target.name}")
                migrate_instance(inst, target.name)
                print(f"[{op_id}] waiting completion for {inst.id}...")
                # Tunggu sampai status kembali ACTIVE & host = target
                wait_for_migration(
                    server_id=inst.id,
                    expect_host=target.name,
                    timeout=MIGRATION_TIMEOUT_SEC,
                    poll=POLL_INTERVAL_SEC
                )
                print(f"[{op_id}] migration done for {inst.id}")
                moves += 1
                moved = True
                # beri waktu agar metrik hypervisor tersinkron
                time.sleep(MIGRATION_SLEEP_SEC)
                break

        if not moved:
            print(f"[{op_id}] no fitting instance for {target.name} (free {target.free_mb}MB) "
                  f"or would exceed target threshold")
            return

    print(f"[{op_id}] stop: reached MAX_MOVES_PER_RUN={MAX_MOVES_PER_RUN}")

# =========================
# API endpoints
# =========================
@app.get("/health")
def health():
    return {
        "ok": True,
        "default_threshold": DEFAULT_THRESHOLD,
        "sleep_sec": MIGRATION_SLEEP_SEC,
        "poll_interval_sec": POLL_INTERVAL_SEC,
        "migration_timeout_sec": MIGRATION_TIMEOUT_SEC,
        "max_moves_per_run": MAX_MOVES_PER_RUN,
    }

@app.get("/compute/hosts")
def hosts(x_api_key: str = Header(..., alias="X-API-Key")):
    _auth(x_api_key)
    data = []
    for h in list_hypervisors():
        data.append({
            "name": h.name,
            "mem_total_mb": h.mem_total_mb,
            "mem_used_mb": h.mem_used_mb,
            "util": round(h.util, 4),
            "free_mb": h.free_mb
        })
    return data

@app.post("/webhook/grafana", response_model=WebhookResult)
def grafana_webhook(payload: GrafanaAlert,
                    background: BackgroundTasks,
                    x_api_key: str = Header(..., alias="X-API-Key")):
    _auth(x_api_key)

    # Ambil host sumber dari label/annotation/alerts
    host = (
        payload.commonLabels.get("host")
        or payload.commonAnnotations.get("host")
        or (payload.alerts and payload.alerts[0].get("labels", {}).get("host"))
    )
    if not host:
        raise HTTPException(400, "host tidak ditemukan di payload")

    # Threshold dari payload atau default
    threshold = payload.target_threshold if payload.target_threshold is not None else DEFAULT_THRESHOLD
    try:
        threshold = float(threshold)
    except Exception:
        raise HTTPException(400, "threshold invalid")
    if not (0.0 < threshold < 1.0):
        raise HTTPException(400, "threshold harus (0,1), contoh 0.6 untuk 60%")

    op_id = payload.commonLabels.get("fingerprint") or f"{host}:{int(time.time())}"

    # Jalankan proses rebalancing di background
    background.add_task(rebalance_instances_until_below, host, threshold, op_id)
    return WebhookResult(
        accepted=True,
        operation_id=op_id,
        message=f"rebalance scheduled for {host} to < {int(threshold*100)}%"
    )
