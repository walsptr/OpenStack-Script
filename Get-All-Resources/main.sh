
# Telegram bot token and chat ID

telegram_bot_token="<bot_token>"
chat_id="chat_id"

# Date and directory setup
date=$(date +"%d-%b-%y")
output_dir="/tmp/$date"
mkdir -p "$output_dir"

# Source OpenStack credentials
source /path/to/rc/file

# Define output files
server_log="/tmp/.all_server.log"
server_csv="$output_dir/$date-server.csv"
project_csv="$output_dir/$date-project.csv"
domain_csv="$output_dir/$date-domain.csv"
readme="$output_dir/README"

# Collect server data
openstack server list --long --all -c ID -c Name -c "Power State" -c Status -c Flavor -c Host -f csv --name-lookup-one-by-one | tail -n +2 > "$server_log"
echo "Instance ID,Instance Name,Power State,Status,Flavor,Hypervisor,Libvirt ID" > "$server_csv"

# Process servers and generate CSV
while IFS=, read -r vm_id vm_name vm_power_state vm_status vm_flavor vm_host _; do
  vm_id=$(echo "$vm_id" | tr -d '"')
  vm_name=$(echo "$vm_name" | tr -d '"')
  vm_power_state=$(echo "$vm_power_state" | tr -d '"')
  vm_status=$(echo "$vm_status" | tr -d '"')
  vm_flavor=$(echo "$vm_flavor" | tr -d '"')
  vm_host=$(echo "$vm_host" | tr -d '"')
  libvirt_id=$(openstack server show "$vm_id" -c OS-EXT-SRV-ATTR:instance_name -f value)
  echo "$vm_id,$vm_name,$vm_power_state,$vm_status,$vm_flavor,$vm_host,$libvirt_id" | tee -a "$server_csv"
done < "$server_log"

# Collect project and domain data
openstack project list --long -c ID -c Name -c "Domain ID" -f csv | sed 's/\"//g' > "$project_csv"
openstack domain list -c ID -c Name -f csv | sed 's/\"//g' > "$domain_csv"

# Generate counts
count_volume=$(openstack volume list --all -f value | wc -l)
count_all_vm=$(wc -l < "$server_log")
{
  echo "All Instances count at $date: $count_all_vm"
  echo "All volume count at $date: $count_volume"
} > "$readme"

# Send notification and files to Telegram
telegram_message="<b>✅ [ INFO ALERT ] ✅</b>%0AExporting all resources in <b>RHOSP Cluster</b> successfully executed on $(date "+%A %e %B %Y %T") WIB.%0AReady to process in Excel:"
curl -s -X POST "https://api.telegram.org/bot$telegram_bot_token/sendMessage" \
  -d "chat_id=$chat_id" \
  -d "parse_mode=HTML" \
  -d "text=$telegram_message"

for file in "$server_csv" "$project_csv" "$domain_csv"; do
  curl -s -F "chat_id=$chat_id" \
    --form "document=@$file" \
    "https://api.telegram.org/bot$telegram_bot_token/sendDocument"
done
