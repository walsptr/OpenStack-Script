hosts=(
        "controller-0"
        "controller-1"
        "controller-2"
        )
dest_conf_file="/etc/pki/tls/private/"
dir_templates="/home/stack/templates"
enable_ssl_default="/home/stack/templates/enable-tls.yaml"
enable_ssl_new="/home/stack/script/ssl/enable-tls.yaml"
file_ssl="overcloud_endpoint.pem"
date=$(date '+%Y-%m-%d-%H:%M')

for host in "${hosts[@]}"; do
        echo "Backup file $file_ssl"
        ssh $host "sudo cp /etc/pki/tls/private/overcloud_endpoint.pem /etc/pki/tls/private/overcloud_endpoint-${date}.pem"
        sleep 2

        echo "Copying file to $host"
        scp $file_ssl $host:~/
        sleep 2

        echo "Change owner permissions"
        ssh $host "sudo chown root:root $file_ssl"
        sleep 2

        echo "Copy to config data"
        ssh $host "sudo cp $file_ssl $dest_conf_file"
        sleep 2

        echo "delete /home/tripleo-admin/overcloud_endpoint.pem"
        ssh $host "sudo rm $file_ssl"
        sleep 2

        echo "backup enable-tls.yaml"
        cp $enable_ssl_default $dir_templates/enable-tls-${date}.yaml
        sleep 2

        echo "copy enable-tls.yaml"
        cp $enable_ssl_new $enable_ssl_default
done
