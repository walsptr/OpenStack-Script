#!/bin/bash

input_file="data-volume.txt"
output_file="snapshot-volume.txt"

# Kosongkan file output jika sudah ada
> "$output_file"

while IFS= read -r volume_id; do
  # Skip baris kosong
  [[ -z "$volume_id" ]] && continue

  # Cek apakah ada snapshot untuk volume ini
  snapshot_count=$(openstack volume snapshot list --all-projects --volume "$volume_id" -f value -c ID | wc -l)

  if (( snapshot_count > 0 )); then
    echo "$volume_id" >> "$output_file"
    echo "Volume $volume_id memiliki $snapshot_count snapshot."
  else
    echo "Volume $volume_id tidak memiliki snapshot."
  fi
done < "$input_file"
