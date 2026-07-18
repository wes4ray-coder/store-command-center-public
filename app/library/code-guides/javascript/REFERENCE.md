# JavaScript Quick Reference

> Offline reference guide for AI agents. Last updated: 2026-07-10.

## Contents
1. [Variables: let, const, var](#1-variables-let-const-var)
2. [Arrow Functions](#2-arrow-functions)
3. [Template Literals](#3-template-literals)
4. [Destructuring](#4-destructuring)
5. [Spread & Rest Operators](#5-spread--rest-operators)
6. [Promises & async/await](#6-promises--asyncawait)
7. [Fetch API](#7-fetch-api)
8. [DOM Manipulation](#8-dom-manipulation)
9. [Array Methods](#9-array-methods)
10. [Object Methods](#10-object-methods)
11. [Modules (import/export)](#11-modules-importexport)
12. [Classes](#12-classes)
13. [Error Handling](#13-error-handling)
14. [Node.js Basics](#14-nodejs-basics)
15. [Common Patterns](#15-common-patterns)
16. [Gotchas](#16-gotchas)

---

## 1. Variables: let, const, var

```javascript
var x = 1;       // function-scoped, hoisted (undefined before assignment)
let y = 2;       // block-scoped, hoisted but TDZ (Temporal Dead Zone)
const z = 3;     // block-scoped, must be initialized, reassignment prevented

// const does NOT make objects immutable
const obj = { a: 1 };
obj.a = 2;       // OK — mutating the object is fine
obj = {};        // TypeError — reassignment fails
```

**Rule of thumb:** Use `const` by default, `let` when reassignment is needed, never `var`.

---

## 2. Arrow Functions

```javascript
// Implicit return (no braces)
const add = (a, b) => a + b;
const square = x => x * x;           // single param: no parens needed
const greet = () => "hello";

// Explicit return (braces required)
const complex = (a, b) => {
  const sum = a + b;
  return sum * 2;
};

// Arrow functions do NOT have their own `this`
const obj = {
  name: "Alice",
  greet: () => console.log(this.name),    // undefined — `this` is lexical
  greetRegular() { console.log(this.name); } // "Alice" — method shorthand
};
```

**Gotcha:** Arrow functions can't be used as constructors (`new` throws). They also have no `arguments` object.

---

## 3. Template Literals

```javascript
const name = "World";
const greeting = `Hello, ${name}!`;

// Multiline strings
const html = `
  <div>
    <p>${greeting}</p>
  </div>
`;

// Nested expressions
const items = [1, 2, 3];
const result = `Sum: ${items.reduce((a, b) => a + b, 0)}`;

// Tagged templates
function tag(strings, ...values) {
  return strings.raw[0]; // raw gives unescaped string
}
const tagged = tag`line1\nline2`;
```

---

## 4. Destructuring

```javascript
// Arrays
const [a, b, c] = [1, 2, 3];          // a=1, b=2, c=3
const [first, , third] = [1, 2, 3];   // skip elements
const [x, ...rest] = [1, 2, 3, 4];    // x=1, rest=[2,3,4]
const [a = 10, b = 20] = [undefined, 5]; // default values: a=10, b=5

// Objects
const { name, age } = { name: "Bob", age: 30 };
const { name: fullName } = { name: "Bob" };  // rename: fullName="Bob"
const { nested: { deep } } = { nested: { deep: 42 } }; // nested destructuring
const { count = 0 } = {};               // default: count=0

// Function parameters
function render({ title, body = "N/A" }) {
  console.log(title, body);
}
render({ title: "Hello" });  // body defaults to "N/A"

// Swapping variables
[a, b] = [b, a];
```

---

## 5. Spread & Rest Operators

```javascript
// Spread — expand iterables
const arr1 = [1, 2, 3];
const arr2 = [...arr1, 4, 5];      // [1,2,3,4,5]
const merged = [...arr1, ...arr2];  // concat without .concat()

const obj1 = { a: 1 };
const obj2 = { ...obj1, b: 2 };    // { a:1, b:2 } — shallow copy
const override = { ...obj1, a: 99 }; // later keys win

// Spread in function calls
Math.max(...arr1);                // equivalent to Math.max(1,2,3)

// Rest — collect remaining
function sum(...nums) { return nums.reduce((a, b) => a + b, 0); }
const [first, ...others] = [1, 2, 3, 4];

// Rest in destructuring
const { a, ...rest } = { a: 1, b: 2, c: 3 };
```

**Gotcha:** Spread creates a **shallow** copy. Nested objects/arrays are still references.

---

## 6. Promises & async/await

```javascript
// Promise creation
const promise = new Promise((resolve, reject) => {
  setTimeout(() => resolve("done"), 1000);
});

// .then / .catch / .finally
promise
  .then(result => console.log(result))
  .catch(err => console.error(err))
  .finally(() => console.log("cleanup"));

// async/await
async function fetchData() {
  try {
    const response = await fetch("/api/data");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    return data;
  } catch (err) {
    console.error("Fetch failed:", err);
    throw err; // re-throw if caller should handle
  }
}

// Parallel execution
const [users, posts] = await Promise.all([
  fetch("/api/users").then(r => r.json()),
  fetch("/api/posts").then(r => r.json())
]);

// Promise.allSettled — doesn't short-circuit on rejection
const results = await Promise.allSetSettled([p1, p2, p3]);
results.forEach(r => {
  if (r.status === "fulfilled") console.log(r.value);
  else console.error(r.reason);
});

// Promise.race — first to settle wins
const fastest = await Promise.race([p1, p2]);

// Sequential with reduce
const urls = ["/a", "/b", "/c"];
const results = await urls.reduce(async (acc, url) => {
  const prev = await acc;
  const data = await fetch(url).then(r => r.json());
  return [...prev, data];
}, Promise.resolve([]));
```

**Gotcha:** `await` inside a `.forEach` callback does NOT pause the outer function. Use `for...of` instead:

```javascript
// WRONG — forEach ignores await
urls.forEach(async url => await fetch(url));

// RIGHT
for (const url of urls) {
  await fetch(url);
}
```

---

## 7. Fetch API

```javascript
// GET
const res = await fetch("/api/users");
const data = await res.json();

// POST with JSON
const res = await fetch("/api/users", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ name: "Alice" }),
});

// POST with form data
const formData = new FormData();
formData.append("file", fileInput.files[0]);
const res = await fetch("/upload", { method: "POST", body: formData });

// Custom headers & credentials
const res = await fetch("/api/me", {
  credentials: "include",          // send cookies
  headers: { "Authorization": `Bearer ${token}` },
});

// Handling non-OK responses (fetch only rejects on network error)
const res = await fetch("/api/users");
if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
const data = await res.json();

// Abort with timeout
const controller = new AbortController();
const timeout = setTimeout(() => controller.abort(), 5000);
try {
  const res = await fetch("/api/slow", { signal: controller.signal });
} catch (err) {
  if (err.name === "AbortError") console.log("Timed out");
} finally {
  clearTimeout(timeout);
}

// Response helpers
res.text();   // string
res.json();   // parsed JSON
res.blob();   // Blob
res.headers.get("content-type");
res.status;   // 200
res.ok;       // true if 200-299
```

---

## 8. DOM Manipulation

```javascript
// Selecting elements
const el = document.querySelector("#app .content");
const all = document.querySelectorAll(".item");  // NodeList (not array)

// Creating elements
const div = document.createElement("div");
div.className = "card";
div.id = "card-1";
div.textContent = "Hello";         // safe from XSS
div.innerHTML = "<b>Bold</b>";     // NOT safe with user input
div.setAttribute("data-id", "42");

// Appending / removing
parent.appendChild(div);           // append
parent.append(div, "text", another); // append multiple
parent.removeChild(div);            // remove
div.remove();                       // self-remove (modern)

// Events
button.addEventListener("click", (e) => {
  e.preventDefault();
  e.stopPropagation();
  console.log(e.target, e.currentTarget);
});

// Event delegation
document.querySelector("#list").addEventListener("click", (e) => {
  const item = e.target.closest(".list-item");
  if (!item) return;
  console.log("Clicked:", item.dataset.id);
});

// Class manipulation
el.classList.add("active");
el.classList.remove("hidden");
el.classList.toggle("active");
el.classList.contains("active");

// Styles
el.style.color = "red";
el.style.backgroundColor = "blue";  // camelCase, not kebab-case
el.style.cssText = "color: red; padding: 10px;";

// Data attributes
el.dataset.userId;    // reads data-user-id
el.dataset.userId = "99";

// Iterating NodeList
document.querySelectorAll(".item").forEach(el => console.log(el));
// Convert to array if needed
const items = [...document.querySelectorAll(".item")];
// or
const items = Array.from(document.querySelectorAll(".item"));
```

---

## 9. Array Methods

```javascript
// map — transform each element
[1, 2, 3].map(x => x * 2);                    // [2, 4, 6]
[{ name: "A" }, { name: "B" }].map(o => o.name); // ["A", "B"]

// filter — keep matching elements
[1, 2, 3, 4].filter(x => x > 2);               // [3, 4]

// reduce — accumulate to single value
[1, 2, 3].reduce((acc, x) => acc + x, 0);      // 6
const grouped = people.reduce((acc, p) => {
  (acc[p.city] ||= []).push(p);
  return acc;
}, {});

// find / findIndex — first match
[1, 2, 3].find(x => x > 2);                    // 3
[1, 2, 3].findIndex(x => x > 2);               // 2

// some / every — test
[1, 2, 3].some(x => x > 2);                    // true
[1, 2, 3].every(x => x > 0);                   // true

// includes / indexOf
[1, 2, 3].includes(2);                         // true
[1, 2, 3].indexOf(2);                          // 1

// flat / flatMap
[1, [2, [3]]].flat();                          // [1, 2, [3]]  (depth=1)
[1, [2, [3]]].flat(2);                         // [1, 2, 3]
[[1, 2], [3, 4]].flatMap(([a, b]) => [a, b]);  // [1, 2, 3, 4]

// sort (mutates!)
[3, 1, 2].sort();                              // [1, 2, 3]
[3, 1, 2].sort((a, b) => b - a);              // [3, 2, 1] descending
[3, 1, 2].toSorted((a, b) => a - b);          // [1, 2, 3] non-mutating (ES2023)

// slice (non-mutating) vs splice (mutating)
[1, 2, 3, 4].slice(1, 3);                     // [2, 3] — copy
[1, 2, 3, 4].splice(1, 2);                    // [2, 3] removed, original mutated

// Array.from — create arrays from iterables
Array.from({ length: 5 }, (_, i) => i ** 2);   // [0, 1, 4, 9, 16]
Array.from("hello");                            // ["h", "e", "l", "l", "o"]

// at (negative indices)
[1, 2, 3].at(-1);                              // 3
```

---

## 10. Object Methods

```javascript
// Object.keys / values / entries
const obj = { a: 1, b: 2 };
Object.keys(obj);     // ["a", "b"]
Object.values(obj);   // [1, 2]
Object.entries(obj);  // [["a", 1], ["b", 2]]

// fromEntries — reverse of entries
Object.fromEntries([["a", 1], ["b", 2]]);  // { a: 1, b: 2 }

// assign — merge (mutates target)
const merged = Object.assign({}, defaults, overrides);

// freeze / seal
Object.freeze(obj);   // can't modify, add, or delete properties
Object.seal(obj);      // can modify existing, can't add/delete

// spread (shallow copy)
const copy = { ...obj };

// Optional chaining
const city = user?.address?.city;          // undefined if any link is nullish
const count = data?.items?.length ?? 0;    // nullish coalescing fallback

// Nullish coalescing — only null/undefined trigger fallback
const x = null ?? "default";    // "default"
const y = 0 ?? "default";      // 0 (NOT "default" — 0 is falsy but not nullish)
const z = "" ?? "default";     // ""
```

---

## 11. Modules (import/export)

```javascript
// Named exports (math.js)
export const add = (a, b) => a + b;
export function multiply(a, b) { return a * b; }
export const PI = 3.14159;

// Default export (one per module)
export default function greet(name) {
  return `Hello, ${name}`;
}

// Importing
import greet from "./greet.js";                    // default
import { add, multiply as mul } from "./math.js";  // named (with alias)
import greet, { add } from "./greet.js";           // both
import * as math from "./math.js";                 // namespace
console.log(math.add(1, 2));

// Dynamic import (returns a Promise)
const module = await import("./heavy-module.js");
module.doWork();

// Re-export
export { add } from "./math.js";
export * from "./utils.js";

// Node.js (CommonJS) — still widely used
const fs = require("fs");
module.exports = { add, multiply };
```

**Gotcha:** ES modules are statically analyzed; you can't import from a variable at runtime. Use dynamic `import()` for that.

---

## 12. Classes

```javascript
class Animal {
  constructor(name) {
    this.name = name;
    this._energy = 0;         // "private" by convention
  }

  // Public class field
  species = "unknown";

  // Private field (truly private)
  #secret = "hidden";

  // Getter / setter
  get energy() { return this._energy; }
  set energy(val) {
    if (val < 0) throw new Error("Negative energy");
    this._energy = val;
  }

  // Static method
  static create(name) {
    return new Animal(name);
  }

  // Instance method
  speak() { return `${this.name} makes a sound`; }

  // Private method
  #内部() { return this.#secret; }
}

class Dog extends Animal {
  constructor(name, breed) {
    super(name);              // must call before using `this`
    this.breed = breed;
  }

  speak() {
    return `${super.speak()} — Woof!`;
  }
}

const d = new Dog("Rex", "Lab");
console.log(d.speak());       // "Rex makes a sound — Woof!"
console.log(Dog.create("X")); // static inherited
```

---

## 13. Error Handling

```javascript
// try/catch/finally
try {
  JSON.parse(badJson);
} catch (err) {
  console.error(err.message);  // err is typed (no need for `catch (err: Error)`)
} finally {
  // always runs
}

// Throwing
throw new Error("Something went wrong");
throw new TypeError("Expected a number");
throw { code: "CUSTOM", message: "custom error" }; // works but not recommended

// Custom error classes
class ValidationError extends Error {
  constructor(message, field) {
    super(message);
    this.name = "ValidationError";
    this.field = field;
  }
}

// Async error handling
async function safe(fn) {
  try {
    return await fn();
  } catch (err) {
    if (err.code === "ENOENT") return null;
    throw err;  // re-throw unknown errors
  }
}
```

---

## 14. Node.js Basics

```javascript
// require (CommonJS)
const fs = require("fs");
const path = require("path");
const http = require("http");

// fs — synchronous
const data = fs.readFileSync("file.txt", "utf8");
const json = JSON.parse(fs.readFileSync("data.json", "utf8"));
fs.writeFileSync("output.txt", "content");

// fs — async (callback)
fs.readFile("file.txt", "utf8", (err, data) => {
  if (err) throw err;
  console.log(data);
});

// fs — promises (modern)
const fsp = require("fs").promises;
// or
const fsp = await import("fs/promises");
const data = await fsp.readFile("file.txt", "utf8");
await fsp.writeFile("output.txt", "content");
await fsp.mkdir("subdir", { recursive: true });
await fsp.rm("oldfile", { force: true });

// path
path.join("dir", "subdir", "file.txt");     // "dir/subdir/file.txt"
path.resolve("dir", "file.txt");              // absolute path
path.extname("file.txt");                    // ".txt"
path.basename("/a/b/file.txt");              // "file.txt"
path.dirname("/a/b/file.txt");               // "/a/b"
path.parse("/a/b/file.txt");                 // { root, dir, base, ext, name }

// __dirname and __filename (CommonJS)
console.log(__dirname);   // directory of current file
console.log(__filename);  // full path of current file

// ESM equivalents
import { fileURLToPath } from "url";
import { dirname } from "path";
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// process
process.argv;          // [node, script, ...args]
process.env.API_KEY;   // environment variables
process.cwd();         // current working directory
process.exit(1);       // exit with code
process.on("exit", code => console.log(`Exiting ${code}`));

// http server
const server = http.createServer((req, res) => {
  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ ok: true }));
});
server.listen(3000, () => console.log("Server on :3000"));

// EventEmitter
const { EventEmitter } = require("events");
const ee = new EventEmitter();
ee.on("data", payload => console.log(payload));
ee.once("start", () => console.log("started once"));
ee.emit("data", { key: "value" });
ee.emit("start");
```

---

## 15. Common Patterns

### Debounce & Throttle
```javascript
function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

function throttle(fn, ms) {
  let last = 0;
  return (...args) => {
    const now = Date.now();
    if (now - last >= ms) { last = now; fn(...args); }
  };
}
```

### Memoization
```javascript
function memoize(fn) {
  const cache = new Map();
  return (...args) => {
    const key = JSON.stringify(args);
    if (cache.has(key)) return cache.get(key);
    const result = fn(...args);
    cache.set(key, result);
    return result;
  };
}
```

### Singleton
```javascript
let instance;
class Database {
  constructor() {
    if (instance) return instance;
    instance = this;
    this.connected = false;
  }
}
```

### Factory Pattern
```javascript
function createUser(type) {
  const types = {
    admin: { role: "admin", permissions: ["all"] },
    guest: { role: "guest", permissions: ["read"] },
  };
  return { ...types[type], createdAt: Date.now() };
}
```

### Pub/Sub
```javascript
class EventBus {
  constructor() { this.events = new Map(); }
  on(event, cb) { (this.events.get(event) || this.events.set(event, []).get(event)).push(cb); }
  emit(event, data) { (this.events.get(event) || []).forEach(cb => cb(data)); }
  off(event, cb) { this.events.set(event, (this.events.get(event) || []).filter(c => c !== cb)); }
}
```

---

## 16. Gotchas

### `typeof` quirks
```javascript
typeof null;            // "object" ( longstanding bug )
typeof NaN;             // "number"
typeof undefined;       // "undefined"
typeof function(){};   // "function"
typeof [];              // "object" — use Array.isArray() instead
```

### Equality
```javascript
0 == false;    // true (loose equality coerces)
0 === false;   // true  wait no — THIS IS FALSE. 0 !== false
"" == 0;       // true
"" === 0;      // false
null == undefined;  // true
null === undefined; // false
NaN === NaN;        // false — use Number.isNaN(NaN) instead
```

### `this` binding
```javascript
const obj = {
  value: 42,
  getValue() { return this.value; },
};
const unbound = obj.getValue;
unbound();                    // undefined — `this` is lost
const bound = obj.getValue.bind(obj);
bound();                      // 42
```

### Floats
```javascript
0.1 + 0.2;                  // 0.30000000000000004
(0.1 + 0.2).toFixed(2);    // "0.30" (string!)
```

### Hoisting
```javascript
console.log(x);  // undefined (var is hoisted)
var x = 5;

console.log(y);  // ReferenceError (let is in TDZ)
let y = 5;
function hoisted() {}  // function declarations are fully hoisted
```

### Array sort sorts as strings by default
```javascript
[10, 1, 2].sort();     // [1, 10, 2] — lexicographic!
[10, 1, 2].sort((a,b) => a - b);  // [1, 2, 10] — numeric
```

### Async forEach
```javascript
// forEach does NOT await — use for...of or Promise.all
[1, 2, 3].forEach(async x => await fetch(`/api/${x}`));  // runs in parallel, not sequential
await Promise.all([1, 2, 3].map(x => fetch(`/api/${x}`))); // explicit parallel
for (const x of [1, 2, 3]) { await fetch(`/api/${x}`); }    // sequential
```
