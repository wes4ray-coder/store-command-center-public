# Windows Quick Reference

> Offline reference guide for AI agents. Last updated: 2026-07-10.

## Contents
1. PowerShell Basics
2. CMD Basics
3. File System
4. Services
5. Registry
6. Networking
7. WMI/CIM
8. Task Scheduler
9. Event Logs
10. Common Admin Tasks

## 1. PowerShell Basics

```powershell
# Cmdlets: Verb-Noun pattern
Get-Process                          # list processes
Get-Service                          # list services
Get-ChildItem                        # list files (alias: ls, dir)
Get-Content file.txt                 # read file (alias: cat)
Get-Location                         # current directory (alias: pwd)

# Variables
$var = "hello"
$number = 42
$array = @(1, 2, 3)
$hash = @{ Name = "Wes"; Age = 30 }

# Pipes (pass objects, not text)
Get-Process | Where-Object { $_.CPU -gt 10 } | Select-Object Name, CPU

# Filtering
Get-Service | Where-Object { $_.Status -eq "Running" }
Get-ChildItem | Where-Object { $_.Length -gt 1MB }

# Sorting & selecting
Get-Process | Sort-Object CPU -Descending | Select-Object -First 10
Get-ChildItem | Select-Object Name, Length, LastWriteTime

# Formatting
Get-Process | Format-Table Name, CPU, WS -AutoSize
Get-Service | Format-List *
Get-Process | Format-Wide -Column 3

# Loops
foreach ($item in $collection) { Write-Host $item }
1..10 | ForEach-Object { $_ * 2 }
while ($true) { Start-Sleep -Seconds 1 }

# Conditionals
if ($val -eq 10) { "ten" }
elseif ($val -gt 10) { "bigger" }
else { "smaller" }

# Comparison operators: -eq, -ne, -gt, -lt, -ge, -le, -like, -match, -contains
# String: -eq (case-insensitive), -ceq (case-sensitive)

# Functions
function Get-Greeting {
    param([string]$Name = "World")
    return "Hello, $Name!"
}
Get-Greeting -Name "Wesley"

# Error handling
try {
    Get-Content "missing.txt" -ErrorAction Stop
} catch {
    Write-Error "Failed: $_"
} finally {
    # cleanup
}

# Modules
Get-Module -ListAvailable
Import-Module PSReadLine
Install-Module -Name Az -Scope CurrentUser
```

## 2. CMD Basics

```cmd
:: Basic commands
dir /b                            :: list files (names only)
dir /s /b *.py                    :: recursive search
cd \Users\wesley                  :: change directory
copy file.txt backup.txt          :: copy
move file.txt /dir/               :: move
del file.txt                      :: delete
ren old.txt new.txt               :: rename
mkdir newfolder                   :: create directory
rmdir /s /q folder               :: delete directory recursively
type file.txt                     :: display content
echo hello > file.txt             :: write to file
echo hello >> file.txt            :: append
findstr "pattern" file.txt       :: search (like grep)
tasklist | findstr python         :: filter

:: Environment
set VAR=value                     :: set variable
echo %VAR%                        :: use variable
set /p INPUT="Enter: "           :: prompt for input
setx PATH "%PATH%;C:\new\path"    :: permanent PATH change

:: Networking
ipconfig                          :: IP config
ipconfig /all                     :: detailed
ipconfig /release                 :: release DHCP
ipconfig /renew                   :: renew DHCP
ping hostname                     :: ping
nslookup hostname                 :: DNS lookup
netstat -an                       :: all connections
tracert hostname                  :: traceroute
```

## 3. File System

```powershell
# Paths (backslash or forward slash both work in PS)
C:\Users\wesley\file.txt
.\relative\path.txt
..\parent\dir

# Permissions (ACLs)
Get-Acl C:\folder
$acl = Get-Acl C:\folder
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    "username", "FullControl", "Allow"
)
$acl.AddAccessRule($rule)
Set-Acl C:\folder $acl

# File attributes
Get-ItemProperty file.txt | Select-Object Attributes
Set-ItemProperty file.txt -Name IsReadOnly -Value $true

# Long paths (>260 chars): enable in registry
# HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled = 1

# Common paths
$env:USERPROFILE                   # C:\Users\wesley
$env:APPDATA                       # Roaming app data
$env:LOCALAPPDATA                  # Local app data
$env:PROGRAMFILES                  # C:\Program Files
$env:WINDIR                        # C:\Windows
$env:TEMP                          # Temp directory
```

## 4. Services

```powershell
# List services
Get-Service
Get-Service | Where-Object { $_.Status -eq "Running" }

# Manage services
Start-Service -Name "Spooler"
Stop-Service -Name "Spooler"
Restart-Service -Name "Spooler"
Set-Service -Name "Spooler" -StartupType Automatic

# Service dependencies
Get-Service -Name "Spooler" -DependentServices
Get-Service -Name "Spooler" -RequiredServices

# WMI/CIM for services
Get-CimInstance -ClassName Win32_Service | Where-Object { $_.State -eq "Running" }

# sc.exe (CMD)
sc query                           # list all
sc start "ServiceName"
sc stop "ServiceName"
sc config "ServiceName" start= auto
sc create "NewService" binPath= "C:\app\service.exe"
sc delete "ServiceName"
```

## 5. Registry

```powershell
# Read registry
Get-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion"
Get-ItemProperty -Path "HKCU:\Control Panel\Desktop" -Name Wallpaper

# Write registry
Set-ItemProperty -Path "HKLM:\SOFTWARE\MyApp" -Name "Setting" -Value "NewValue"
New-Item -Path "HKLM:\SOFTWARE\MyApp" -Force
New-ItemProperty -Path "HKLM:\SOFTWARE\MyApp" -Name "Version" -Value 1 -PropertyType DWord

# Delete registry
Remove-Item -Path "HKLM:\SOFTWARE\MyApp" -Recurse
Remove-ItemProperty -Path "HKLM:\SOFTWARE\MyApp" -Name "Setting"

# Registry hives
# HKLM:\  = HKEY_LOCAL_MACHINE
# HKCU:\  = HKEY_CURRENT_USER
# HKCR:\  = HKEY_CLASSES_ROOT (links to HKLM\SOFTWARE\Classes)
# HKU:\   = HKEY_USERS

# CMD reg commands
reg query "HKLM\SOFTWARE\MyApp"
reg add "HKLM\SOFTWARE\MyApp" /v Version /t REG_DWORD /d 1
reg delete "HKLM\SOFTWARE\MyApp" /v Setting /f
reg export "HKLM\SOFTWARE\MyApp" backup.reg
reg import backup.reg
```

## 6. Networking

```powershell
# Adapters
Get-NetAdapter
Get-NetAdapter | Where-Object { $_.Status -eq "Up" }
Get-NetIPAddress -InterfaceAlias "Ethernet"

# IP config
Get-NetIPAddress
New-NetIPAddress -InterfaceAlias "Ethernet" -IPAddress 192.168.1.10 -PrefixLength 24
Set-NetIPAddress -InterfaceAlias "Ethernet" -IPAddress 192.168.1.11

# DNS
Get-DnsClientServerAddress
Set-DnsClientServerAddress -InterfaceAlias "Ethernet" -ServerAddresses "8.8.8.8"

# Firewall
Get-NetFirewallRule
New-NetFirewallRule -Name "Allow-Port" -DisplayName "Allow Port 8080" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow
Remove-NetFirewallRule -Name "Allow-Port"

# Test connectivity
Test-Connection -ComputerName google.com -Count 4   # ping
Test-NetConnection -ComputerName google.com -Port 443  # port test
Resolve-DnsName google.com

# netsh (CMD)
netsh interface ip show config
netsh advfirewall firewall add rule name="Allow80" dir=in action=allow protocol=TCP localport=80
netsh advfirewall firewall delete rule name="Allow80"
```

## 7. WMI/CIM

```powershell
# WMI (older, COM-based)
Get-WmiObject -Class Win32_OperatingSystem
Get-WmiObject -Class Win32_Process
Get-WmiObject -Class Win32_LogicalDisk -Filter "DriveType=3"

# CIM (newer, WS-Man based — preferred)
Get-CimInstance -ClassName Win32_OperatingSystem
Get-CimInstance -ClassName Win32_Process | Select-Object Name, ProcessId, WorkingSetSize
Get-CimInstance -ClassName Win32_LogicalDisk -Filter "DriveType=3" | Select-Object DeviceID, FreeSpace, Size

# System info
Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer, Model, TotalPhysicalMemory
Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, MaxClockSpeed

# BIOS
Get-CimInstance Win32_BIOS | Select-Object Manufacturer, SerialNumber, Version

# Network
Get-CimInstance Win32_NetworkAdapterConfiguration | Where-Object { $_.IPEnabled -eq $true }

# Disk
Get-Disk
Get-Partition
Get-Volume
```

## 8. Task Scheduler

```powershell
# List scheduled tasks
Get-ScheduledTask
Get-ScheduledTask | Where-Object { $_.State -eq "Ready" }

# Create a scheduled task
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-File C:\script.ps1"
$trigger = New-ScheduledTaskTrigger -Daily -At 3am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName "Backup" -Action $action -Trigger $trigger -Settings $settings

# Manage tasks
Start-ScheduledTask -TaskName "Backup"
Stop-ScheduledTask -TaskName "Backup"
Disable-ScheduledTask -TaskName "Backup"
Enable-ScheduledTask -TaskName "Backup"
Unregister-ScheduledTask -TaskName "Backup"

# CMD schtasks
schtasks /create /tn "Backup" /tr "powershell.exe C:\script.ps1" /sc daily /st 03:00
schtasks /run /tn "Backup"
schtasks /end /tn "Backup"
schtasks /delete /tn "Backup" /f
schtasks /query /fo LIST /v
```

## 9. Event Logs

```powershell
# Event logs
Get-EventLog -LogName System -Newest 50
Get-EventLog -LogName Application -Newest 50 -EntryType Error
Get-EventLog -LogName Security -Newest 20

# Get-WinEvent (faster, more powerful)
Get-WinEvent -LogName Application -MaxEvents 20
Get-WinEvent -FilterHashtable @{LogName='Application'; Level=2} -MaxEvents 20  # errors only
Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=(Get-Date).AddDays(-1)}

# wevtutil (CMD)
wevtutil qe Application /c:50 /f:text
wevtutil el                         # list all log names
wevtutil epl Application backup.evtx # export log
```

## 10. Common Admin Tasks

```powershell
# System info
systeminfo
Get-ComputerInfo
$env:OS
Get-Host | Select-Object Version

# Installed software
Get-CimInstance Win32_Product | Select-Object Name, Version
Get-Package                           # PSGet packages

# Users
Get-LocalUser
New-LocalUser -Name "username" -Password (Read-Host -AsSecureString)
Enable-LocalUser -Name "username"
Disable-LocalUser -Name "username"
Remove-LocalUser -Name "username"

# Groups
Get-LocalGroup
Add-LocalGroupMember -Group "Administrators" -Member "username"
Remove-LocalGroupMember -Group "Administrators" -Member "username"

# Disk cleanup
Get-PSDrive C | Select-Object Used, Free
Optimize-Volume -DriveLetter C -Analyze

# Shutdown/restart
Stop-Computer
Restart-Computer
Stop-Computer -Force

# Remote
Enter-PSSession -ComputerName server01
Invoke-Command -ComputerName server01 -ScriptBlock { Get-Process }
New-PSSession -ComputerName server01

# Chocolatey (package manager, like apt)
choco install python
choco install vscode
choco upgrade all
choco list --local-only
```
