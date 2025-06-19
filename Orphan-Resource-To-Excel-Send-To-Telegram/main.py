#!/usr/bin/env python3
import sys
import logging
import openstack
import os_client_config
import csv
import pandas as pd
import os
from datetime import datetime
import requests
import re

# Variable Definitions (to be defined at the beginning of the script)
OPENRC_PATH = '/path/to/rcfile'
OUTPUT_BASE_DIR = '/path/to/output/dir'
BOT_TOKEN = "telegram_bot_token"
CHAT_ID = "telegram_chat_id"
LOG_FILE_PATH = '/path/to/log/dir'

today_str = datetime.now().strftime('%Y%m%d')
OUTPUT_EXCEL = os.path.join(OUTPUT_BASE_DIR, today_str, f"{today_str}-Orphan-Resources.xlsx")

# Set up the log format to include current date
LOG_FORMAT = '[%(asctime)s] %(process)d-%(levelname)s-%(message)s'
LOG_DATEFMT = '%Y-%m-%d %H:%M:%S'

# Configure logging
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt=LOG_DATEFMT)
LOG = logging.getLogger(__name__)

# Make sure logs are saved to the file and not printed to console
file_handler = logging.FileHandler(LOG_FILE_PATH)
file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT))
LOG.addHandler(file_handler)

def connect():
    try:
        config = os_client_config.get_config()
        conn = openstack.connection.Connection(config=config)
        conn.authorize()
        return conn
    except Exception as curr_error:
        LOG.exception('Connection error : %s', curr_error, exc_info=1)
        sys.exit(1)

def get_projects_ids(conn):
    return [project.id for project in conn.identity.projects()]

def get_orphan_objs(conn, projectids, obj):
    projectids.append("")
    orphans = []
    headers = []

    if obj == "servers":
        headers = ['ID', 'Name', 'ProjectID', 'Networks']
        for server in conn.list_servers(all_projects=True):
            if server.project_id not in projectids:
                network_names = ", ".join(server.addresses.keys()) if server.addresses else ""
                orphans.append([server.id, server.name, server.project_id, network_names])

    elif obj == "volumes":
        headers = ['ID', 'Name', 'ProjectID']
        for volume in conn.block_storage.volumes(details=True, all_projects=True):
            if volume.project_id not in projectids:
                orphans.append([volume.id, volume.name, volume.project_id])

    elif obj == "volume_snapshots":
        headers = ['ID', 'Name', 'ProjectID']
        for snap in conn.block_storage.snapshots(details=True, all_projects=True):
            if snap.project_id not in projectids:
                orphans.append([snap.id, snap.name, snap.project_id])

    elif obj == "image_snapshots":
        headers = ['ID', 'Name', 'ProjectID']
        for image in conn.image.images():
            project_id = getattr(image, 'owner_id', getattr(image, 'project_id', None))
            if (project_id not in projectids) and (getattr(image, 'size', 1) == 0):
                orphans.append([image.id, image.name, project_id])

    elif obj == "networks":
        headers = ['ID', 'Name', 'ProjectID', 'Subnets ID']
        for net in conn.list_networks():
            if net['tenant_id'] not in projectids:
                subnets_str = ", ".join(net["subnets"]) if net.get("subnets") else ""
                orphans.append([net["id"], net["name"], net["tenant_id"], subnets_str])

    elif obj == "subnets":
        headers = ['ID', 'Name', 'ProjectID']
        for subnet in conn.list_subnets():
            if subnet['tenant_id'] not in projectids:
                orphans.append([subnet["id"], subnet["name"], subnet["tenant_id"]])

    elif obj == "routers":
        headers = ['ID', 'Name', 'ProjectID']
        for router in conn.list_routers():
            if router['tenant_id'] not in projectids:
                orphans.append([router["id"], router["name"], router["tenant_id"]])

    elif obj == "floating_ips":
        headers = ['ID', 'Name', 'IP', 'ProjectID']
        for fip in conn.list_floating_ips():
            if fip['tenant_id'] not in projectids:
                orphans.append([fip["id"], fip.get("name", ""), fip["floating_ip_address"], fip["tenant_id"]])

    elif obj == "ports":
        headers = ['ID', 'Name', 'ProjectID']
        for port in conn.list_ports():
            if port['tenant_id'] not in projectids:
                orphans.append([port["id"], port.get("name", ""), port["tenant_id"]])

    elif obj == "security_groups":
        headers = ['ID', 'Name', 'ProjectID']
        for sg in conn.list_security_groups():
            if sg['tenant_id'] not in projectids:
                orphans.append([sg["id"], sg["name"], sg["tenant_id"]])

    return headers, orphans

def save_to_csv(filename, headers, data):
    with open(filename, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(headers)
        writer.writerows(data)

def sanitize_sheet_name(name):
    return re.sub(r'[\[\]\*\/\\\?\:]', '', name)[:31]

def combine_csv_to_excel(csv_files, output_excel):
    with pd.ExcelWriter(output_excel, engine='xlsxwriter') as writer:
        workbook = writer.book

        header_format = workbook.add_format({
            'bold': True,
            'text_wrap': True,
            'valign': 'top',
            'align': 'left',
            'bg_color': '#9bbb59',
            'border': 1
        })

        for csv_file in csv_files:
            if os.path.exists(csv_file):
                sheet_base = os.path.splitext(os.path.basename(csv_file))[0]
                sheet_name = sanitize_sheet_name(sheet_base)
                df = pd.read_csv(csv_file)
                df.to_excel(writer, sheet_name=sheet_name, index=False)
                worksheet = writer.sheets[sheet_name]

                for idx, col in enumerate(df.columns):
                    max_len = max(df[col].astype(str).map(len).max(), len(col)) + 2
                    worksheet.set_column(idx, idx, max_len)

                worksheet.autofilter(0, 0, 0, len(df.columns) - 1)
                for col_num, value in enumerate(df.columns.values):
                    worksheet.write(0, col_num, value, header_format)

        LOG.info(f"Combined Excel saved to {output_excel}")

def load_openrc(file_path):
    with open(file_path) as f:
        for line in f:
            if line.strip().startswith("#") or not line.strip():
                continue
            if line.startswith("export"):
                key_value = line.strip().split("export ")[1]
                key, val = key_value.split("=", 1)
                val = val.strip('"').strip("'")
                os.environ[key.strip()] = val.strip()

def send_file_to_telegram(file_path, bot_token, chat_id):
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    with open(file_path, 'rb') as f:
        files = {'document': (os.path.basename(file_path), f)}
        data = {'chat_id': chat_id}
        response = requests.post(url, files=files, data=data)
    if response.status_code == 200:
        LOG.info("File berhasil dikirim ke Telegram.")
    else:
        LOG.error(f"Gagal mengirim file ke Telegram. Status: {response.status_code}, Pesan: {response.text}")

def prepare_output_directory(base_dir=OUTPUT_BASE_DIR):
    today_str = datetime.now().strftime('%Y%m%d')
    output_dir = os.path.join(base_dir, today_str)
    os.makedirs(output_dir, exist_ok=True)
    return output_dir

if __name__ == '__main__':

    # Load OpenRC and establish connection
    load_openrc(OPENRC_PATH)
    conn = connect()
    projectids = get_projects_ids(conn)

    valid_options = ['servers', 'volumes', 'volume_snapshots', 'image_snapshots', 'secgroups',
                     'networks', 'routers', 'subnets', 'floatingips', 'ports']

    ostack_objects = valid_options
    output_dir = prepare_output_directory()
    today_str = datetime.now().strftime('%Y-%m-%d')
    LOG.debug(f"Script berjalan pada tanggal {today_str}, output disimpan di {output_dir}")

    csv_files = []

    for ostack_object in ostack_objects:
        original_object = ostack_object
        if ostack_object == 'secgroups':
            ostack_object = 'security_groups'
        elif ostack_object == 'floatingips':
            ostack_object = 'floating_ips'

        LOG.info(f"Collecting orphan {original_object}...")
        headers, orphans = get_orphan_objs(conn, projectids, ostack_object)

        if orphans:
            filename = os.path.join(output_dir, f"{original_object}.csv")
            save_to_csv(filename, headers, orphans)
            LOG.info(f"Saved {len(orphans)} orphan {original_object} to {filename}")
            csv_files.append(filename)
        else:
            LOG.info(f"No orphan {original_object} found.")

    combine_csv_to_excel(csv_files, OUTPUT_EXCEL)

    # Send file to Telegram
    send_file_to_telegram(OUTPUT_EXCEL, BOT_TOKEN, CHAT_ID)
