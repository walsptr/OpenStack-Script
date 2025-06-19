#!/bin/bash


source /path/to/rc/file

read -p "Masukkan nama Security Group: " SEC_GROUP

read -p "Masukkan Project ID: " PROJECT_ID


echo ""
echo "🔍 Mencari VM yang menggunakan Security Group: '$SEC_GROUP'..."
echo ""

openstack server list --project $PROJECT_ID -f json | jq -r '.[].ID' | while read id; do
    VM_INFO=$(openstack server show "$id" -f json)
    VM_NAME=$(echo "$VM_INFO" | jq -r '.name')
    VM_ID=$(echo "$VM_INFO" | jq -r '.id')
    MATCH=$(echo "$VM_INFO" | jq -r --arg SEC_GROUP "$SEC_GROUP" 'select(.security_groups[]?.name == $SEC_GROUP)')
    
    if [[ ! -z "$MATCH" ]]; then
        echo "-------------------------------------------"
        echo "🖥️  Nama VM : $VM_NAME"
        echo "🆔 ID VM    : $VM_ID"
    fi
done

echo ""
echo "✅ Selesai mencari VM yang menggunakan Security Group: '$SEC_GROUP' di Project ID: '$PROJECT_ID'"
