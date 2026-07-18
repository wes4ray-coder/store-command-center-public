# General Linux Quick Reference

> Offline reference guide for AI agents. Last updated: 2026-07-10.

## Contents
1. File Permissions
2. Process Management
3. Shell Basics
4. Text Processing
5. File Operations
6. Environment
7. Kernel
8. Boot Process

## 1. File Permissions

```bash
# View permissions
ls -l file.txt
# -rwxr-xr-- 1 owner group 4096 Jul 10 file.txt
#  ^^^ ^^^ ^^^
#  owner group others

# Change permissions
chmod 755 file          # rwxr-xr-x
chmod u+x file          # add execute for owner
chmod g-w file          # remove write for group
chmod a+r file          # add read for all
chmod -R 644 /dir       # recursive

# Numeric: r=4, w=2, x=1
# 7 = rwx, 6 = rw-, 5 = r-x, 4 = r--, 0 = ---

# Change ownership
chown user file
chown user:group file
chown -R user:group /dir

# Special bits
chmod u+s file          # setuid — run as owner
chmod g+s dir           # setgid — new files inherit group
chmod +t /dir           # sticky bit — only owner can delete

# ACLs (advanced)
getfacl file
setfacl -m u:username:rwx file
setfacl -x u:username file
```

## 2. Process Management

```bash
# View processes
ps aux                  # all processes
ps aux | grep nginx     # filter
top                     # interactive
htop                    # better top (install if needed)
pgrep -f "python"      # find by name pattern
pidof nginx             # get PID by name

# Kill processes
kill <PID>              # SIGTERM (graceful)
kill -9 <PID>           # SIGKILL (force)
killall nginx           # by name
pkill -f "python app"   # by pattern

# Job control
command &               # run in background
Ctrl+Z                  # suspend foreground
bg                      # resume in background
fg                      # bring to foreground
jobs                    # list background jobs
disown %1               # detach job from shell

# Priority
nice -n 10 command      # start with lower priority (higher = lower)
renice -n 5 -p <PID>    # change priority of running process
```

## 3. Shell Basics

```bash
# Variables
VAR="hello"             # no spaces around =
echo $VAR               # reference
export VAR              # make available to child processes
unset VAR               # remove variable

# Command substitution
RESULT=$(date +%Y%m%d)
RESULT=`date +%Y%m%d`   # deprecated but works

# Pipes
command1 | command2     # pipe stdout to stdin
command1 |& command2    # pipe stdout+stderr to stdin

# Redirection
> file                  # stdout to file (overwrite)
>> file                 # stdout to file (append)
< file                  # stdin from file
2> file                 # stderr to file
2>&1                    # stderr to stdout
&> file                 # stdout+stderr to file

# Conditionals
if [ "$VAR" = "value" ]; then
    echo "match"
elif [ -z "$VAR" ]; then
    echo "empty"
else
    echo "no match"
fi

# Test operators
[ -f file ]             # file exists and is regular
[ -d dir ]              # is directory
[ -z "$str" ]           # string is empty
[ -n "$str" ]           # string is not empty
[ "$a" = "$b" ]         # string equality
[ "$a" != "$b" ]        # string inequality
[ "$a" -eq "$b" ]       # integer equality
[ "$a" -lt "$b" ]       # integer less than
[ "$a" -gt "$b" ]       # integer greater than
[ "$a" -le "$b" ]       # less or equal
[ "$a" -ge "$b" ]       # greater or equal
[[ "$a" == pattern* ]]  # pattern matching (bash)

# Case
case "$1" in
    start) echo "Starting" ;;
    stop)  echo "Stopping" ;;
    *)     echo "Usage: $0 {start|stop}" ;;
esac

# Loops
for f in *.txt; do echo "$f"; done
for i in {1..10}; do echo "$i"; done
while [ condition ]; do echo "loop"; done
until [ condition ]; do echo "waiting"; done

# Functions
myfunc() {
    echo "Args: $@"
    echo "First: $1"
    echo "Count: $#"
    return 0
}
myfunc arg1 arg2
```

## 4. Text Processing

```bash
# grep — search
grep "pattern" file           # basic search
grep -i "pattern" file       # case-insensitive
grep -r "pattern" /dir        # recursive
grep -n "pattern" file        # line numbers
grep -v "pattern" file        # invert (lines NOT matching)
grep -E "pat1|pat2" file     # extended regex (alternation)
grep -c "pattern" file        # count matches
grep -o "pattern" file        # only matching part
rg "pattern" /dir             # ripgrep (faster, respects .gitignore)

# sed — stream editor
sed 's/old/new/' file         # replace first occurrence per line
sed 's/old/new/g' file        # replace all
sed -i 's/old/new/g' file    # in-place edit
sed -n '10,20p' file          # print lines 10-20
sed '/pattern/d' file          # delete matching lines
sed '5a\inserted line' file   # insert after line 5

# awk — column processing
awk '{print $1}' file         # print first column
awk -F',' '{print $2}' file  # CSV, print second column
awk 'NR==10' file             # print line 10
awk '$3 > 100' file           # rows where column 3 > 100
awk '{sum+=$1} END{print sum}' file  # sum column 1

# Other text tools
cut -d',' -f2 file           # extract field 2 (comma-delimited)
cut -c1-10 file              # extract chars 1-10
sort file                    # sort lines
sort -n file                 # numeric sort
sort -t',' -k2 -n file       # sort by field 2 numerically
uniq file                    # remove consecutive duplicates
sort file | uniq -c          # count unique lines
sort file | uniq -u          # show only unique lines
tr 'a-z' 'A-Z' < file        # translate lowercase to uppercase
tr -d '\n' < file            # delete all newlines
wc -l file                   # count lines
wc -w file                   # count words
wc -c file                   # count chars
head -20 file                # first 20 lines
tail -20 file                # last 20 lines
tail -f file                 # follow file (for logs)
```

## 5. File Operations

```bash
# find
find /dir -name "*.py"              # by name
find /dir -type f -name "*.log"    # files only
find /dir -type d -name "temp"     # directories only
find /dir -mtime -1                  # modified in last 24h
find /dir -size +100M                # larger than 100MB
find /dir -name "*.py" -exec grep "import" {} +
find /dir -name "*.py" -exec rm {} \;  # DANGEROUS: delete matches
find /dir -maxdepth 2 -name "*.md"   # limit depth

# locate (uses database, faster than find)
locate filename
sudo updatedb                      # update database

# rsync
rsync -av /src/ /dest/             # archive + verbose (with trailing /)
rsync -av --delete /src/ /dest/    # delete files in dest not in src
rsync -avz user@host:/remote/ /local/  # over SSH with compression

# tar
tar -czf archive.tar.gz /dir       # create gzip
tar -xzf archive.tar.gz            # extract gzip
tar -xzf archive.tar.gz -C /dir    # extract to specific dir
tar -tf archive.tar.gz             # list contents
tar -cjf archive.tar.bz2 /dir      # bzip2 (slower, smaller)
tar -xjf archive.tar.bz2           # extract bzip2
tar -cf archive.tar /dir           # uncompressed

# zip/unzip
zip -r archive.zip /dir
unzip archive.zip -d /dir
```

## 6. Environment

```bash
# PATH
echo $PATH                          # current PATH
export PATH="/new/bin:$PATH"        # prepend
# Permanent: add to ~/.bashrc or ~/.profile

# Shell config files (order of execution for login shell):
# /etc/profile → ~/.bash_profile → ~/.bashrc (if interactive)

# For non-login interactive shell:
# ~/.bashrc

# Common env vars
HOME        # user home directory
USER        # current username
SHELL       # default shell
PWD         # current directory
LANG        # locale
TERM        # terminal type

# Set environment
export VAR="value"                   # current shell + children
VAR="value" command                  # only for this command

# Aliases
alias ll='ls -la'
alias gs='git status'
# Permanent: add to ~/.bashrc

# Functions in .bashrc
mkcd() { mkdir -p "$1" && cd "$1"; }
```

## 7. Kernel

```bash
# Kernel info
uname -r                             # kernel version
uname -a                             # all info
cat /proc/version                    # kernel version string

# Kernel modules
lsmod                                # list loaded modules
modinfo <module>                     # module info
sudo modprobe <module>               # load module
sudo modprobe -r <module>            # remove module

# Kernel parameters (sysctl)
sysctl -a                            # list all parameters
sysctl net.ipv4.ip_forward           # get specific
sudo sysctl -w net.ipv4.ip_forward=1 # set temporarily
# Permanent: /etc/sysctl.d/*.conf

# /proc filesystem
cat /proc/cpuinfo                    # CPU info
cat /proc/meminfo                    # memory info
cat /proc/loadavg                    # load averages
cat /proc/<pid>/status               # process info
cat /proc/filesystems                # supported filesystems

# /sys filesystem (sysfs)
ls /sys/class/net/                   # network interfaces
cat /sys/class/thermal/temp          # temperature
```

## 8. Boot Process

```bash
# GRUB (bootloader)
# Config: /etc/default/grub
# Custom: /etc/grub.d/
sudo update-grub                     # regenerate config (Debian/Ubuntu)

# Common GRUB settings:
# GRUB_TIMEOUT=5
# GRUB_DEFAULT=0
# GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"

# Run levels / targets (systemd)
systemctl get-default                # current default target
sudo systemctl set-default multi-user.target   # CLI
sudo systemctl set-default graphical.target     # GUI

# systemd rescue
systemctl rescue                     # single user mode
systemctl emergency                  # minimal emergency shell

# Init systems (legacy)
# SysV init: /etc/init.d/ scripts
# Upstart: /etc/init/ configs
# systemd: /lib/systemd/system/ and /etc/systemd/system/

# Boot logs
journalctl -b                        # current boot
journalctl -b -1                      # previous boot
journalctl --list-boots               # list boot sessions
dmesg                                 # kernel ring buffer
```
