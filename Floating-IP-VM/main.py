import openstack
import csv
import os
import shlex

# === ✅ SET NAMA FILE OPENRC DI SINI ===
OPENRC_FILE = "openrc"

def load_openrc(file_path):
    with open(file_path, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("export "):
                parts = line.replace("export ", "").split("=", 1)
                if len(parts) == 2:
                    key = parts[0]
                    val = shlex.split(parts[1])[0]
                    os.environ[key] = val

# Load environment dari openrc
load_openrc(OPENRC_FILE)

# Koneksi ke OpenStack
conn = openstack.connect()

# File output CSV
csv_file = "floating_ip_report.csv"
header = ["Floating IP", "Status", "Instance Name", "Instance ID", "User ID", "Username", "Project Name"]

with open(csv_file, mode="w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(header)

    for fip in conn.network.ips():
        floating_ip = fip.floating_ip_address
        status = fip.status
        instance_name = "-"
        instance_id = "-"
        user_id = "-"
        username = "-"
        project_name = "-"

        # Ambil project name dari fip.project_id
        try:
            project = conn.identity.get_project(fip.project_id)
            if project:
                project_name = project.name
        except Exception:
            project_name = "None"

        if fip.port_id:
            try:
                port = conn.network.get_port(fip.port_id)
                device_id = port.device_id
                if device_id:
                    server = conn.compute.get_server(device_id)
                    if server:
                        instance_name = server.name
                        instance_id = server.id
                        user_id = server.user_id

                        # Ambil username dari user_id
                        try:
                            user = conn.identity.get_user(user_id)
                            if user:
                                username = user.name
                        except Exception:
                            username = "None"
            except Exception:
                pass

        writer.writerow([floating_ip, status, instance_name, instance_id, user_id, username, project_name])

print(f"\n✅ Output berhasil disimpan ke file: {csv_file}")
