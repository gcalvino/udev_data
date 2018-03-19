#!/usr/bin/python

# Copyright (C) 2016  Ricardo Noriega (ricardonor@gmail.com)
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import requests
import json
import os, sys
import shutil
import fileinput
import time
import subprocess

'''
Example of Metadata information
--------------------------------

{
  "devices": [
    {
        "type": "nic",
        "bus": "pci",
        "address": "0000:00:02.0",
        "mac": "01:22:22:42:22:21",
        "tags": ["nfvfunc1"]
    },
    {
        "type": "nic",
        "bus": "pci",
        "address": "0000:00:03.0",
        "mac": "01:22:22:42:22:21",
        "tags": ["nfvfunc2"]
    },
    {
        "type": "disk",
        "bus": "scsi",
        "address": "1:0:2:0",
        "serial": "disk-vol-2352423",
        "tags": ["oracledb"]
    },
    {
        "type": "disk",
        "bus": "pci",
        "address": "0000:00:07.0",
        "serial": "disk-vol-24235252",
        "tags": ["squidcache"]
    }
  ]
}
'''
CONFIG_DRIVE = False

def get_metadata_zeroconf():
    '''Function that sends a GET to the metadata service and parses the output'''
    try:
        response = requests.get('http://169.254.169.254/openstack/latest/meta_data.json')
        r = json.loads(response.text)
        metadata = {}
        for item in r.get('devices'):
            metadata[item['tags'][0]] = item['address']
        return metadata
    except Exception as e:
        return "ERROR - Metadata service not available: {}".format(e)

def get_metadata_config_drive():
    '''Function that mounts config drive with metadata info'''
    try:
        path = "/mnt/config"
        if os.path.isdir(path) is not True:
            os.mkdir(path, 0755)
        os.system("mount /dev/disk/by-label/config-2 /mnt/config")
        with open('/mnt/config/openstack/latest/meta_data.json', 'r') as fp:
            r = json.load(fp)
        metadata = {}
        for item in r.get('devices'):
            metadata[item['tags'][0]] = item['address']
        return metadata
    except Exception as e:
        return "ERROR - Config drive mount failed: {}".format(e)

def get_metadata_lspci():

    try:
        p1 = subprocess.Popen("lspci | grep Ethernet", stdout=subprocess.PIPE, shell=True)
        lspci_byte = p1.stdout.read()
        lspci_list = lspci_byte.decode('utf-8').splitlines()
        nic_list = []
        for nic in lspci_list:
           nic_list.append(nic.split(' ')[0])
        nic_list.sort()

        metadata = get_metadata_zeroconf()
        lspci_metadata = {}
        i = 0
        for nic in nic_list:
            if metadata.get(nic) == None:
                lspci_metadata["xe{}".format(i)] = nic
                i += 1
        return lspci_metadata
    except Exception as e:
        return "ERROR - LSPCI metadata failed: {}".format(e)


def write_udev(metadata, mode='w'):
    '''Function that will write udev rules that look like:
    cat /etc/udev/rules.d/70-persistent-net.rules
    ACTION=="add", SUBSYSTEM=="net", KERNELS=="0000:00:0a.0", NAME="eth0"
    ACTION=="add", SUBSYSTEM=="net", KERNELS=="0000:00:0b.0", NAME="eth1"
    ACTION=="add", SUBSYSTEM=="net", KERNELS=="0000:00:0c.0", NAME="xe0"
    ACTION=="add", SUBSYSTEM=="net", KERNELS=="0000:00:0d.0", NAME="xe1" '''
    try:
        target = open('/etc/udev/rules.d/70-persistent-net.rules', mode)
        for i in metadata:
            target.write('ACTION=="add", SUBSYSTEM=="net", KERNELS=="'+ metadata[i] + '", NAME="' + i + '"')
            target.write("\n")
        target.close()
    except Exception as e:
        return "ERROR - Writing udev config file failed: {}".format(e)

def apply_udev(metadata, mode="w"):
    try:
        if os.path.isfile('/etc/redhat-release'):
            if not CONFIG_DRIVE:
                os.system("systemctl stop network.service")
            os.system("udevadm control --reload")
            os.system("udevadm trigger --attr-match=subsystem=net")
            os.system("systemctl restart systemd-udev-trigger.service")
            for name,pci in metadata.iteritems():
                shutil.copy("/etc/sysconfig/network-scripts/ifcfg-eth0", "/etc/sysconfig/network-scripts/ifcfg-"+ name)
                for line in fileinput.input("/etc/sysconfig/network-scripts/ifcfg-"+ name, inplace=1):
                    if "eth0" in line:
                        line = line.replace("eth0", name)
                    sys.stdout.write(line)
            os.remove("/etc/sysconfig/network-scripts/ifcfg-eth0")
            if not CONFIG_DRIVE:
                os.system("systemctl start network.service")
        else:
            os.system("systemctl stop networking.service")
            os.system("udevadm control --reload")
            os.system("udevadm trigger --attr-match=subsystem=net")
            os.system("systemctl restart systemd-udev-trigger.service")
            shutil.copy("/etc/network/interfaces", "/etc/network/interfaces.bckup")
            for name,pci in metadata.iteritems():
                target = open('/etc/network/interfaces', mode)
                if mode == "w":
                    target.write("auto lo")
                    target.write("\n")
                    target.write("iface lo inet loopback")
                    target.write("\n")
                    target.write("\n")
                for i in metadata:
                    if "eth0" in i:
                        target.write("auto {}".format(i))
                        target.write("\n")
                        target.write("iface {} inet dhcp".format(i))
                        target.write("\n")
                        target.write("\n")
            os.system("systemctl start networking.service")
    except Exception as e:
        return "ERROR - Apply udev failed: {}".format(e)

def main():

    if CONFIG_DRIVE:
        a = get_metadata_config_drive()
        write_udev(a)
        apply_udev(a)
    if not CONFIG_DRIVE:
        time.sleep(3)
        a = get_metadata_zeroconf()
        write_udev(a)
        apply_udev(a)

if __name__ == '__main__':
    sys.exit(main())
