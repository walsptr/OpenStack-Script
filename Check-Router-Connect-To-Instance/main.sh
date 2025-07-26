#!/bin/bash

# File berisi daftar router_id (satu per baris)
router_id_file="router_id"

# Membaca router_id dari file
mapfile -t router_ids < "$router_id_file"

log_file="/opt/script/router/hasil_router_check.txt"
echo "=== ROUTER CHECK START ===" > "$log_file"

for rid in "${router_ids[@]}"; do
  echo "🔍 Checking router: $rid" >> "$log_file"

  # Get interfaces_info
  interfaces=$(openstack router show --fit "$rid" -c interfaces_info -f json | jq -r '."interfaces_info"[]?.subnet_id')

  if [[ -z "$interfaces" ]]; then
    echo "  ⚠️  No internal interfaces found!" >> "$log_file"
    continue
  fi

  for subnet in $interfaces; do
    echo "  🌐 Subnet: $subnet" >> "$log_file"

    # Check if any ports with device-owner compute:nova exist in this subnet
    result=$(openstack port list --device-owner compute:nova --fixed-ip subnet=$subnet -f value -c ID)

    if [[ -z "$result" ]]; then
      echo "    ✅ No VM using this subnet — safe to delete (if other conditions met)" >> "$log_file"
    else
      echo "    ❌ Subnet in use by VM(s):" >> "$log_file"
      echo "$result" | sed 's/^/      - /' >> "$log_file"
    fi
  done
done

echo "=== ROUTER CHECK COMPLETE ===" >> "$log_file"
echo "✅ Log saved to: $log_file"
