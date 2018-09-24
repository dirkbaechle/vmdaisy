Setup Ubuntu 14.04 normal.
Ensured that basic networking runs fine
Changed network config as given in the attached file, to enable bridging functionaltiy for VMs

When starting "kvm" as normal

  kvm -m 2048 -cpu host -smp cores=2,threads=1,sockets=1 -device e1000,netdev=tunnel -netdev tap,id=tunnel,ifname=vnet0 -hda susetry.qcow2

there would be an error 


"qemu-system-x86_64: -netdev tap,id=tunnel,ifname=vnet0: could not configure /dev/net/tun (vnet0): Operation not permitted
qemu-system-x86_64: -netdev tap,id=tunnel,ifname=vnet0: Device 'tap' could not be initialized"

as described on "http://wiki.libvirt.org" (link at http://stackoverflow.com/questions/20153050/why-do-i-get-a-permissions-error-when-starting-a-kvm-vm-with-a-tap-interface ) , peformed the following steps


1) disable SELinux

a) in /etc/selinux/config, change the line "SELINUX=enforcing" to SELINUX=permissive b) from a root shell, run "setenforce permissive"

2) in /etc/libvirt/qemu.conf add/edit the following lines:

 a) clear_emulator_capabilities = 0
 b) user = root
 c) group = root
 d)
    cgroup_device_acl = [
        "/dev/null", "/dev/full", "/dev/zero",
        "/dev/random", "/dev/urandom",
        "/dev/ptmx", "/dev/kvm", "/dev/kqemu",
        "/dev/rtc", "/dev/hpet", "/dev/net/tun",
    ]

(the final "/dev/net/tun" is the most important part of (d)).

3) restart libvirtd 

  sudo stop libvirt-bin
  sudo start libvirt-bin




Then started the VM again, as root with

  sudo kvm -m 2048 -cpu host -smp cores=2,threads=1,sockets=1 -device e1000,netdev=tunnel -netdev tap,id=tunnel,ifname=vnet0 -hda susetry.qcow2

Within the started VM reconfigured the network interface to a static address 192.168.1.10, and ensured that the "ssh" service is allowed for the External zone in the Firewall (openSuSE 12.3). 

Checked login from the host machine with

  ssh dirk@192.168.1.10

worked!


Problem:

The authenticity of host '192.168.1.10 (192.168.1.10)' can't be established.
ECDSA key fingerprint is 9c:19:e2:2c:1c:c4:ec:03:4c:47:5f:7e:69:bf:2a:00.
Are you sure you want to continue connecting (yes/no)? yes
Warning: Permanently added '192.168.1.10' (ECDSA) to the list of known hosts.
Password: 

How to handle this when all VMs have the same IP address?


Solution
========

Now using Paramiko, with AutoAdd policy for unknown hosts.

Requirements: Hosts need to have an ssh server installed.

Additionally, for the shutdown of the machine, we have to grant the buildslave user the ight to excute /sbin/shutdown.

There are several methods available, we prefer to edit the /etc/sudoers file with::

    sudo visudo

and then add::

    user ALL=/sbin/shutdown
    user ALL=NOPASSWD: /sbin/shutdown

at the end of the file.


For ssh relogin (remote host changes - man in the middle attack)
================================================================

Add file ~/.ssh/config on guest system with contents::

    Host 192.168.1.10
    StrictHostKeyChecking no

, and now also a::

    ssh-keygen -f /home/dirk/.ssh/known_hosts -R server_ip

gets executed before sending a ssh command via paramiko.


In the VM you also have to make sure that::

    Defaults requiretty

is not activated in the /etc/sudoers file. This is default setting for
most Fedore, RedHat distributions.

It's possible to remove this restriciont on a per-user basis, by
adding::

    Defaults:user !requiretty

