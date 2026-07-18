# Python Quick Reference

> Offline reference guide for AI agents. Last updated: 2026-07-10.

## Contents
1. [Syntax Basics](#syntax-basics)
2. [Types & Data Structures](#types--data-structures)
3. [Control Flow](#control-flow)
4. [Functions](#functions)
5. [Classes & OOP](#classes--oop)
6. [Error Handling](#error-handling)
7. [Decorators](#decorators)
8. [Type Hints](#type-hints)
9. [Async / Await](#async--await)
10. [File I/O](#file-io)
11. [Common Stdlib](#common-stdlib)
12. [Virtualenvs & pip](#virtualenvs--pip)
13. [Gotchas](#gotchas)

---

## Syntax Basics

```python
# Comments use #
# Multiple assignment
a, b, c = 1, 2, 3

# Swap variables
a, b = b, a

# f-strings (Python 3.6+)
name = "world"
print(f"Hello, {name}!")
print(f"{2 + 3 = }")  # Debug: prints "2 + 3 = 5"

# String methods
"hello".upper()          # "HELLO"
"hello world".split()    # ["hello", "world"]
",".join(["a", "b"])     # "a,b"
"  trim  ".strip()       # "trim"
"hello".replace("l", "L")# "heLLo"

# Slicing
s = "hello"
s[1:4]       # "ell"
s[::-1]      # "olleh" (reverse)
s[-1]        # "o"

# Walrus operator (3.8+)
if (n := len("hello")) > 3:
    print(f"Length is {n}")
```

## Types & Data Structures

```python
# --- Lists (mutable, ordered) ---
lst = [1, 2, 3]
lst.append(4)          # [1, 2, 3, 4]
lst.extend([5, 6])     # [1, 2, 3, 4, 5, 6]
lst.insert(0, 0)       # [0, 1, 2, 3, 4, 5, 6]
lst.pop()              # removes last, returns 6
lst.pop(0)             # removes index 0, returns 0
lst.remove(2)          # removes first occurrence of 2
lst.sort()             # in-place sort
lst.reverse()          # in-place reverse
lst.index(3)           # find index of value
lst.count(3)           # count occurrences
# List comprehension
squares = [x**2 for x in range(10)]
evens = [x for x in range(20) if x % 2 == 0]
flat = [n for row in matrix for n in row]  # flatten

# --- Tuples (immutable, ordered) ---
t = (1, 2, 3)
single = (42,)         # single-element tuple needs comma
a, b, c = t            # unpacking

# --- Dictionaries (mutable, insertion-ordered 3.7+) ---
d = {"key": "value", "num": 42}
d["new"] = "val"
d.get("missing", "default")  # safe access
d.pop("key")                 # remove and return
d.update({"a": 1, "b": 2})   # merge
d.keys(), d.values(), d.items()
# Dict comprehension
squared = {k: v**2 for k, v in d.items() if isinstance(v, (int, float))}
# Python 3.9+ merge
merged = {"a": 1} | {"b": 2}  # {"a": 1, "b": 2}

# --- Sets (mutable, unordered, unique) ---
s = {1, 2, 3}
s.add(4)
s.remove(1)            # KeyError if not found
s.discard(1)           # safe remove
{1, 2} | {2, 3}       # union: {1, 2, 3}
{1, 2} & {2, 3}       # intersection: {2}
{1, 2} - {2, 3}       # difference: {1}
{1, 2} ^ {2, 3}       # symmetric difference: {1, 3}

# --- frozenset (immutable set) ---
fs = frozenset([1, 2, 3])

# --- None, bool ---
None                    # null value
True, False            # booleans (capitalized!)
bool(0), bool("")       # False
bool([]), bool(None)    # False
bool(1), bool("text")   # True
```

## Control Flow

```python
# if/elif/else
if x > 10:
    ...
elif x > 5:
    ...
else:
    ...

# Ternary
result = "yes" if condition else "no"

# match-case (3.10+)
match status:
    case 200:
        print("OK")
    case 404:
        print("Not found")
    case _:
        print("Unknown")

# for loop
for item in iterable:
    ...
for i, item in enumerate(items):
    print(f"{i}: {item}")
for a, b in zip(list1, list2):
    ...

# while
while condition:
    ...
    if done:
        break
    if skip:
        continue
else:
    # runs if loop completes without break
    ...

# range
range(10)        # 0..9
range(2, 10)     # 2..9
range(0, 10, 2)  # 0, 2, 4, 6, 8
```

## Functions

```python
# Basic
def add(a, b):
    return a + b

# Default args
def greet(name, greeting="Hello"):
    return f"{greeting}, {name}!"

# *args and **kwargs
def func(*args, **kwargs):
    print(args)    # tuple of positional
    print(kwargs)  # dict of keyword

# Keyword-only args (after *)
def func(a, b, *, required, optional=True):
    ...

# Positional-only args (before /)
def func(a, b, /, c, d):
    ...  # a, b must be positional

# Lambda
sq = lambda x: x**2
pairs = sorted(items, key=lambda x: x[1])

# Unpacking in calls
def add(a, b, c): return a + b + c
nums = [1, 2, 3]
add(*nums)             # unpack list
add(**{"a": 1, "b": 2, "c": 3})  # unpack dict

# Generators
def counter():
    i = 0
    while True:
        yield i
        i += 1

def batch_gen(items, size):
    for i in range(0, len(items), size):
        yield items[i:i+size]

# Generator expression
total = sum(x**2 for x in range(100))
```

## Classes & OOP

```python
class Animal:
    species = "Unknown"  # class attribute

    def __init__(self, name, age):
        self.name = name
        self.age = age

    def speak(self):
        return f"{self.name} makes a sound"

    def __repr__(self):
        return f"Animal({self.name!r}, {self.age})"

    def __str__(self):
        return f"{self.name} ({self.age} years old)"

    def __eq__(self, other):
        return self.name == other.name

    def __lt__(self, other):
        return self.age < other.age

    def __len__(self):
        return self.age

    def __getitem__(self, key):
        return getattr(self, key)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False  # don't suppress exceptions

class Dog(Animal):
    def __init__(self, name, age, breed):
        super().__init__(name, age)
        self.breed = breed

    def speak(self):
        return f"{self.name} barks!"

# Property decorator
class Temperature:
    def __init__(self, celsius):
        self._celsius = celsius

    @property
    def fahrenheit(self):
        return self._celsius * 9/5 + 32

    @fahrenheit.setter
    def fahrenheit(self, f):
        self._celsius = (f - 32) * 5/9

# Dataclasses (3.7+)
from dataclasses import dataclass, field

@dataclass
class Point:
    x: float
    y: float
    label: str = ""
    tags: list = field(default_factory=list)
    # auto-generates __init__, __repr__, __eq__

# Abstract base class
from abc import ABC, abstractmethod

class Shape(ABC):
    @abstractmethod
    def area(self) -> float:
        ...

# Static / class methods
class MyClass:
    @staticmethod
    def utility():
        return "no self needed"

    @classmethod
    def create(cls, val):
        return cls(val)
```

## Error Handling

```python
try:
    result = risky_operation()
except ValueError as e:
    print(f"Value error: {e}")
except (TypeError, KeyError) as e:
    print(f"Type/Key error: {e}")
except Exception as e:
    print(f"Unexpected: {e}")
    raise  # re-raise
else:
    print("No exception occurred")
finally:
    print("Always runs")

# Raise with context
raise ValueError("bad input") from original_error

# Custom exceptions
class MyError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code

# Exception groups (3.11+)
try:
    ...
except* OSError as eg:
    ...
except* ValueError as eg:
    ...

# Common built-in exceptions
# ValueError, TypeError, KeyError, IndexError, AttributeError
# FileNotFoundError, PermissionError, RuntimeError
# StopIteration, NotImplementedError, OverflowError
```

## Decorators

```python
import time
from functools import wraps, lru_cache

def timer(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        print(f"{func.__name__}: {time.perf_counter() - start:.4f}s")
        return result
    return wrapper

@timer
def slow_function():
    time.sleep(1)

# Decorator with arguments
def repeat(n):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for _ in range(n):
                result = func(*args, **kwargs)
            return result
        return wrapper
    return decorator

@repeat(3)
def greet(name):
    print(f"Hi {name}")

# LRU cache
@lru_cache(maxsize=128)
def fibonacci(n):
    if n < 2:
        return n
    return fibonacci(n-1) + fibonacci(n-2)

# Class as decorator
class CallCounter:
    def __init__(self, func):
        self.func = func
        self.count = 0

    def __call__(self, *args, **kwargs):
        self.count += 1
        return self.func(*args, **kwargs)
```

## Type Hints

```python
from typing import (
    Optional, Union, List, Dict, Tuple, Set,
    Callable, Any, TypeVar, Generic, Protocol,
    Literal, TypedDict
)

# Basic
def greet(name: str) -> str:
    return f"Hello, {name}"

# Optional / Union
def parse(s: str) -> Optional[int]:
    try:
        return int(s)
    except ValueError:
        return None

# Collections (3.9+ built-in syntax)
def process(items: list[str]) -> dict[str, int]:
    return {item: len(item) for item in items}

# Tuple
coords: tuple[float, float] = (1.0, 2.0)
var_tuple: tuple[int, ...] = (1, 2, 3)

# Callable
handler: Callable[[str, int], bool] = lambda s, i: len(s) > i

# TypeVar and Generic
T = TypeVar("T")

def first(lst: list[T]) -> T:
    return lst[0]

class Stack(Generic[T]):
    def __init__(self) -> None:
        self._items: list[T] = []
    def push(self, item: T) -> None:
        self._items.append(item)
    def pop(self) -> T:
        return self._items.pop()

# Literal
def set_mode(mode: Literal["train", "test"]) -> None: ...

# TypedDict
class UserInfo(TypedDict):
    name: str
    age: int
    email: str

# Protocol (structural typing)
class Drawable(Protocol):
    def draw(self) -> None: ...

# Any — avoid if possible
data: Any = get_data()
```

## Async / Await

```python
import asyncio

async def fetch_data(url):
    await asyncio.sleep(1)  # simulate I/O
    return {"data": "value"}

async def main():
    # Sequential
    result1 = await fetch_data("url1")
    result2 = await fetch_data("url2")

    # Concurrent
    results = await asyncio.gather(
        fetch_data("url1"),
        fetch_data("url2"),
        fetch_data("url3"),
    )

    # With timeout
    try:
        result = await asyncio.wait_for(fetch_data("url"), timeout=5.0)
    except asyncio.TimeoutError:
        print("Timed out")

# Run event loop
asyncio.run(main())

# Async context manager
class AsyncDB:
    async def __aenter__(self):
        await self.connect()
        return self
    async def __aexit__(self, *exc):
        await self.close()

async def work():
    async with AsyncDB() as db:
        data = await db.query("SELECT *")

# Async iteration
async def stream_lines():
    async for line in async_file:
        process(line)

# asyncio.Queue
queue = asyncio.Queue()
await queue.put(item)
item = await queue.get()

# Semaphore for concurrency limit
sem = asyncio.Semaphore(10)
async def limited():
    async with sem:
        await fetch()
```

## File I/O

```python
# Text file
with open("file.txt", "r", encoding="utf-8") as f:
    content = f.read()          # entire file
    lines = f.readlines()       # list of lines
    for line in f:              # memory efficient
        process(line.strip())

with open("out.txt", "w", encoding="utf-8") as f:
    f.write("text\n")

# Append
with open("log.txt", "a") as f:
    f.write("new entry\n")

# Binary
with open("image.png", "rb") as f:
    data = f.read()

# JSON
import json
data = json.load(open("d.json"))         # read
json.dump(data, open("d.json", "w"),     # write
    indent=2, ensure_ascii=False)

# CSV
import csv
with open("data.csv", newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        print(row["column_name"])

# Pathlib (preferred over os.path)
from pathlib import Path
p = Path("/home/user/file.txt")
p.exists(), p.is_file(), p.is_dir()
p.parent, p.name, p.stem, p.suffix
p.read_text(encoding="utf-8")
p.write_text("content")
p.mkdir(parents=True, exist_ok=True)
p.glob("*.py")           # iterator of matches
list(p.rglob("*.py"))    # recursive glob

# tempfile
import tempfile
with tempfile.NamedTemporaryFile(suffix=".txt") as f:
    f.write(b"data")
```

## Common Stdlib

```python
import os
os.environ.get("PATH")
os.path.join("dir", "sub", "file.txt")
os.makedirs("dir/sub", exist_ok=True)
os.getcwd()
os.listdir(".")

import sys
sys.argv          # command-line args
sys.path          # module search path
sys.exit(1)       # exit with code
sys.stdin, sys.stdout, sys.stderr

import re
re.match(r"^foo", "foo bar")     # match at start
re.search(r"\d+", "abc 123")    # search anywhere
re.findall(r"\w+", "hello world")  # ["hello", "world"]
re.sub(r"\s+", " ", "a  b   c")    # "a b c"
re.split(r"[,\s]+", "a,b c,d")     # ["a", "b", "c", "d"]
email_re = re.compile(r"^[\w.]+@[\w.]+\.\w+$")
email_re.match("a@b.com")

import collections
cnt = collections.Counter("aaabbc")    # {'a': 3, 'b': 2, 'c': 1}
cnt.most_common(2)
dd = collections.defaultdict(list)
dq = collections.deque([1, 2, 3])
dq.appendleft(0); dq.popleft()

import datetime
dt = datetime.datetime.now()
d = datetime.date.today()
dt.strftime("%Y-%m-%d %H:%M:%S")
datetime.datetime.strptime("2024-01-15", "%Y-%m-%d")
from datetime import timedelta
future = dt + timedelta(days=7)

import itertools
itertools.chain([1,2], [3,4])     # 1,2,3,4
itertools.product("AB", repeat=2)  # AA,AB,BA,BB
itertools.combinations("ABC", 2)   # AB,AC,BC
itertools.groupby(sorted_items, key=...)
itertools.starmap(func, [(1,2), (3,4)])

import functools
functools.reduce(lambda a, b: a + b, [1, 2, 3, 4])  # 10
functools.partial(print, sep=" | ")

import json, csv, os, re, sys, math, random, hashlib
import subprocess, argparse, logging, unittest, asyncio
import contextlib, dataclasses, enum, pathlib, typing
```

## Virtualenvs & pip

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate    # Linux/Mac
.venv\Scripts\activate       # Windows

# pip commands
pip install requests
pip install -r requirements.txt
pip install --upgrade pip
pip freeze > requirements.txt
pip uninstall requests
pip show requests
pip list

# uv (faster alternative)
uv venv
uv pip install requests
uv pip compile requirements.in -o requirements.txt

# pyproject.toml (modern project setup)
# [project]
# name = "mypackage"
# version = "0.1.0"
# dependencies = ["requests>=2.28"]
# [project.scripts]
# mycli = "mypackage.cli:main"
```

```python
# venv in code
import venv
venv.create(".venv", with_pip=True)

# sys.path manipulation
import sys
sys.path.insert(0, "/custom/path")
```

## Gotchas

- **Mutable default args**: `def f(x=[])` → same list every call. Use `x=None; if x is None: x = []`
- **Float comparison**: `0.1 + 0.2 != 0.3`. Use `math.isclose()` or `decimal`.
- **Identity vs equality**: `is` checks identity (same object), `==` checks equality.
- **`None` is falsy** but not `False`. Use `is None` / `is not None`.
- **Late binding closures**: `f = [lambda: i for i in range(5)]` → all return 4. Use `lambda i=i: i`.
- **GIL**: Only one thread runs Python bytecode at a time. Use `multiprocessing` for CPU-bound parallelism.
- **`copy` vs `deepcopy`**: `list.copy()` is shallow. `copy.deepcopy()` for nested structures.
- **Integer division**: `5 // 2 == 2` (floor), `5 / 2 == 2.5` (float).
- **String interning**: `is` may work for short strings, but don't rely on it.
- **`__repr__` vs `__str__`**: `repr` for debugging, `str` for users.
- **`@dataclass` mutable defaults**: Use `field(default_factory=list)` not `= []`.
- **`except Exception`** catches `SystemExit` and `KeyboardInterrupt`? No — those inherit from `BaseException`. `Exception` does NOT catch them.
- **f-string nesting**: `f"{f'{x}'}"` works in 3.12+, use intermediate vars before that.
- **`list.clear()` vs `list = []`**: `.clear()` modifies in-place, `= []` creates new list. Relevant for mutable references.
- **Scope**: assignments inside a function create local vars. Use `global`/`nonlocal` to modify outer scope.
- **`is` vs `==` for singletons**: Always use `if x is None`, not `if x == None`.
- **Tuple "mutability"**: `t = ([1],)` — you CAN mutate `t[0].append(2)`, just can't reassign `t[0]`.
