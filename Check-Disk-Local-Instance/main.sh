#!/bin/bash

for dom in $(sudo podman exec nova_libvirt virsh list --all | egrep -v "^( Id|---|$)" | awk '{print $2}'); do
    dumpxml=$(sudo podman exec nova_libvirt virsh dumpxml $dom | egrep "<nova:name>|<uuid>|<nova:project" | tr '\r\n' ' ' | sed 's/\s*<\/*uuid>//g; s/\s*<\/*nova:name>/:/g; s/\s*<\/*nova:project//g; s/ uuid="//g; s/\"*>/:/g')
    uuid=$(echo $dumpxml | cut -d':' -f1)
    name=$(echo $dumpxml | cut -d':' -f2)
    prjid=$(echo $dumpxml | cut -d':' -f3)
    prj=$(echo $dumpxml | cut -d':' -f4)
    disks=$(sudo podman exec nova_libvirt virsh domblklist ${dom} | egrep -v "^( Target|---|$)" | awk '{print $1,$2}')
    state=$(sudo podman exec nova_libvirt virsh list --all | grep $dom | awk '{print $3}')

    OLDIFS=$IFS
    IFS=$'\n'
    for disk in ${disks}; do
        echo -ne "\"${compute_host}\",\"${dom}\","
        echo -ne "\"${uuid}\",\"${name}\",\"${prjid}\",\"${prj}\",\"${state}\","
        echo "${disk}" | awk '{printf "\"%s\"|\"%s\"", $1,$2}' | tr '|' ','
        echo ""
    done
    IFS=$OLDIFS
done > /tmp/instance-list-$(hostname).csv
