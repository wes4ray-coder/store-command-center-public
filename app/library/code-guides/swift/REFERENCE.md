# Swift Quick Reference

> Offline reference guide for AI agents. Last updated: 2026-07-10.

## Contents
1. Variables & Constants
2. Data Types
3. Control Flow
4. Functions & Closures
5. Classes & Structs
6. Optionals
7. Protocols & Extensions
8. Generics
9. Error Handling
10. Concurrency
11. Collections
12. Strings
13. Common Patterns

## 1. Variables & Constants

```swift
var variable = 10          // mutable
let constant = "hello"     // immutable (preferred by default)

// Type annotation
var score: Double = 95.5
var name: String = "Wesley"
```

## 2. Data Types

```swift
// Numbers
let int: Int = 42
let double: Double = 3.14159
let float: Float = 3.14
let bool: Bool = true

// Tuples
let point = (x: 10, y: 20)
point.x  // 10
point.0  // 10

// Any (avoid when possible)
let anything: Any = "can be anything"
```

## 3. Control Flow

```swift
// If-else
if score >= 90 {
    print("A")
} else if score >= 80 {
    print("B")
} else {
    print("C")
}

// Switch (exhaustive, no implicit fallthrough)
switch day {
case .monday, .tuesday:
    print("Start of week")
case .friday:
    print("Almost weekend")
default:
    print("Midweek")
}

// For-in loops
for i in 0..<5 { print(i) }        // 0,1,2,3,4
for i in 0...5 { print(i) }        // 0,1,2,3,4,5
for item in array { print(item) }
for (index, value) in array.enumerated() { print("\(index): \(value)") }

// While
while condition { /* ... */ }
repeat { /* ... */ } while condition  // do-while equivalent
```

## 4. Functions & Closures

```swift
// Basic function
func greet(name: String) -> String {
    return "Hello, \(name)!"
}

// Argument labels
func greet(person name: String, from hometown: String) -> String {
    return "\(name) is from \(hometown)"
}
greet(person: "Wesley", from: "Texas")

// Default values
func configure(timeout: Int = 30) { /* ... */ }

// Variadic
func sum(_ numbers: Int...) -> Int {
    return numbers.reduce(0, +)
}
sum(1, 2, 3, 4)

// Inout (pass by reference)
func increment(_ value: inout Int) { value += 1 }
var count = 5
increment(&count)  // count is now 6

// Closures
let add = { (a: Int, b: Int) -> Int in a + b }
add(3, 4)

// Trailing closure syntax
[1, 2, 3].map { $0 * 2 }  // [2, 4, 6]

// Escaping closures (for async/callbacks)
func fetchData(completion: @escaping (Result<Data, Error>) -> Void) { /* ... */ }
```

## 5. Classes & Structs

```swift
// Struct (value type — preferred for data)
struct Point {
    var x: Double
    var y: Double
    
    // Computed property
    var magnitude: Double { sqrt(x*x + y*y) }
    
    // Method
    func distance(to other: Point) -> Double {
        sqrt(pow(other.x - x, 2) + pow(other.y - y, 2))
    }
}

// Class (reference type)
class Person {
    var name: String
    var age: Int
    
    init(name: String, age: Int) {
        self.name = name
        self.age = age
    }
    
    deinit { /* cleanup when deallocated */ }
}

// Inheritance
class Student: Person {
    var school: String
    init(name: String, age: Int, school: String) {
        self.school = school
        super.init(name: name, age: age)
    }
}

// Protocol conformance
struct Point: Equatable {
    var x: Double
    var y: Double
    static func == (lhs: Point, rhs: Point) -> Bool {
        lhs.x == rhs.x && lhs.y == rhs.y
    }
}
```

## 6. Optionals

```swift
// Optional (may contain value or nil)
var name: String? = nil
var age: Int? = 42

// Forced unwrapping (risky — crashes if nil)
let value = age!

// Optional binding (safe)
if let unwrapped = age {
    print("Age is \(unwrapped)")
}

// Guard let (early exit)
func process(age: Int?) {
    guard let age = age else { return }
    print("Processing age: \(age)")
}

// Nil coalescing
let displayAge = age ?? 0

// Optional chaining
let count = user?.profile?.friends?.count  // returns Int?

// Implicitly unwrapped optional (avoid, but seen in old code)
var forceName: String! = "Wes"
```

## 7. Protocols & Extensions

```swift
// Protocol definition
protocol Drawable {
    func draw()
    var area: Double { get }
}

// Protocol conformance
struct Circle: Drawable {
    var radius: Double
    var area: Double { .pi * radius * radius }
    func draw() { print("Drawing circle") }
}

// Protocol with default implementation via extension
extension Drawable {
    func describe() { print("Area: \(area)") }
}

// Extensions (add functionality to existing types)
extension Int {
    var squared: Int { self * self }
    func times(_ block: () -> Void) {
        for _ in 0..<self { block() }
    }
}
5.squared  // 25
3.times { print("Hi") }
```

## 8. Generics

```swift
// Generic function
func first<T>(_ items: [T]) -> T? {
    return items.first
}

// Generic type
struct Stack<Element> {
    private var items: [Element] = []
    mutating func push(_ item: Element) { items.append(item) }
    mutating func pop() -> Element? { return items.popLast() }
}

// Type constraints
func max<T: Comparable>(_ a: T, _ b: T) -> T {
    return a > b ? a : b
}

// Associated types in protocols
protocol Container {
    associatedtype Item
    var items: [Item] { get }
    mutating func append(_ item: Item)
}
```

## 9. Error Handling

```swift
// Define errors
enum DataError: Error {
    case notFound
    case invalidFormat(String)
    case timeout
}

// Throwing function
func loadData(from url: String) throws -> Data {
    guard !url.isEmpty else { throw DataError.notFound }
    // ...
    return Data()
}

// Do-catch
do {
    let data = try loadData(from: "https://example.com")
    print("Loaded \(data.count) bytes")
} catch DataError.notFound {
    print("Not found")
} catch DataError.invalidFormat(let detail) {
    print("Invalid: \(detail)")
} catch {
    print("Unexpected error: \(error)")
}

// try? (converts to optional, nil on error)
let data = try? loadData(from: url)

// try! (crashes on error — avoid in production)
let data2 = try! loadData(from: "https://known-good.com")
```

## 10. Concurrency

```swift
// async/await (Swift 5.5+)
func fetchUser() async throws -> User {
    let (data, _) = try await URLSession.shared.data(from: url)
    return try JSONDecoder().decode(User.self, from: data)
}

// Task groups
func fetchAll() async {
    await withTaskGroup(of: User.self) { group in
        for id in ids {
            group.addTask { await fetchUser(id: id) }
        }
        for await user in group {
            print(user)
        }
    }
}

// @MainActor (UI thread)
@MainActor
class ViewModel: ObservableObject {
    @Published var users: [User] = []
}

// Async sequences
for try await line in url.lines {
    print(line)
}

// Structured concurrency
async let a = fetchUser(id: 1)
async let b = fetchUser(id: 2)
let (user1, user2) = try await (a, b)
```

## 11. Collections

```swift
// Arrays
var fruits = ["apple", "banana", "cherry"]
fruits.append("date")
fruits.insert("apricot", at: 0)
fruits.remove(at: 2)
fruits.count
fruits.contains("apple")
fruits.sort()
fruits.map { $0.uppercased() }
fruits.filter { $0.hasPrefix("a") }
fruits.reduce(0) { $0 + $1.count }

// Dictionaries
var scores: [String: Int] = ["Wes": 95, "Amy": 87]
scores["Wes"] = 100
scores["Bob"] = 75
for (name, score) in scores { print("\(name): \(score)") }
scores.keys
scores.values

// Sets
var primes: Set<Int> = [2, 3, 5, 7]
primes.insert(11)
primes.contains(7)
primes.union([13, 17])
primes.intersection([2, 3, 5])
```

## 12. Strings

```swift
let name = "Wesley"
let greeting = "Hello, \(name)!"  // String interpolation
let multiline = """
Line 1
Line 2
"""

// Common operations
let upper = name.uppercased()
let lower = name.lowercased()
let count = name.count
let parts = "a,b,c".split(separator: ",")
let trimmed = "  hi  ".trimmingCharacters(in: .whitespaces)
let replaced = "hello world".replacingOccurrences(of: "world", with: "Swift")

// Check
"Hello".hasPrefix("He")
"file.txt".hasSuffix(".txt")
"contains".contains("tain")

// String indices (not integer-indexed)
let str = "Swift"
let firstChar = str[str.startIndex]
let lastChar = str[str.index(before: str.endIndex)]
let index = str.index(str.startIndex, offsetBy: 2)
```

## 13. Common Patterns

```swift
// Singleton
class AppManager {
    static let shared = AppManager()
    private init() {}
}

// Delegate pattern
protocol DownloadDelegate: AnyObject {
    func didDownload(data: Data)
}

// Observer (Combine)
class Store: ObservableObject {
    @Published var items: [Item] = []
}

// Factory
protocol Animal { func speak() }
class Dog: Animal { func speak() { print("Woof") } }
class Cat: Animal { func speak() { print("Meow") } }
func makeAnimal(_ type: String) -> Animal {
    switch type {
    case "dog": return Dog()
    case "cat": return Cat()
    default: fatalError("Unknown")
    }
}

// Result type
func process() -> Result<Int, Error> {
    // ...
    return .success(42)
    // or .failure(someError)
}
```
