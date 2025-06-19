#!/usr/bin/env python3
import sys
import logging
import openstack
import os_client_config
import os
import requests
from urllib.parse import urlparse

# Change with your rc file
OPENRC_PATH = '/path/to/rcfile'

FORMAT = '%(process)d-%(levelname)s-%(message)s'
logging.basicConfig(format=FORMAT, level=logging.INFO)
LOG = logging.getLogger(__name__)

# Ganti dengan alamat Pushgateway kamu
PUSHGATEWAY_URL = "http://localhost:9091" 
parsed_url = urlparse(PUSHGATEWAY_URL)
pushgateway_instance = parsed_url.hostname

VALID_OPTIONS = ['networks', 'routers', 'subnets', 'floatingips', 'ports',
                 'servers', 'volumes', 'volume_snapshots', 'image_snapshots', 'secgroups']


def usage():
    print("Usage: check_orphan-resources.py <object> where object is one or more of")
    print("'networks', 'routers', 'subnets', 'floatingips', 'ports', 'servers',")
    print("'volumes', 'volume_snapshots', 'image_snapshots', 'secgroups' or 'all'")


def connect():
    try:
        config = os_client_config.get_config()
        conn = openstack.connection.Connection(config=config)
        conn.authorize()
        return conn
    except Exception as e:
        LOG.exception('Connection error: %s', e, exc_info=True)


def get_projects_ids(conn):
    return [project.id for project in conn.identity.projects()]


def delete_old_metrics(pushgateway_url, job_name):
    try:
        url = f"{pushgateway_url}/metrics/job/{job_name}"
        response = requests.delete(url)
        if response.status_code in (200, 202):
            LOG.info(f"Deleted old metrics for {job_name}")
        else:
            LOG.warning(f"Failed to delete old metrics for {job_name}: HTTP {response.status_code} - {response.text}")
    except Exception as e:
        LOG.exception(f"Exception while deleting old metrics for {job_name}: {e}")


def push_metrics(pushgateway_url, job_name, metric_data):
    try:
        url = f"{pushgateway_url}/metrics/job/{job_name}"
        headers = {"Content-Type": "text/plain"}
        response = requests.post(url, data=metric_data.encode('utf-8'), headers=headers)
        if response.status_code not in (200, 202):
            LOG.warning(f"Failed to push {job_name}: HTTP {response.status_code} - {response.text}")
            LOG.debug(f"Payload:\n{metric_data}")
        else:
            LOG.info(f"Pushed metrics for {job_name} (status: {response.status_code})")
    except Exception as e:
        LOG.exception(f"Exception while pushing {job_name}: {e}")


def generate_metric_line(metric_name, labels: dict, value: int = 1) -> str:
    # Filter out empty label values
    labels = {k: v for k, v in labels.items() if v}
    label_str = ",".join([f'{k}="{v}"' for k, v in labels.items()])
    return f'{metric_name}{{{label_str}}} {value}'

def load_openrc(file_path):
    """Load OpenStack RC file like `source` does in shell."""
    with open(file_path) as f:
        for line in f:
            # Lewati komentar atau baris kosong
            if line.strip().startswith("#") or not line.strip():
                continue
            if line.startswith("export"):
                # Ambil key dan value
                key_value = line.strip().split("export ")[1]
                key, val = key_value.split("=", 1)
                val = val.strip('"').strip("'")  # Hapus tanda kutip
                os.environ[key.strip()] = val.strip()

def get_orphan_objs(conn, projectids, obj):
    projectids.append("")
    metrics = []

    if obj == "servers":
        for server in conn.list_servers(all_projects=True):
            if server.project_id not in projectids:
                labels = {
                    "job": "orphan_servers",
                    "name": server.name or "unknown",
                    "server_id": server.id,
                    "project_id": server.project_id,
                    "instance": pushgateway_instance
                }
                metrics.append(generate_metric_line("orphan_servers", labels))

    elif obj == "volumes":
        for volume in conn.block_storage.volumes(details=True, all_projects=True):
            if volume.project_id not in projectids:
                labels = {
                    "job": "orphan_volumes",
                    "name": volume.name or "unknown",
                    "volume_id": volume.id,
                    "project_id": volume.project_id,
                    "instance": pushgateway_instance
                }
                metrics.append(generate_metric_line("orphan_volumes", labels))

    elif obj == "volume_snapshots":
        for snap in conn.block_storage.snapshots(details=True, all_projects=True):
            if snap.project_id not in projectids:
                labels = {
                    "job": "orphan_volume_snapshots",
                    "name": snap.name or "unknown",
                    "snapshot_id": snap.id,
                    "project_id": snap.project_id,
                    "instance": pushgateway_instance
                }
                metrics.append(generate_metric_line("orphan_volume_snapshots", labels))

    elif obj == "image_snapshots":
        for image in conn.image.images():
            project_id = getattr(image, 'owner_id', getattr(image, 'project_id', None))
            if (project_id not in projectids) and (getattr(image, 'size', 1) == 0):
                labels = {
                    "job": "orphan_image_snapshots",
                    "name": image.name or "unknown",
                    "image_id": image.id,
                    "project_id": project_id,
                    "instance": pushgateway_instance
                }
                metrics.append(generate_metric_line("orphan_image_snapshots", labels))

    elif obj == "networks":
        for net in conn.list_networks():
            if net['tenant_id'] not in projectids:
                labels = {
                    "job": "orphan_networks",
                    "name": net['name'],
                    "network_id": net['id'],
                    "project_id": net['tenant_id'],
                    "instance": pushgateway_instance
                }
                metrics.append(generate_metric_line("orphan_networks", labels))

    elif obj == "subnets":
        for subnet in conn.list_subnets():
            if subnet['tenant_id'] not in projectids:
                labels = {
                    "job": "orphan_subnets",
                    "name": subnet['name'],
                    "subnet_id": subnet['id'],
                    "project_id": subnet['tenant_id'],
                    "instance": pushgateway_instance
                }
                metrics.append(generate_metric_line("orphan_subnets", labels))

    elif obj == "routers":
        for router in conn.list_routers():
            if router['tenant_id'] not in projectids:
                labels = {
                    "job": "orphan_routers",
                    "name": router['name'],
                    "router_id": router['id'],
                    "project_id": router['tenant_id'],
                    "instance": pushgateway_instance
                }
                metrics.append(generate_metric_line("orphan_routers", labels))

    elif obj == "floating_ips":
        for fip in conn.list_floating_ips():
            if fip['tenant_id'] not in projectids:
                labels = {
                    "job": "orphan_floating_ips",
                    "floating_ip_address": fip['floating_ip_address'],
                    "floating_id": fip['id'],
                    "project_id": fip['tenant_id'],
                    "instance": pushgateway_instance
                }
                metrics.append(generate_metric_line("orphan_floating_ips", labels))

    elif obj == "ports":
        for port in conn.list_ports():
            if port['tenant_id'] not in projectids:
                labels = {
                    "job": "orphan_ports",
                    "name": port.get('name', ''),
                    "port_id": port['id'],
                    "project_id": port['tenant_id'],
                    "instance": pushgateway_instance
                }
                metrics.append(generate_metric_line("orphan_ports", labels))

    elif obj == "security_groups":
        for sg in conn.list_security_groups():
            if sg['tenant_id'] not in projectids:
                labels = {
                    "job": "orphan_secgroups",
                    "name": sg['name'],
                    "secgroup_id": sg['id'],
                    "project_id": sg['tenant_id'],
                    "instance": pushgateway_instance
                }
                metrics.append(generate_metric_line("orphan_secgroups", labels))

    else:
        LOG.warning("Object type %s not recognized", obj)

    return metrics


if __name__ == '__main__':
    load_openrc(OPENRC_PATH)
    conn = connect()
    if not conn:
        sys.exit(1)

    projectids = get_projects_ids(conn)

    if len(sys.argv) > 1:
        if sys.argv[1] == 'all':
            ostack_objects = VALID_OPTIONS
        else:
            ostack_objects = sys.argv[1:]

        for ostack_object in ostack_objects:
            if ostack_object not in VALID_OPTIONS:
                LOG.error("%s is not a valid OpenStack object", ostack_object)
                usage()
                sys.exit(1)

            # Normalize
            if ostack_object == "secgroups":
                ostack_object = "security_groups"
            if ostack_object == "floatingips":
                ostack_object = "floating_ips"

            LOG.info(f"Checking {ostack_object}...")
            metrics = get_orphan_objs(conn, projectids, ostack_object)
            job_name = f"orphan_{ostack_object}"

            delete_old_metrics(PUSHGATEWAY_URL, job_name)

            if metrics:
                # Include type declaration
                metric_type = f"# TYPE {job_name} untyped\n"
                metric_data = metric_type + "\n".join(metrics) + "\n"
                push_metrics(PUSHGATEWAY_URL, job_name, metric_data)
            else:
                LOG.info(f"No orphan {ostack_object}")
    else:
        usage()
