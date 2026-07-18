# TypeScript Quick Reference

> Offline reference guide for AI agents. Last updated: 2026-07-10.

## Contents
1. [Basic Types](#1-basic-types)
2. [Interfaces](#2-interfaces)
3. [Type Aliases](#3-type-aliases)
4. [Union & Intersection Types](#4-union--intersection-types)
5. [Generics](#5-generics)
6. [Utility Types](#6-utility-types)
7. [Type Narrowing & Guards](#7-type-narrowing--guards)
8. [Enums](#8-enums)
9. [Tuples](#9-tuples)
10. [Modules & Declaration Files](#10-modules--declaration-files)
11. [Classes in TypeScript](#11-classes-in-typescript)
12. [Decorators](#12-decorators)
13. [tsconfig.json Basics](#13-tsconfigjson-basics)
14. [Common Patterns](#14-common-patterns)
15. [Gotchas](#15-gotchas)

---

## 1. Basic Types

```typescript
// Primitives
let str: string = "hello";
let num: number = 42;
let bool: boolean = true;
let big: bigint = 9007199254740991n;
let sym: symbol = Symbol("id");

// Arrays
let nums: number[] = [1, 2, 3];
let strs: Array<string> = ["a", "b"];
let matrix: number[][] = [[1, 2], [3, 4]];

// any / unknown / never / void
let anything: any = "whatever";        // opts out of type checking
let unsure: unknown = "maybe";         // safe any — must narrow before use
function log(): void { console.log("x"); } // no return value
function fail(msg: string): never { throw new Error(msg); } // never returns
function infiniteLoop(): never { while(true) {} }

// null / undefined
let nullable: string | null = null;
let undef: number | undefined = undefined;

// Literal types
let dir: "left" | "right" | "up" | "down" = "left";
let count: 0 | 1 | 2 = 1;
```

**`any` vs `unknown`:** `any` disables checking; `unknown` requires narrowing before use. Always prefer `unknown`.

---

## 2. Interfaces

```typescript
// Basic interface
interface User {
  id: number;
  name: string;
  email?: string;              // optional property
  readonly createdAt: Date;    // can't be reassigned
}

// Function types
interface Greet {
  (name: string, greeting?: string): string;
}
const greet: Greet = (name, greeting = "Hello") => `${greeting}, ${name}`;

// Index signatures
interface StringMap {
  [key: string]: string;
}
const colors: StringMap = { red: "#f00", green: "#0f0" };

// Extending interfaces
interface Animal { name: string; }
interface Dog extends Animal { breed: string; }

// Multiple inheritance
interface CanFly { fly(): void; }
interface CanSwim { swim(): void; }
interface Duck extends CanFly, CanSwim { quack(): void; }

// Hybrid types
interface Counter {
  (): void;           // callable
  count: number;      // has properties
  reset(): void;
}

// Declaration merging (interfaces with same name merge)
interface Window { myCustomProp: string; }
interface Window { anotherProp: number; }
// Window now has both myCustomProp and anotherProp
```

**Gotcha:** Interfaces are for object shapes only. For unions, primitives, or conditional types, use type aliases.

---

## 3. Type Aliases

```typescript
// Basic
type ID = number | string;
type Point = { x: number; y: number };
type Callback = (data: string) => void;

// Union types
type Status = "pending" | "active" | "complete";
type Result<T> = { success: true; data: T } | { success: false; error: string };

// Intersection
type WithTimestamp = { createdAt: Date };
type WithAuthor = { author: string };
type Post = { title: string } & WithTimestamp & WithAuthor;

// Mapped types
type Readonly<T> = { readonly [P in keyof T]: T[P] };
type Optional<T> = { [P in keyof T]?: T[P] };

// Conditional types
type IsString<T> = T extends string ? true : false;
type A = IsString<string>;  // true
type B = IsString<number>;  // false

// Template literal types
type Direction = "north" | "south" | "east" | "west";
type Compass = `go-${Direction}`;  // "go-north" | "go-south" | ...
type PropPath<T> = T extends object ? keyof T : never;
```

### Interface vs Type Alias
```typescript
// Interfaces: extensible, mergeable, better error messages
// Type aliases: more flexible (unions, intersections, conditional, mapped)
// Rule: use interface for object shapes, type for everything else
```

---

## 4. Union & Intersection Types

```typescript
// Union — "OR"
type ID = number | string;
function formatId(id: ID): string {
  // must narrow before using methods specific to a type
  if (typeof id === "string") return id.toUpperCase();
  return id.toFixed(0);
}

// Discriminated unions
type Shape =
  | { kind: "circle"; radius: number }
  | { kind: "square"; size: number }
  | { kind: "rect"; width: number; height: number };

function area(s: Shape): number {
  switch (s.kind) {
    case "circle": return Math.PI * s.radius ** 2;
    case "square": return s.size ** 2;
    case "rect":   return s.width * s.height;
  }
}

// Intersection — "AND"
type HasId = { id: number };
type HasName = { name: string };
type Entity = HasId & HasName;
// Entity must have both id and name

// Literal nar