# macOS Quick Reference

> Offline reference guide for AI agents. Last updated: 2026-07-10.

## Contents
1. Terminal Basics
2. Package Management (Homebrew)
3. Launch Services
4. File System
5. Networking
6. System Info
7. Defaults (Preferences)
8. Accessibility
9. Developer Tools

## 1. Terminal Basics

```bash
# Default shell on macOS: zsh (since Catalina)
# Config files: ~/.zshrc, ~/.zprofile

# Homebrew (essential package manager)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew --version

# Shell tricks (zsh)
!!                  # repeat last command
!$                  # last argument of last command
cd -                # go back to previous directory
pushd /dir && popd  # save/restore directory stack

# macOS-specific commands
open .                       # open current folder in Finder
open -a "Safari" URL         # open URL in Safari
open -e file.txt            # open in TextEdit
pbcopy < file.txt            # copy file contents to clipboard
pbpaste > file.txt          # paste clipboard to file
caffeinate                  # prevent sleep (Ctrl-C to stop)
caffeinate -t 3600          # prevent sleep for 1 hour
say "hello"                  # text-to-speech
say -f file.txt              # speak file contents
```

## 2. Package Management (Homebrew)

```bash
# Install packages
brew install <package>          # CLI tools
brew install --cask <app>        # GUI applications

# Update
brew update                      # update Homebrew itself
brew upgrade                     # upgrade all packages
brew upgrade <package>           # upgrade specific package
brew upgrade --cask --greedy     # upgrade all casks (including auto-updates)

# Search
brew search <term>               # search packages
brew info <package>              # package details
brew leaves                      # top-level packages (no dependencies)

# Remove
brew uninstall <package>
brew uninstall --cask <app>
brew autoremove                  # remove unused dependencies

# Services
brew services list
brew services start postgresql
brew services stop postgresql
brew services restart postgresql
brew services cleanup

# Cleanup
brew cleanup                     # remove old downloads
brew cleanup -s                  # aggressive cleanup

# Cask examples
brew install --cask visual-studio-code
brew install --cask docker
brew install --cask firefox
brew install --cask slack
```

## 3. Launch Services

```bash
# launchctl (like systemd for macOS)
# LaunchAgents run in user session
# LaunchDaemons run as system

# User agents: ~/Library/LaunchAgents/
# System agents: /Library/LaunchAgents/
# System daemons: /Library/LaunchDaemons/

# List loaded
launchctl list

# Start/stop
launchctl start <label>
launchctl stop <label>
launchctl kill SIGTERM <label>

# Load/unload plist
launchctl load ~/Library/LaunchAgents/com.user.task.plist
launchctl unload ~/Library/LaunchAgents/com.user.task.plist

# Bootstrap (newer API, macOS 10.10+)
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.task.plist
launchctl bootout gui/$(id -u)/com.user.task

# Example plist (~/Library/LaunchAgents/com.user.backup.plist)
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.backup</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>/Users/wesley/backup.sh</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>3</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/backup.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/backup.err</string>
</dict>
</plist>
```

## 4. File System

```bash
# APFS (Apple File System) — default since macOS 10.13
# Case-insensitive by default, supports snapshots, clones, encryption

# Disk utility
diskutil list                     # list all disks
diskutil info disk0               # disk info
diskutil eraseDisk APFS "MyDisk" disk2  # format
diskutil apfs list                # APFS containers
diskutil apfs resizeContainer disk0s2 0  # use all available

# Mount/unmount
diskutil unmount /Volumes/USB
diskutil mount /dev/disk2s1
mount_apfs /dev/disk2s1 /mnt

# File permissions
ls -la                           # view permissions
chmod 755 file
chown user:staff file             # group is often "staff" on macOS
chmod +x script.sh

# Extended attributes
xattr file.txt                    # list attributes
xattr -l file.txt                 # list with values
xattr -w com.apple.metadata:kMDItemFinderComment "Comment" file.txt
xattr -d com.apple.quarantine file.txt  # remove quarantine flag

# Common paths
~/Library/                       # user data (prefs, caches, app support)
~/Library/Application Support/    # app data (like %APPDATA%)
~/Library/Preferences/            # preference plists
~/Library/Caches/                 # app caches
~/Library/LaunchAgents/           # user launch agents
/Library/LaunchAgents/            # system launch agents
/Library/LaunchDaemons/          # system daemons
/Applications/                    # installed apps
/usr/local/bin/                   # Homebrew binaries (Intel)
/opt/homebrew/bin/                # Homebrew binaries (Apple Silicon)
```

## 5. Networking

```bash
# Network interfaces
ifconfig                          # all interfaces
ifconfig en0                      # primary ethernet/Wi-Fi
ifconfig en0 down                 # disable interface
ifconfig en0 up                   # enable interface

# Network settings (macOS-specific)
networksetup -listallnetworkservices
networksetup -getinfo Wi-Fi
networksetup -setmanual Wi-Fi 192.168.1.10 255.255.255.0 192.168.1.1
networksetup -setdnsservers Wi-Fi 8.8.8.8
networksetup -setsearchdomains Wi-Fi example.com

# Connection test
ping hostname
traceroute hostname
nc -zv hostname 443               # port test (netcat)
curl -I https://example.com

# Wi-Fi
airport -I                        # current Wi-Fi info (older macOS)
/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -I
networksetup -setairportnetwork en0 "SSID" "password"

# Firewall
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --setglobalstate on
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /path/to/app
```

## 6. System Info

```bash
# System version
sw_vers                           # macOS version
sw_vers -productVersion           # just version number
uname -a                          # kernel info

# Hardware info
system_profiler                   # full system profile
system_profiler SPHardwareDataType   # hardware summary
system_profiler SPStorageDataType     # storage
system_profiler SPDisplaysDataType    # displays/GPU
system_profiler SPNetworkDataType     # network

# Serial number
system_profiler SPHardwareDataType | grep "Serial Number"

# Memory
vm_stat                           # memory stats
sysctl hw.memsize                # total RAM (bytes)

# CPU
sysctl -n machdep.cpu.brand_string   # CPU model
sysctl hw.ncpu                    # number of CPUs
sysctl hw.physicalcpu             # physical cores
sysctl hw.logicalcpu              # logical cores

# Updates
softwareupdate -l                 # list available updates
sudo softwareupdate -i -a         # install all updates
sudo softwareupdate --install-rosetta  # install Rosetta 2 (Apple Silicon)

# Uptime
uptime
```

## 7. Defaults (Preferences)

```bash
# defaults — read/write macOS preference plists
# Stored as XML in ~/Library/Preferences/

# Read
defaults read com.apple.finder    # all finder prefs
defaults read com.apple.dock       # dock prefs
defaults read com.apple.safari    # safari prefs
defaults read <bundle-id> <key>    # specific key

# Write
defaults write com.apple.finder AppleShowAllFiles -bool true   # show hidden files
defaults write com.apple.dock autohide -bool true               # auto-hide dock
defaults write com.apple.dock orientation -string right        # dock on right
defaults write com.apple.safari IncludeInternalDebugMenu -bool true

# Delete
defaults delete com.apple.finder <key>    # reset specific key
defaults delete com.apple.finder          # reset all finder prefs

# Common useful settings
defaults write NSGlobalDomain AppleShowScrollBars -string "Always"
defaults write NSGlobalDomain NSAutomaticWindowAnimationsEnabled -bool false
defaults write NSGlobalDomain KeyRepeat -int 2
defaults write NSGlobalDomain InitialKeyRepeat -int 15
defaults write com.apple.screencapture location -string ~/Pictures/Screenshots

# Restart the service after changes
killall Finder
killall Dock
killall SystemUIServer

# Plist editing (command-line)
plutil -convert xml1 ~/Library/Preferences/com.apple.finder.plist
plutil -p ~/Library/Preferences/com.apple.finder.plist    # print plist
plutil -insert <key> -<type> <value> file.plist
```

## 8. Accessibility

```bash
# Accessibility permissions needed for automation
# System Settings > Privacy & Security > Accessibility

# Check if app has accessibility permission
sqlite3 ~/Library/Application\ Support/com.apple.TCC/TCC.db \
  "SELECT client FROM access WHERE service='kTCCServiceAccessibility';"

# Grant via terminal (requires user approval dialog)
# System Settings > Privacy & Security > Accessibility > Add Terminal/your-app

# macOS automation permissions
# osascript triggers permission prompts
osascript -e 'tell application "Safari" to activate'

# Siri/Shortcuts
shortcuts list                          # list available shortcuts
shortcuts run "Shortcut Name"          # run a shortcut
```

## 9. Developer Tools

```bash
# Xcode Command Line Tools (without full Xcode)
xcode-select --install                 # install CLI tools
xcode-select -p                        # show path
sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer

# Swift
swift --version
swift package init --type executable
swift build
swift test

# Xcode
xcodebuild -list                        # list schemes/targets
xcodebuild -scheme "MyApp" build        # build
xcodebuild -scheme "MyApp" test         # test
xcodebuild -scheme "MyApp" -destination 'platform=iOS Simulator,name=iPhone 15' build

# Simulator (iOS)
xcrun simctl list devices               # list simulators
xcrun simctl create "Test" "iPhone 15" # create simulator
xcrun simctl boot <UDID>                # boot simulator
xcrun simctl install <UDID> app.app     # install app
xcrun simctl uninstall <UDID> <bundle-id>
xcrun simctl erase <UDID>               # reset simulator
xcrun simctl delete <UDID>              # delete simulator

# Instruments (profiling)
instruments -s devices                  # list connected devices
instruments -t "Time Profiler" -w "device" app

# Codesigning
codesign -s "Developer ID Application" app.app
codesign -v app.app                     # verify
codesign -dvvv app.app                  # details

# App Store Connect
xcrun altool --upload-app -f app.ipa --type ios
```
