# Rust Quick Reference

> Offline reference guide for AI agents. Last updated: 2026-07-10.

## Contents
1. Ownership
2. References & Borrowing
3. Lifetimes
4. Smart Pointers
5. Traits & Generics
6. Enums & Pattern Matching
7. Error Handling
8. Closures & Iterators
9. Modules
10. Cargo

## 1. Ownership

```rust
// Move semantics (default)
let s1 = String::from("hello");
let s2 = s1;                    // s1 moved to s2 — s1 no longer valid
// println!("{}", s1);         // ERROR: borrow of moved value

// Clone (explicit deep copy)
let s1 = String::from("hello");
let s2 = s1.clone();            // both valid

// Copy trait (integers, floats, bools, chars — stack-only types)
let x = 42;
let y = x;                      // x copied, both valid

// Functions take ownership
fn take(s: String) { println!("{}", s); }
let s = String::from("hello");
take(s);
// s no longer valid here — ownership moved into function

// Return ownership
fn make() -> String { String::from("hello") }
let s = make();                 // ownership returned to caller

// Pass by reference instead (borrow)
fn borrow(s: &String) { println!("{}", s); }
let s = String::from("hello");
borrow(&s);                     // s still valid

// Ownership rules:
// 1. Each value has one owner
// 2. When owner goes out of scope, value is dropped
// 3. At any time: EITHER one mutable ref OR any number of immutable refs
```

## 2. References & Borrowing

```rust
// Immutable reference
let s = String::from("hello");
let r1 = &s;
let r2 = &s;                    // multiple immutable refs OK
println!("{} {}", r1, r2);

// Mutable reference
let mut s = String::from("hello");
let r = &mut s;
r.push_str(" world");
// Can't have another ref (mutable or immutable) while mutable ref exists
// let r2 = &s;                // ERROR

// Mutable ref goes out of scope → can borrow again
{
    let r = &mut s;
    r.push_str("!");
}
let r2 = &s;                    // OK, previous mut ref is gone

// Dangling references prevented
// let r = &String::from("temp");  // ERROR: temp dropped immediately

// Slicing
let s = String::from("hello");
let slice: &str = &s[0..3];     // "hel"
let slice2 = &s[..];             // "hello"
let slice3 = &s[1..];           // "ello"

// Mutable slice
let mut arr = [1, 2, 3, 4, 5];
let slice = &mut arr[1..3];
slice[0] = 10;                  // arr is now [1, 10, 3, 4, 5]
```

## 3. Lifetimes

```rust
// Lifetimes ensure references don't outlive their data
// Usually inferred, sometimes need explicit annotation

fn longest<'a>(x: &'a str, y: &'a str) -> &'a str {
    if x.len() > y.len() { x } else { y }
}
// 'a means: return value lives as long as shortest input

// Struct with references needs lifetime
struct Excerpt<'a> {
    part: &'a str,
}
let novel = String::from("hello world");
let ex = Excerpt { part: &novel[0..5] };

// Static lifetime (lives for entire program)
let s: &'static str = "I exist forever";
```

## 4. Smart Pointers

```rust
// Box<T> — heap allocation (single owner)
let b = Box::new(5);
println!("{}", *b);             // dereference

// Rc<T> — reference counted (multiple owners, immutable)
use std::rc::Rc;
let a = Rc::new(String::from("hello"));
let b = Rc::clone(&a);         // increment ref count
let c = Rc::clone(&a);
Rc::strong_count(&a);           // 3

// RefCell<T> — interior mutability (runtime borrow check)
use std::cell::RefCell;
let data = RefCell::new(vec![1, 2, 3]);
data.borrow_mut().push(4);     // mutable borrow (runtime check)
data.borrow().len();           // immutable borrow

// Rc<RefCell<T>> — multiple owners with mutation
let shared = Rc::new(RefCell::new(Vec::new()));
let shared2 = Rc::clone(&shared);
shared.borrow_mut().push(1);
shared2.borrow_mut().push(2);

// Arc<T> — atomic reference counting (thread-safe Rc)
use std::sync::Arc;
let a = Arc::new(vec![1, 2, 3]);
let b = Arc::clone(&a);
```

## 5. Traits & Generics

```rust
// Define trait
trait Summary {
    fn summarize(&self) -> String;
    fn default_text(&self) -> String {
        String::from("(no summary)")     // default method
    }
}

// Implement trait
struct Article { title: String, content: String }

impl Summary for Article {
    fn summarize(&self) -> String {
        format!("{}: {}", self.title, &self.content[..50])
    }
}

// Trait bound
fn print_summary<T: Summary>(item: &T) {
    println!("{}", item.summarize());
}

// Multiple trait bounds
fn notify<T: Summary + Display>(item: &T) {
    println!("Breaking: {}", item.summarize());
}

// Trait objects (dynamic dispatch)
pub trait Draw { fn draw(&self); }
pub struct Screen { components: Vec<Box<dyn Draw>> }
// Box<dyn Draw> = heap-allocated trait object

// Generic struct
struct Pair<T> { x: T, y: T }
impl<T> Pair<T> {
    fn new(x: T, y: T) -> Self { Self { x, y } }
}

// Generic with trait bound
impl<T: PartialOrd + PartialEq> Pair<T> {
    fn larger(&self) -> &T {
        if self.x >= self.y { &self.x } else { &self.y }
    }
}

// Derive macros
#[derive(Debug, Clone, PartialEq, Eq, Hash, Default)]
struct Config {
    host: String,
    port: u16,
}
```

## 6. Enums & Pattern Matching

```rust
// Basic enum
enum Direction { North, South, East, West }

// Enum with data
enum Message {
    Quit,
    Move { x: i32, y: i32 },
    Write(String),
    ChangeColor(i32, i32, i32),
}

// Pattern matching
let msg = Message::Write(String::from("hello"));
match msg {
    Message::Quit => println!("Quit"),
    Message::Move { x, y } => println!("Move to ({}, {})", x, y),
    Message::Write(text) => println!("Write: {}", text),
    Message::ChangeColor(r, g, b) => println!("RGB({}, {}, {})", r, g, b),
}

// Option<T> (null replacement)
enum Option<T> { Some(T), None }
let x: Option<i32> = Some(5);
let y: Option<i32> = None;

match x {
    Some(val) => println!("{}", val),
    None => println!("nothing"),
}

// if let (single-arm match)
if let Some(val) = x {
    println!("got {}", val);
}

// while let
let mut v = vec![1, 2, 3];
while let Some(val) = v.pop() {
    println!("{}", val);
}

// Result<T, E> (error handling)
enum Result<T, E> { Ok(T), Err(E) }

// Match on Result
match result {
    Ok(val) => println!("success: {}", val),
    Err(e) => eprintln!("error: {}", e),
}
```

## 7. Error Handling

```rust
use std::fs::File;
use std::io::{self, Read};

// ? operator (propagate errors)
fn read_file(path: &str) -> io::Result<String> {
    let mut file = File::open(path)?;   // ? returns Err on failure
    let mut contents = String::new();
    file.read_to_string(&mut contents)?;
    Ok(contents)
}

// Custom error
use std::fmt;
use std::error::Error;

#[derive(Debug)]
struct AppError { message: String }

impl fmt::Display for AppError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "AppError: {}", self.message)
    }
}

impl Error for AppError {}

// anyhow (ecosystem library for easy errors)
// anyhow::Result<T> = Result<T, anyhow::Error>
use anyhow::{anyhow, Context, Result};

fn process() -> Result<()> {
    let content = std::fs::read_to_string("config.toml")
        .context("Failed to read config file")?;
    Ok(())
}

// Matching errors
match file_result {
    Ok(content) => println!("Content: {}", content),
    Err(ref e) if e.kind() == io::ErrorKind::NotFound => eprintln!("File not found"),
    Err(e) => eprintln!("Other error: {}", e),
}

// unwrap / expect (panics on error — use in prototyping only)
let content = std::fs::read_to_string("file.txt").unwrap();
let content = std::fs::read_to_string("file.txt").expect("file must exist");
```

## 8. Closures & Iterators

```rust
// Closures
let add = |a, i32| -> i32 { a + b };
let add2 = |a, b| a + b;         // type inferred
add(1, 2);                       // 3

// Capture environment
let x = 10;
let add_x = |y| x + y;           // captures x by reference
add_x(5);                        // 15

// move closure (takes ownership of captured variables)
let x = vec![1, 2, 3];
let print = move || println!("{:?}", x);  // x moved into closure

// Iterators
let nums = vec![1, 2, 3, 4, 5];

// Consumer (terminal)
nums.iter().sum::<i32>();              // 15
nums.iter().count();                   // 5
nums.iter().max();                     // Some(5)
nums.iter().min();                     // Some(1)
nums.iter().any(|&x| x > 3);           // true
nums.iter().all(|&x| x > 0);           // true
nums.iter().collect::<Vec<_>>();

// Adapter (chainable)
nums.iter().map(|&x| x * 2).collect::<Vec<_>>();
nums.iter().filter(|&&x| x % 2 == 0).collect::<Vec<_>>();
nums.iter().enumerate().map(|(i, &v)| format!("{}: {}", i, v));
nums.iter().take(3);
nums.iter().skip(2).take(3);
nums.iter().chain([6, 7].iter());
nums.iter().zip(['a', 'b', 'c'].iter());

// Fold/reduce
nums.iter().fold(0, |acc, &x| acc + x);  // 15

// Chaining
let result = nums.iter()
    .filter(|&&x| x % 2 == 0)
    .map(|&x| x * x)
    .sum::<i32>();  // 4 + 16 = 20

// Create iterator
(1..=10).collect::<Vec<_>>();
let chars = "hello".chars().collect::<Vec<_>>();
let lines = "a\nb\nc".lines().collect::<Vec<_>>();

// IntoIterator (for loop)
for x in &nums { println!("{}", x); }
for x in nums { println!("{}", x); }  // takes ownership
```

## 9. Modules

```rust
// File: src/main.rs
mod utils;                      // declare module (file: src/utils.rs)

use utils::helper;              // import specific item
use utils::*;                   // glob import (avoid in lib code)
use crate::utils;               // absolute path from crate root
use super::sibling;             // parent module

// Visibility
pub fn public_fn() {}           // accessible outside module
fn private_fn() {}              // module-private (default)
pub(crate) fn crate_fn() {}     // crate-visible

// Module inline
mod config {
    pub struct Settings { pub host: String, port: u16 }
    pub fn load() -> Settings { Settings { host: "localhost".into(), port: 8080 } }
}

// File structure maps to modules
// src/main.rs   → crate root
// src/utils.rs  → mod utils
// src/models/   → mod models (with mod.rs or models.rs)
// src/models/user.rs → mod models::user
```

## 10. Cargo

```toml
# Cargo.toml
[package]
name = "myproject"
version = "0.1.0"
edition = "2021"

[dependencies]
serde = { version = "1.0", features = ["derive"] }
tokio = { version = "1.0", features = ["full"] }
anyhow = "1.0"

[dev-dependencies]
pretty_assertions = "1.0"

[[bin]]
name = "myapp"
path = "src/main.rs"
```

```bash
# Commands
cargo new myproject             // create new project
cargo new --lib mylib           // create library
cargo build                     // compile (debug)
cargo build --release           // optimized build
cargo run                       // compile + run
cargo test                      // run tests
cargo test -- --nocapture       // show println in tests
cargo bench                     // run benchmarks
cargo check                     // fast type-check (no binary)
cargo clippy                    // linter
cargo fmt                       // format code
cargo fmt -- --check            // verify formatting
cargo doc --open                 // generate docs
cargo add serde                 // add dependency
cargo update                    // update deps (in Cargo.lock)
cargo tree                      // dependency tree
cargo publish                   // publish to crates.io
cargo install ripgrep            // install binary globally
```
