#!/bin/bash

# Telegram bot token and chat ID
#telegram_bot_token="6540955721:AAHouyW-bt6qUKGbgyQFod5pwUZtD1o37bU"
#chat_id="882891040"
telegram_bot_token="<bot_token>"
chat_id="<chat_id>"

# Date and directory setup
date=$(date +"%d-%b-%y")
output_dir="/tmp/$date"
mkdir -p "$output_dir"

# Source OpenStack credentials
source /path/to/rc/file

# Collect volume list
volume_log="/tmp/.jah_all_volume.log"
output_volume_csv="$output_dir/jah-$date-volume.csv"
openstack volume list --all --long -c ID -c Name -c Status -c Size -c Type -f csv | sed 's/\"//g' | tail -n +2 > "$volume_log"

# Prepare volume CSV header
echo "Volume ID,Volume Name,Status,Size,Type,Migration Status,Cinder Pool,Instance ID,Project ID,Image ID,Image Name" > "$output_volume_csv"

# Variabel buat summary snapshot
declare -A pool_snapshot_count
total_snapshot=0

# Process each volume
while IFS=, read -r vol_id vol_name vol_status vol_size vol_type; do
  # Fetch volume details
  volume_details=$(cinder show "$vol_id")

  # Extract required fields using `grep` and `awk`
  vol_migration_status=$(echo "$volume_details" | grep "migration_status" | awk '{print $4}' | tr -d '"')
  vol_mapped=$(echo "$volume_details" | grep os-vol-host-attr | awk '{print $4}' | cut -d '#' -f2)
  vm_id=$(echo "$volume_details" | grep "attached_servers" | awk -F"[][]" '{print $2}' | tr -d "[]'")
  project_id=$(echo "$volume_details" | grep "os-vol-tenant-attr:tenant_id" | awk '{print $4}' | tr -d '"')
  image_id=$(echo "$volume_details" | grep "image_id" | awk '{print $5}' | tr -d '"')
  image_name=$(echo "$volume_details" | grep "image_name" | awk '{print $5}' | tr -d '"')

  # Hitung snapshot count
  snapshot_count=$(openstack volume snapshot list --all-projects --volume "$vol_id" -f value -c ID | wc -l)

  # Tambah ke summary pool & total
  pool_snapshot_count["$vol_mapped"]=$(( ${pool_snapshot_count["$vol_mapped"]} + snapshot_count ))
  total_snapshot=$(( total_snapshot + snapshot_count ))

  # Append data to the final CSV
  echo "$vol_id,$vol_name,$vol_status,$vol_size,$vol_type,$vol_migration_status,$vol_mapped,$vm_id,$project_id,$image_id,$image_name,$snapshot_count" | tee -a "$output_volume_csv"
done < "$volume_log"

# Buat summary TXT
{
  echo "=== Snapshot Summary per Pool ==="
  for pool in "${!pool_snapshot_count[@]}"; do
    echo "Pool $pool memiliki ${pool_snapshot_count[$pool]} snapshot"
  done | sort
  echo "TOTAL semua snapshot = $total_snapshot"
} > "$output_snapshot_summary"


# Notify via Telegram
curl -F "chat_id=$chat_id" \
  --form "document=@$output_volume_csv" \
  "https://api.telegram.org/bot$telegram_bot_token/sendDocument"

curl -F "chat_id=$chat_id" \
  --form "document=@$output_snapshot_summary" \
  "https://api.telegram.org/bot$telegram_bot_token/sendDocument"


