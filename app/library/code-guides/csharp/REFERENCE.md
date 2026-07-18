# C# Quick Reference

> Offline reference guide for AI agents. Last updated: 2026-07-10.

## Contents
1. Types
2. Classes & Structs
3. Records
4. Interfaces & Generics
5. LINQ
6. Collections
7. Async/Await
8. Exception Handling
9. File I/O
10. .NET CLI

## 1. Types

```csharp
// Value types (stored on stack)
int x = 42;
long big = 9_000_000_000L;
double d = 3.14;
float f = 3.14f;
decimal money = 19.99m;
bool flag = true;
char c = 'A';
byte b = 255;

// Reference types (stored on heap)
string name = "Wesley";
object obj = new object();
int[] arr = { 1, 2, 3 };

// Nullable
int? maybe = null;
maybe = 42;
if (maybe.HasValue) Console.WriteLine(maybe.Value);
int safe = maybe ?? 0;          // null coalescing
int force = maybe!.Value;        // null-forgiving (tells compiler it's not null)

// var (type inference)
var list = new List<int>();
var dict = new Dictionary<string, int>();
var text = "hello";

// Tuples
(int x, int y) point = (10, 20);
Console.WriteLine(point.x);
var (a, b) = (1, 2);             // deconstruction
```

## 2. Classes & Structs

```csharp
// Class (reference type)
public class Person {
    public string Name { get; set; }
    public int Age { get; private set; }
    
    public Person() { }  // default constructor
    public Person(string name, int age) {
        Name = name;
        Age = age;
    }
    
    public virtual void Introduce() {
        Console.WriteLine($"Hi, I'm {Name}, {Age} years old.");
    }
}

// Struct (value type — for small, immutable data)
public struct Point {
    public double X { get; }
    public double Y { get; }
    
    public Point(double x, double y) { X = x; Y = y; }
    
    public double Magnitude => Math.Sqrt(X * X + Y * Y);
}

// Inheritance
public class Student : Person {
    public string School { get; set; }
    
    public Student(string name, int age, string school) 
        : base(name, age) {
        School = school;
    }
    
    public override void Introduce() {
        base.Introduce();
        Console.WriteLine($"I go to {School}.");
    }
}

// Static class
public static class MathHelper {
    public static double Square(double x) => x * x;
    public static double Distance(Point a, Point b) =>
        Math.Sqrt(Math.Pow(a.X - b.X, 2) + Math.Pow(a.Y - b.Y, 2));
}

// Pattern matching (C# 8+)
string result = age switch {
    < 18 => "minor",
    >= 18 and < 65 => "adult",
    >= 65 => "senior",
    _ => "unknown"
};
```

## 3. Records (C# 9+)

```csharp
// Record (immutable reference type with value-based equality)
public record User(string Name, int Age);
var u1 = new User("Wes", 30);
var u2 = new User("Wes", 30);
Console.WriteLine(u1 == u2);   // True (value equality)

// With expression (create modified copy)
var older = u1 with { Age = 31 };

// Record with additional members
public record Product {
    public string Name { get; init; }
    public decimal Price { get; init; }
    public string Category { get; init; } = "general";
    
    public Product(string name, decimal price, string category = "general") {
        Name = name;
        Price = price;
        Category = category;
    }
}

// init-only properties (settable only at construction)
public class Config {
    public string Host { get; init; } = "localhost";
    public int Port { get; init; } = 8080;
}
var cfg = new Config { Host = "example.com", Port = 443 };
// cfg.Host = "other";  // ERROR: init-only after construction
```

## 4. Interfaces & Generics

```csharp
// Interface
public interface IRepository<T> {
    Task<T> GetByIdAsync(int id);
    Task<IEnumerable<T>> GetAllAsync();
    Task AddAsync(T item);
    Task DeleteAsync(int id);
}

// Implement
public class UserRepository : IRepository<User> {
    public Task<User> GetByIdAsync(int id) { /* ... */ }
    public Task<IEnumerable<User>> GetAllAsync() { /* ... */ }
    public Task AddAsync(User item) { /* ... */ }
    public Task DeleteAsync(int id) { /* ... */ }
}

// Generic methods
public T First<T>(List<T> list) => list.FirstOrDefault();

// Generic constraints
public void Process<T>(T item) where T : class { }           // reference type
public void Process<T>(T item) where T : struct { }          // value type
public void Process<T>(T item) where T : new() { }           // has parameterless constructor
public void Process<T>(T item) where T : IComparable<T> { }  // implements interface

// Generic class
public class Cache<TKey, TValue> where TKey : notnull {
    private Dictionary<TKey, TValue> _store = new();
    public TValue Get(TKey key) => _store[key];
    public void Set(TKey key, TValue value) => _store[key] = value;
}
```

## 5. LINQ

```csharp
using System.Linq;

// Method syntax
var adults = users.Where(u => u.Age >= 18);
var names = users.Select(u => u.Name);
var sorted = users.OrderBy(u => u.Name).ThenByDescending(u => u.Age);
var first = users.FirstOrDefault(u => u.Name == "Wes");
var any = users.Any(u => u.Age < 18);
var count = users.Count(u => u.Active);
var sum = orders.Sum(o => o.Amount);
var avg = orders.Average(o => o.Amount);

// Grouping
var grouped = users.GroupBy(u => u.Country);
foreach (var group in grouped) {
    Console.WriteLine($"{group.Key}: {group.Count()} users");
}

// Joining
var joined = users.Join(orders,
    u => u.Id,
    o => o.UserId,
    (u, o) => new { u.Name, o.Amount });

// SelectMany (flatten)
var allTags = articles.SelectMany(a => a.Tags).Distinct();

// Query syntax (alternative)
var result = from u in users
             where u.Age >= 18
             orderby u.Name
             select new { u.Name, u.Age };

// Aggregate
var csv = users.Select(u => u.Name).Aggregate((a, b) => $"{a},{b}");

// Chunk (C# 10+)
var pages = users.Chunk(20);  // batches of 20

// ToDictionary
var dict = users.ToDictionary(u => u.Id, u => u.Name);
```

## 6. Collections

```csharp
using System.Collections.Generic;

// List
var list = new List<int> { 1, 2, 3 };
list.Add(4);
list.AddRange(new[] { 5, 6 });
list.Insert(0, 0);
list.Remove(3);
list.RemoveAt(0);
list.Count;
list.Contains(2);
list.IndexOf(4);
list.Sort();
list.Reverse();
list.Clear();

// Dictionary
var dict = new Dictionary<string, int>();
dict["age"] = 30;
dict.TryAdd("name", 1);
dict.ContainsKey("age");
dict.TryGetValue("age", out int age);
foreach (var (key, value) in dict) { }

// HashSet
var set = new HashSet<int> { 1, 2, 3 };
set.Add(2);          // no duplicate
set.Contains(2);
set.UnionWith(new[] { 4, 5 });
set.IntersectWith(new[] { 2, 3 });

// Queue / Stack
var queue = new Queue<string>();
queue.Enqueue("first");
queue.Dequeue();
queue.Peek();

var stack = new Stack<int>();
stack.Push(1);
stack.Pop();
stack.Peek();
```

## 7. Async/Await

```csharp
// Basic async method
public async Task<string> FetchDataAsync(string url) {
    using var client = new HttpClient();
    var response = await client.GetStringAsync(url);
    return response;
}

// Task<T>
public async Task<List<User>> GetUsersAsync() {
    await Task.Delay(500);  // simulate latency
    return new List<User> { new("Wes", 30) };
}

// Fire and forget (use carefully)
_ = Task.Run(() => DoBackgroundWork());

// Parallel
await Task.WhenAll(tasks);
await Task.WhenAny(tasks);

// CancellationToken
public async Task ProcessAsync(CancellationToken token) {
    foreach (var item in items) {
        token.ThrowIfCancellationRequested();
        await ProcessItemAsync(item, token);
    }
}

// ValueTask (avoid allocation for cached/synchronous results)
public ValueTask<int> GetCountAsync() {
    return _cache.HasValue 
        ? new ValueTask<int>(_cache.Value) 
        : new ValueTask<int>(FetchCountAsync());
}

// ConfigureAwait (library code should use ConfigureAwait(false))
await Task.Delay(100).ConfigureAwait(false);

// Parallel.ForEach
Parallel.ForEach(items, item => { Process(item); });
Parallel.ForEachAsync(items, async (item, ct) => { await ProcessAsync(item, ct); });
```

## 8. Exception Handling

```csharp
try {
    var result = 10 / divisor;
} catch (DivideByZeroException ex) {
    Console.WriteLine($"Division error: {ex.Message}");
} catch (InvalidOperationException ex) {
    Console.WriteLine($"Invalid op: {ex.Message}");
} catch (Exception ex) {
    Console.WriteLine($"Unexpected: {ex}");
    throw;   // re-throw preserving stack trace
} finally {
    // always runs
}

// Custom exceptions
public class ValidationException : Exception {
    public string Field { get; }
    public ValidationException(string field, string message) 
        : base(message) {
        Field = field;
    }
}

// Throw expressions
string label = count switch {
    0 => throw new InvalidOperationException("Empty"),
    _ => $"Count: {count}"
};

// Try-catch pattern for parsing
if (int.TryParse(input, out int number)) {
    Console.WriteLine($"Parsed: {number}");
} else {
    Console.WriteLine("Invalid number");
}
```

## 9. File I/O

```csharp
using System.IO;

// Read all text
string content = File.ReadAllText("file.txt");
string[] lines = File.ReadAllLines("file.txt");

// Write
File.WriteAllText("output.txt", content);
File.WriteAllLines("lines.txt", new[] { "line1", "lines2" });

// Append
File.AppendAllText("log.txt", $"[{DateTime.Now}] message\n");

// Async
string text = await File.ReadAllTextAsync("file.txt");
await File.WriteAllTextAsync("output.txt", text);

// Streams
using var stream = File.OpenRead("data.bin");
using var reader = new StreamReader(stream);
string? line;
while ((line = reader.ReadLine()) != null) {
    Console.WriteLine(line);
}

// File info
var info = new FileInfo("file.txt");
Console.WriteLine($"{info.Length} bytes, modified {info.LastWriteTime}");

// Directory
Directory.CreateDirectory("/path/to/dir");
var files = Directory.GetFiles("/dir", "*.py", SearchOption.AllDirectories);
var exists = Directory.Exists("/dir");

// Path operations
string dir = Path.GetDirectoryName("/a/b/c.txt");   // /a/b
string file = Path.GetFileName("/a/b/c.txt");         // c.txt
string ext = Path.GetExtension("file.txt");           // .txt
string combined = Path.Combine("/base", "sub", "file.txt");  // /base/sub/file.txt
string temp = Path.GetTempFileName();
```

## (not fully expanded)

## 10. .NET CLI

```bash
# Create project
dotnet new console -n MyApp          # console app
dotnet new web -n MyApi              # web app
dotnet new classlib -n MyLib         # class library

# Build & run
dotnet build                          # build all projects
dotnet run                             # build + run
dotnet run --project src/MyApp        # specific project

# Dependencies
dotnet add package Newtonsoft.Json   # add NuGet package
dotnet add package Bogus --version 35.0.0
dotnet remove package Newtonsoft.Json
dotnet restore                        # restore packages

# Testing
dotnet test
dotnet test --filter "FullyQualifiedName~UserServiceTests"

# Publish
dotnet publish -c Release -o /publish  # publish for deployment
dotnet publish -c Release -r linux-x64 --self-contained

# EF Core
dotnet ef migrations add InitialCreate
dotnet ef database update
dotnet ef migrations remove

# Watch (hot reload)
dotnet watch run

# Solution
dotnet new sln -n MySolution
dotnet sln add src/MyApp src/MyLib
dotnet sln list
dotnet sln remove src/MyApp
```
