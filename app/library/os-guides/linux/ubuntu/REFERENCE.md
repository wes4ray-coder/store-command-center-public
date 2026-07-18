# Ubuntu 24.04 LTS Quick Reference

> Offline reference guide for AI agents. Last updated: 2026-07-10.

## Contents
1. System Structure
2. Package Management
3. Service Management (systemd)
4. User Management
5. Networking
6. Storage
7. Cron & Timers
8. Logs
9. Docker on Ubuntu
10. SSH
11. Firewall
12. Performance & Monitoring

## 1. System Structure

```
/etc/       — system configuration files
/var/       — variable data (logs, caches, spools)
/home/      — user home directories
/usr/       — user programs and data (bin, lib, share)
/opt/       — optional/third-party software
/tmp/       — temporary files (cleared on reboot)
/proc/      — kernel & process info (virtual)
/sys/       — sysfs (hardware info, virtual)
/dev/       — device files
/root/      — root user home
/boot/      — kernel & bootloader files
```

## 2. Package Management

```bash
# APT
sudo apt update              # refresh package lists
sudo apt upgrade             # upgrade all packages
sudo apt install <pkg>       # install package
sudo apt remove <pkg>        # remove package (keep config)
sudo apt purge <pkg>         # remove package + config
sudo apt autoremove          # remove unused dependencies
apt list --installed          # list installed packages
apt show <pkg>                # show package info
apt-cache search <term>      # search packages

# Snap
sudo snap install <pkg>      # install snap
sudo snap remove <pkg>       # remove snap
snap list                    # list installed snaps
sudo snap refresh            # update all snaps

# DPKG
dpkg -l                      # list installed packages
dpkg -i <file.deb>           # install .deb file
dpkg -r <pkg>                # remove package
dpkg-reconfigure <pkg>       # reconfigure package
```

## 3. Service Management (systemd)

```bash
# System services
sudo systemctl start <svc>
sudo systemctl stop <svc>
sudo systemctl restart <svc>
sudo systemctl status <svc>
sudo systemctl enable <svc>     # start on boot
sudo systemctl disable <svc>    # don't start on boot
sudo systemctl daemon-reload    # after unit file changes

# User services (no sudo)
systemctl --user start <svc>
systemctl --user stop <svc>
systemctl --user status <svc>
systemctl --user enable <svc>
systemctl --user list-units --type=service

# Linger (user services survive logout)
loginctl enable-linger <user>
loginctl disable-linger <user>

# Logs
journalctl -u <svc> -n 100          # last 100 lines
journalctl -u <svc> -f              # follow
journalctl --user -u <svc> -n 50    # user service logs
journalctl --since "1 hour ago"     # time-filtered
journalctl -p err                   # errors only

# Service files
# System: /etc/systemd/system/<svc>.service
# User: ~/.config/systemd/user/<svc>.service

# Example user service
[Unit]
Description=My App
After=network.target

[Service]
Type=simple
ExecStart=/path/to/app
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

## 4. User Management

```bash
# Add user
sudo adduser <username>          # interactive (recommended)
sudo useradd -m -s /bin/bash <username>  # non-interactive

# Sudo access
sudo usermod -aG sudo <username>     # add to sudo group
# Or edit sudoers:
sudo visudo
# Add: <username> ALL=(ALL:ALL) ALL

# Groups
groups <user>                        # show user's groups
sudo usermod -aG <group> <user>      # add user to group
sudo groupadd <group>                # create group

# Other
passwd <user>                        # change password
chsh -s /bin/bash <user>             # change shell
id <user>                            # show UID/GID/groups
```

## 5. Networking

```bash
# IP configuration
ip addr show                     # show all interfaces
ip addr add 192.168.1.10/24 dev eth0  # add IP
ip link set eth0 up              # bring interface up
ip route show                    # routing table

# Sockets
ss -tulnp                        # listening TCP/UDP with PIDs
ss -tnp                          # active TCP connections

# Netplan (Ubuntu network config)
# Config: /etc/netplan/*.yaml
sudo netplan apply               # apply changes

# Example netplan:
# network:
#   version: 2
#   ethernets:
#     eth0:
#       dhcp4: true

# DNS
resolvectl status                # DNS resolver status
# Static DNS in netplan or /etc/resolv.conf
```

## 6. Storage

```bash
# Block devices
lsblk                            # show block devices
lsblk -f                         # with filesystem info
blkid                            # UUIDs and labels

# Mounting
sudo mount /dev/sdb1 /mnt        # mount partition
sudo umount /mnt                 # unmount
mount | column -t                # show mounted filesystems

# FSTAB (persistent mounts)
# /etc/fstab format:
# UUID=<uuid> /mount/point ext4 defaults 0 2
sudo mount -a                    # mount all from fstab

# Disk usage
df -h                            # filesystem usage
df -i                            # inode usage
du -sh /path                     # directory size
du -sh /path/* | sort -rh | head # largest items

# LVM
sudo pvs                         # physical volumes
sudo vgs                         # volume groups
sudo lvs                         # logical volumes
sudo lvextend -L +10G /dev/vg/lv # extend LV
sudo resize2fs /dev/vg/lv        # resize filesystem (ext4)
```

## 7. Cron & Timers

```bash
# Cron
crontab -e                       # edit user crontab
crontab -l                       # list user crontab
sudo crontab -e                  # root crontab

# Cron format: minute hour day month weekday command
# */5 * * * * /path/to/script.sh    — every 5 minutes
# 0 3 * * * /path/to/backup.sh      — 3 AM daily
# 0 0 * * 0 /path/to/weekly.sh      — midnight Sunday

# System-wide cron
# /etc/crontab
# /etc/cron.{daily,weekly,monthly}/
# /etc/cron.d/<name>

# Systemd timers (preferred over cron)
# Create .timer unit + matching .service
[Unit]
Description=Run backup daily

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target

systemctl --user start <name>.timer
systemctl --user enable <name>.timer
systemctl --user list-timers
```

## 8. Logs

```bash
# Journalctl (primary log source)
journalctl -n 200 --no-pager     # last 200 lines
journalctl -f                    # follow (like tail -f)
journalctl -u <svc>              # service-specific
journalctl --user -u <svc>       # user service
journalctl --since "2026-07-09" --until "2026-07-10"
journalctl -p err                # priority filter (err, warning, info)
journalctl --disk-usage          # log disk usage

# Traditional log files
# /var/log/syslog                — system log
# /var/log/auth.log              — auth log
# /var/log/kern.log              — kernel log
# /var/log/nginx/                — nginx logs
# /var/log/docker/               — docker logs

# Log rotation
# /etc/logrotate.conf
# /etc/logrotate.d/<app>
sudo logrotate -f /etc/logrotate.d/<app>  # force rotation
```

## 9. Docker on Ubuntu

```bash
# Installation
sudo apt install docker.io docker-compose-v2
sudo usermod -aG docker $USER    # run without sudo
# Log out/in or: newgrp docker

# Compose
docker compose up -d             # start services
docker compose down              # stop services
docker compose logs -f           # follow logs
docker compose ps                # status
docker compose build             # rebuild images
docker compose restart <svc>     # restart one service

# Containers
docker ps                        # running containers
docker ps -a                     # all containers
docker logs <container>          # view logs
docker exec -it <container> bash # shell into container
docker stats                     # resource usage

# Images
docker images                    # list images
docker pull <image>              # pull image
docker rmi <image>               # remove image
docker system prune              # clean up unused

# Volumes
docker volume ls
docker volume create <name>
docker volume inspect <name>

# Networks
docker network ls
docker network inspect <name>

# Restart policy in compose:
# restart: unless-stopped  (recommended)
# restart: always
# restart: on-failure
```

## 10. SSH

```bash
# Server config: /etc/ssh/sshd_config
# Key settings:
#   Port 22
#   PermitRootLogin no
#   PasswordAuthentication no  (use keys)
#   PubkeyAuthentication yes

sudo systemctl restart sshd       # apply changes

# Key management
ssh-keygen -t ed25519 -C "comment"    # generate key
ssh-keygen -t rsa -b 4096              # RSA fallback
ssh-copy-id user@host                  # install public key
ssh-add                                # add key to agent
ssh -L 8080:localhost:80 user@host    # local port forward
ssh -R 8080:localhost:80 user@host    # remote port forward

# Known hosts
# ~/.ssh/known_hosts
ssh-keygen -R <hostname>               # remove stale host key
```

## 11. Firewall

```bash
# UFW (Ubuntu's firewall frontend)
sudo ufw status                    # current status
sudo ufw enable                    # enable firewall
sudo ufw disable                   # disable
sudo ufw allow 22/tcp               # allow SSH
sudo ufw allow 80/tcp               # allow HTTP
sudo ufw allow 443/tcp              # allow HTTPS
sudo ufw deny 3306                  # block MySQL
sudo ufw allow from 192.168.1.0/24 to any port 18789  # LAN only
sudo ufw delete allow 8080/tcp      # remove rule
sudo ufw reset                      # reset all rules

# iptables (lower level)
sudo iptables -L -n -v              # list rules
sudo iptables -A INPUT -p tcp --dport 22 -j ACCEPT   # allow SSH
sudo iptables -A INPUT -p tcp --dport 3306 -j DROP   # block MySQL
# Save/restore:
sudo iptables-save > /etc/iptables/rules.v4
sudo iptables-restore < /etc/iptables/rules.v4

# Persistent iptables via systemd service:
# /etc/systemd/system/iptables-restore.service
#ExecStart=/sbin/iptables-restore /etc/iptables/rules.v4
# Type=oneshot
# RemainAfterExit=yes
```

## 12. Performance & Monitoring

```bash
# Process monitoring
top                                # interactive process viewer
htop                               # better top (install: sudo apt install htop)
iotop                              # disk I/O monitor (sudo)
nethogs                            # per-process network usage

# Memory
free -h                            # memory usage
cat /proc/meminfo                  # detailed memory info

# Disk
df -h                              # filesystem usage
iostat -x 1                        # disk I/O stats (sysstat package)

# GPU (NVIDIA)
nvidia-smi                         # GPU summary
nvidia-smi -l 1                    # continuous monitoring
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv  # specific stats

# Network
iftop                             # network traffic (sudo)
nload                             # network throughput

# System info
uname -a                           # kernel version
lsb_release -a                     # Ubuntu version
uptime                             # load averages
lscpu                              # CPU info
lspci                              # PCI devices
lsusb                              # USB devices
dmesg | tail -20                   # recent kernel messages

# Performance tuning
nice -n 10 <command>              # run with lower priority
renice -n 5 -p <PID>              # change priority of running process
ulimit -a                          # shell resource limits
```

## Common Paths

```
/etc/systemd/system/         — system service units
~/.config/systemd/user/      — user service units
/etc/nginx/                  — nginx config
/etc/ssh/sshd_config         — SSH server config
/etc/fstab                   — filesystem mount table
/etc/crontab                 — system crontab
/etc/netplan/                — network configuration
/var/log/                    — system logs
~/.local/bin/                — user-local binaries (in PATH)
~/.local/share/              — user data
~/.config/                   — user configuration
~/.cache/                    — user cache
```
