# Bash Quick Reference

> Offline reference guide for AI agents. Last updated: 2026-07-10.

## Contents
1. Variables
2. Conditionals
3. Loops
4. Functions
5. Arrays & Strings
6. Pipes & Redirection
7. Exit Codes
8. Command Substitution
9. Traps & Signals
10. Common Utilities

## 1. Variables

```bash
VAR="hello"                    # no spaces around =
NUM=42
FLOAT=3.14
ARRAY=("a" "b" "c")

echo $VAR                      # reference
echo "$VAR"                    # safe quoting (handles spaces in values)
echo ${VAR}                    # explicit braces
echo "${VAR}_suffix"           # braces for concatenation
echo ${#VAR}                   # string length

# Environment / export
export GLOBAL_VAR="shared"     # available to child processes
unset VAR                      # remove variable

# Special variables
$0                             script name
$1 $2 ... ${10}                positional args
$@                             all args (separate words)
$*                             all args (single string)
$#                             arg count
$$                             PID of script
$!                             PID of last background job
$?                             exit code of last command
$_                             last arg of previous command

# Default values
echo ${VAR:-default}            # use default if unset/empty (doesn't set)
echo ${VAR:=default}            # use default and SET it
echo ${VAR:?error message}      # error if unset/empty

# String operations
STR="Hello World"
echo ${STR:0:5}                # substring: Hello
echo ${STR:6}                  # from index 6: World
echo ${STR#H}                  # remove prefix: ello World
echo ${STR%d}                  # remove suffix: Hello Worl
echo ${STR/World/Bash}         # replace first: Hello Bash
echo ${STR//l/L}               # replace all: HeLLo WorLd
echo ${STR,,}                  # to lowercase
echo ${STR^^}                  # to uppercase

# Integer arithmetic
RESULT=$(( 2 + 3 ))
RESULT=$(( $NUM * 2 ))
RESULT=$(( $NUM % 10 ))         # modulo
(( NUM++ ))                    # increment
(( NUM-- ))                    # decrement
(( NUM += 5 ))                 # compound assignment
```

## 2. Conditionals

```bash
# if/elif/else
if [ "$VAR" = "value" ]; then
    echo "match"
elif [ -z "$VAR" ]; then
    echo "empty"
else
    echo "no match"
fi

# [[ ]] — bash enhanced (preferred in bash)
if [[ "$VAR" == "value" ]]; then echo "match"; fi
if [[ "$STR" == *pattern* ]]; then echo "contains pattern"; fi
if [[ "$NUM" -gt 10 && "$NUM" -lt 20 ]]; then echo "in range"; fi
if [[ -f "file.txt" && -r "file.txt" ]]; then echo "readable file"; fi
if [[ "$STR" =~ ^[0-9]+$ ]]; then echo "numeric"; fi   # regex match

# File tests
[ -f file ]      regular file exists
[ -d dir ]       directory exists
[ -e path ]      exists (any type)
[ -r file ]      readable
[ -w file ]      writable
[ -x file ]      executable
[ -s file ]      not empty (size > 0)
[ -L link ]      symbolic link
[ file1 -nt file2 ]  newer than
[ file1 -ot file2 ]  older than

# String tests
[ -z "$str" ]    empty
[ -n "$str" ]    not empty
[ "$a" = "$b" ]  equal (use == in [[ ]])
[ "$a" != "$b" ] not equal

# Integer tests
[ "$a" -eq "$b" ]  equal
[ "$a" -ne "$b" ]  not equal
[ "$a" -lt "$b" ]  less than
[ "$a" -gt "$b" ]  greater than
[ "$a" -le "$b" ]  less or equal
[ "$a" -ge "$b" ]  greater or equal

# Case
case "$1" in
    start)  echo "Starting";;
    stop)   echo "Stopping";;
    restart) echo "Restarting";;
    *)      echo "Usage: $0 {start|stop|restart}"; exit 1;;
esac

# Case with patterns
case "$filename" in
    *.jpg|*.png)  echo "Image";;
    *.mp4|*.avi)  echo "Video";;
    *)            echo "Unknown";;
esac

# Ternary-like
[ condition ] && echo "yes" || echo "no"
```

## 3. Loops

```bash
# for
for i in 1 2 3 4 5; do echo $i; done
for i in {1..5}; do echo $i; done
for i in {0..100..10}; do echo $i; done   # step by 10
for f in *.txt; do echo "$f"; done
for arg in "$@"; do echo "Arg: $arg"; done

# C-style for
for ((i=0; i<10; i++)); do echo $i; done

# while
while [ condition ]; do echo "loop"; done
while read -r line; do echo "$line"; done < file.txt
while true; do echo "infinite — break to exit"; sleep 1; done

# until
until [ condition ]; do echo "waiting"; sleep 1; done

# break & continue
for i in {1..10}; do
    [ $i -eq 5 ] && break
    [ $(( i % 2 )) -eq 0 ] && continue
    echo $i
done

# Loop over command output
for f in $(find . -name "*.py"); do echo "$f"; done
# Better (handles spaces in filenames):
find . -name "*.py" | while read -r f; do echo "$f"; done
# Best:
while IFS= read -r f; do echo "$f"; done < <(find . -name "*.py")
```

## 4. Functions

```bash
# Basic
my_func() {
    echo "Hello $1"
    echo "Args: $@"
    echo "Count: $#"
    return 0                   # exit code, not a value
}
my_func "Wes" "extra"

# Return value via stdout
get_date() {
    date +%Y%m%d
}
TODAY=$(get_date)
echo $TODAY

# Return value via variable
parse_config() {
    local key=$1
    local val=$(grep "^$key=" config.env | cut -d= -f2)
    echo "$val"
}

# Local variables
counter() {
    local count=0
    ((count++))
    echo $count
}

# Anonymous functions (not native, but patterns):
# Inline via process substitution
result=$(echo "hello" | tr a-z A-Z)

# Default parameter values
greet() {
    local name=${1:-"World"}
    echo "Hello, $name"
}

# Pass array to function
show_array() {
    local arr=("$@")
    for item in "${arr[@]}"; do echo "$item"; done
}
show_array "${MY_ARRAY[@]}"
```

## 5. Arrays & Strings

```bash
# Indexed arrays
arr=("apple" "banana" "cherry")
echo ${arr[0]}                  # first element
echo ${arr[-1]}                 # last element
echo ${arr[@]}                  # all elements
echo ${#arr[@]}                 # count
echo ${#arr[0]}                 # length of first element
arr+=("date")                   # append
arr[2]="cherry2"                # update by index
unset arr[1]                   # remove element (index 1 becomes empty)
arr=("${arr[@]}")              # reindex after unset

# Associative arrays (bash 4+)
declare -A config
config[host]="localhost"
config[port]="8080"
config[name]="MyApp"
echo "${config[host]}"
for key in "${!config[@]}"; do echo "$key = ${config[$key]}"; done

# String splitting
IFS=',' read -ra parts <<< "a,b,c"
for part in "${parts[@]}"; do echo "$part"; done

# Read lines into array
mapfile -t lines < file.txt     # bash 4+
# or:
lines=()
while IFS= read -r line; do lines+=("$line"); done < file.txt

# String manipulation
str="  Hello World  "
trimmed="${str#"${str%%[![:space:]]*}"}"   # left trim
trimmed="${trimmed%"${trimmed##*[![:space:]]}"}"  # right trim
# or use extglob:
shopt -s extglob
trimmed="${str##+([[:space:]])}"    # left
trimmed="${trimmed%%+([[:space:]])}" # right
```

## 6. Pipes & Redirection

```bash
# Pipes
command1 | command2            # stdout → stdin
command1 |& command2            # stdout+stderr → stdin (bash 4+)

# Redirection
> file                         # stdout (overwrite)
>> file                        # stdout (append)
< file                         # stdin
2> file                        # stderr
2>&1                          # stderr → stdout
&> file                        # stdout+stderr (bash 4+)
>> file 2>&1                   # append stdout+stderr

# Process substitution
<(command)                     # output as temp file (input)
>(command)                     # input as temp file (output)
diff <(sort file1) <(sort file2)
comm <(grep "A" file) <(grep "B" file)

# Here documents
cat << EOF
multi-line text
with $variable expansion
EOF

# Here strings
grep "pattern" <<< "$text"

# File descriptor
exec 3> /tmp/log               # open fd 3
echo "log" >&3
exec 3>&-                      # close fd 3

# Reading multiple files
while read -r f1 <&3; do
    read -r f2 <&4
    echo "$f1 $f2"
done 3<file1 4<file2
```

## 7. Exit Codes

```bash
# Standard exit codes
0    success
1    general error
2    misuse
126  found but not executable
127  command not found
128  invalid exit argument
130  interrupted (Ctrl+C = 128 + 2)
137  killed (128 + 9)
130  terminated

# Check exit code
command
if [ $? -eq 0 ]; then echo "success"; fi
# Better:
if command; then echo "success"; else echo "failed"; fi
command && echo "succeeded" || echo "failed"

# Set exit codes
exit 0          # success
exit 1          # error
exit 2          # usage error

# Default in functions:
# Return value of last command

# set -e: exit on error
set -e          # any non-zero exit → script exits
set -e -o pipefail  # piped command failure → exit
# In functions, set -e only affects the function if not in a conditional
```

## 8. Command Substitution

```bash
# Modern
RESULT=$(date +%Y%m%d)
FILES=$(find . -name "*.py")
LINES=$(wc -l < file.txt)

# Legacy (backticks)
RESULT=`date +%Y%m%d`
# Nested is messy with backticks — prefer $()

# Process substitution (avoid subshell issues)
while read -r line; do
    echo "$line"
done < <(grep "pattern" file)
# Using | would run in subshell — variables set wouldn't persist

# Subshell isolation
x=1
(x=2; echo "inside: $x")
echo "outside: $x"  # x is still 1
```

## 9. Traps & Signals

```bash
# Trap signals for cleanup
cleanup() {
    rm -f /tmp/tempfile
    echo "Cleaned up"
}
trap cleanup EXIT              # run on script exit (any reason)
trap cleanup INT TERM          # run on Ctrl+C or kill

# Common signals
# INT  (2)  - Ctrl+C
# TERM (15) - termination signal (default for kill)
# KILL (9)  - cannot be trapped
# EXIT      - pseudo-signal, runs on script exit
# HUP  (1)  - hangup (terminal closed)

# Ignore a signal
trap '' INT                   # ignore Ctrl+C

# Reset trap
trap - INT                    # restore default behavior

# set options
set -e                        # exit on error
set -u                        # error on undefined variable
set -x                        # trace commands (debug)
set -o pipefail               # pipe returns rightmost non-zero
set -E                        # ERR trap inherited by functions
shopt -s globstar             # ** matches all files recursively
shopt -s nullglob             # no match → empty (not literal pattern)
```

## 10. Common Utilities

```bash
# grep
grep -rin "pattern" /dir       # recursive, case-insensitive, line numbers
grep -v "exclude" file         # invert match
grep -E "a|b" file             # extended regex
grep -c "pattern" file         # count matches
grep -o "pattern" file         # only matching text

# sed
sed 's/old/new/g' file         # global replace
sed -i 's/old/new/g' file     # in-place edit
sed -i.bak 's/old/new/g' file  # in-place with backup
sed '/pattern/d' file          # delete matching lines
sed -n '10,20p' file           # print lines 10-20

# awk
awk '{print $1}' file          # first column
awk -F',' '{print $2}' file    # CSV field 2
awk '{sum+=$1} END{print sum}' # sum column 1
awk 'NR>1' file                # skip header

# find
find . -name "*.py" -type f
find . -mtime -1               # modified in last 24h
find . -size +100M
find . -name "*.py" -exec grep "import" {} +
find . -name "*.py" -delete    # careful!

# xargs
find . -name "*.py" | xargs grep "pattern"
find . -name "*.bak" | xargs rm
cat urls.txt | xargs -I{} curl -s {}

# tar
tar -czf backup.tar.gz /dir    # create gzip
tar -xzf backup.tar.gz         # extract gzip
tar -tf backup.tar.gz          # list contents

# curl
curl -s -o output.txt https://example.com  # silent, save output
curl -X POST -d '{"key":"val"}' -H "Content-Type: application/json" URL
curl -f URL                     # fail on HTTP error
curl -I URL                     # headers only

# jq (JSON processing)
echo '{"name":"Wes"}' | jq '.name'
echo '[1,2,3]' | jq '.[]'       # iterate array
echo '{"a":1}' | jq 'keys'      # list keys
echo '[{"n":"a"},{"n":"b"}]' | jq '.[].n'  # extract field from array
```
