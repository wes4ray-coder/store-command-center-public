# Go Quick Reference

> Offline reference guide for AI agents. Last updated: 2026-07-10.

## Contents
1. Types & Variables
2. Functions
3. Pointers & Methods
4. Interfaces
5. Goroutines & Channels
6. Error Handling
7. Structs
8. Packages & Modules
9. Testing
10. Common Patterns

## 1. Types & Variables

```go
// Basic types
var i int = 42
var f float64 = 3.14
var s string = "hello"
var b bool = true

// Short declaration (inside functions only)
x := 10
name := "Wes"
pi := 3.14159

// Zero values
var i int      // 0
var s string   // ""
var b bool     // false
var p *int     // nil

// Constants
const Pi = 3.14159
const (
    StatusOK = 200
    StatusNotFound = 404
)

// Arrays (fixed size)
var arr [5]int                 // [0 0 0 0 0]
arr[0] = 10
arr2 := [3]int{1, 2, 3}

// Slices (dynamic arrays)
nums := []int{1, 2, 3}
nums = append(nums, 4)
nums = append(nums, 5, 6, 7)
len(nums)                      // 7
cap(nums)                      // underlying capacity
nums[0]                        // 1
nums[1:3]                      // [2 3] — slice
nums[:2]                       // [1 2]
nums[2:]                       // [3 4 5 6 7]
copy(dst, src)                 // copy slice

// Maps
m := map[string]int{"a": 1, "b": 2}
m["c"] = 3
delete(m, "a")
v, ok := m["a"]               // v=0, ok=false (deleted)
len(m)

// Iterate map
for key, val := range m {
    fmt.Printf("%s = %d\n", key, val)
}

// Type conversion
i := int(3.14)                 // 3
s := string(65)               // "A"
f := float64(10)              // 10.0
```

## 2. Functions

```go
// Basic
func add(a int, b int) int {
    return a + b
}

// Short signature (same type params)
func add(a, b int) int { return a + b }

// Multiple return values
func divmod(a, b int) (int, int) {
    return a / b, a % b
}
q, r := divmod(17, 5)         // q=3, r=2

// Named returns
func split(sum int) (x, y int) {
    x = sum * 4 / 9
    y = sum - x
    return                      // naked return
}

// Variadic
func sum(nums ...int) int {
    total := 0
    for _, n := range nums {
        total += n
    }
    return total
}
sum(1, 2, 3)
nums := []int{1, 2, 3}
sum(nums...)                   // spread slice

// Closures
counter := func() func() int {
    count := 0
    return func() int {
        count++
        return count
    }
}
c := counter()
c()                            // 1
c()                            // 2

// Functions as values
fn := func(x int) int { return x * 2 }
result := fn(5)               // 10

// Defer (runs when function exits)
func readFile() {
    f := os.Open("file.txt")
    defer f.Close()            // runs at exit
    // ...
}
```

## 3. Pointers & Methods

```go
// Pointers
x := 42
p := &x                        // p is *int, points to x
fmt.Println(*p)                // 42
*p = 100                       // change x through pointer
fmt.Println(x)                 // 100

// new() returns pointer to zero value
p := new(int)                  // *int, value 0

// Methods (receiver functions)
type Rectangle struct {
    Width, Height float64
}

// Value receiver (works on copy)
func (r Rectangle) Area() float64 {
    return r.Width * r.Height
}

// Pointer receiver (can modify original)
func (r *Rectangle) Scale(factor float64) {
    r.Width *= factor
    r.Height *= factor
}

rect := Rectangle{Width: 10, Height: 5}
rect.Area()                    // 50
rect.Scale(2)
rect.Width                     // 20
```

## 4. Interfaces

```go
// Define interface
type Shape interface {
    Area() float64
    Perimeter() float64
}

// Implicit implementation (no "implements" keyword)
type Circle struct {
    Radius float64
}

func (c Circle) Area() float64 {
    return math.Pi * c.Radius * c.Radius
}

func (c Circle) Perimeter() float64 {
    return 2 * math.Pi * c.Radius
}

// Now Circle satisfies Shape automatically
var s Shape = Circle{Radius: 5}

// Type assertions
c, ok := s.(Circle)           // explicit type assertion
if ok {
    fmt.Println(c.Radius)
}

// Type switch
func describe(s Shape) {
    switch v := s.(type) {
    case Circle:
        fmt.Printf("Circle with radius %f\n", v.Radius)
    case Rectangle:
        fmt.Printf("Rectangle %f x %f\n", v.Width, v.Height)
    default:
        fmt.Printf("Unknown shape: %T\n", v)
    }
}

// Empty interface (any type)
func printAnything(v interface{}) {
    fmt.Printf("%v (%T)\n", v, v)
}

// Stringer interface (like toString)
type User struct{ Name string }
func (u User) String() string {
    return fmt.Sprintf("User(%s)", u.Name)
}
```

## 5. Goroutines & Channels

```go
// Goroutine (lightweight thread)
go func() {
    fmt.Println("running concurrently")
}()

// Channels (typed communication between goroutines)
ch := make(chan int)

// Send/receive
ch <- 42                       // send
v := <-ch                      // receive

// Buffered channel
ch := make(chan int, 10)        // buffer size 10
ch <- 1                        // doesn't block (buffer has space)

// Close channel
close(ch)

// Range over channel (until closed)
for v := range ch {
    fmt.Println(v)
}

// Select (multiplex channels)
select {
case msg := <-ch1:
    fmt.Println("ch1:", msg)
case msg := <-ch2:
    fmt.Println("ch2:", msg)
case ch3 <- 42:
    fmt.Println("sent to ch3")
default:
    fmt.Println("no activity")
}

// WaitGroups (synchronize goroutines)
var wg sync.WaitGroup
for i := 0; i < 5; i++ {
    wg.Add(1)
    go func(id int) {
        defer wg.Done()
        fmt.Println("worker", id)
    }(i)
}
wg.Wait()                     // wait for all to finish

// Context (cancellation/timeout)
ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
defer cancel()

select {
case <-ctx.Done():
    fmt.Println("timeout:", ctx.Err())
case result := <-work:
    fmt.Println("got:", result)
}
```

## 6. Error Handling

```go
// Error type
func divide(a, b float64) (float64, error) {
    if b == 0 {
        return 0, fmt.Errorf("division by zero")
    }
    return a / b, nil
}

result, err := divide(10, 0)
if err != nil {
    log.Fatal(err)
}

// Common pattern
if err != nil {
    return fmt.Errorf("failed to process: %w", err)  // %w wraps error
}

// Custom error type
type ValidationError struct {
    Field string
    Msg  string
}

func (e *ValidationError) Error() string {
    return fmt.Sprintf("%s: %s", e.Field, e.Msg)
}

// errors.Is and errors.As (Go 1.13+)
if errors.Is(err, os.ErrNotExist) { /* file not found */ }

var ve *ValidationError
if errors.As(err, &ve) {
    fmt.Println("field:", ve.Field)
}

// Panic/Recover (for truly exceptional cases)
func safeDivide(a, b int) (result int, err error) {
    defer func() {
        if r := recover(); r != nil {
            err = fmt.Errorf("recovered: %v", r)
        }
    }()
    if b == 0 {
        panic("division by zero")
    }
    return a / b, nil
}
```

## 7. Structs

```go
type User struct {
    ID       int
    Name     string
    Email    string
    Active   bool
    Created  time.Time
}

// Create
u := User{ID: 1, Name: "Wes", Active: true}
u2 := User{Name: "Amy"}

// Anonymous structs
point := struct {
    X, Y int
}{X: 10, Y: 20}

// Struct embedding (composition)
type Admin struct {
    User          // embedded — Admin has all User fields/methods
    Permissions []string
}

admin := Admin{
    User: User{ID: 1, Name: "admin"},
    Permissions: []string{"read", "write"},
}
admin.Name                     // "admin" (promoted from User)

// Tags (for JSON, etc.)
type Product struct {
    Name  string `json:"name"`
    Price float64 `json:"price"`
    Stock int    `json:"stock,omitempty"`
}

// JSON marshal/unmarshal
data, _ := json.Marshal(product)
var p Product
json.Unmarshal(data, &p)
```

## 8. Packages & Modules

```bash
# Initialize module
go mod init github.com/user/myproject

# go.mod file:
# module github.com/user/myproject
# go 1.21

# Add dependency
go get github.com/gin-gonic/gin

# Tidy (add missing, remove unused)
go mod tidy

# Vendor (copy deps locally)
go mod vendor
```

```go
// Package structure
// Project root: mymodule/
//   main.go (package main)
//   utils/
//     helper.go (package utils)
//   models/
//     user.go (package models)

// Import
import (
    "fmt"
    "strings"
    "github.com/user/mymodule/utils"
)

// Exported = Capital letter
func Exported() {}    // public
func internal() {}     // package-private
```

## 9. Testing

```go
// File: user_test.go (same package, _test.go suffix)
package main

import "testing"

func TestAdd(t *testing.T) {
    result := add(2, 3)
    if result != 5 {
        t.Errorf("add(2,3) = %d, want 5", result)
    }
}

// Table-driven tests
func TestDivide(t *testing.T) {
    tests := []struct {
        a, b     int
        want     int
        wantErr  bool
    }{
        {10, 2, 5, false},
        {10, 0, 0, true},
        {15, 3, 5, false},
    }
    for _, tt := range tests {
        got, err := divide(tt.a, tt.b)
        if (err != nil) != tt.wantErr {
            t.Errorf("divide(%d,%d) error = %v, wantErr %v", tt.a, tt.b, err, tt.wantErr)
        }
        if got != tt.want {
            t.Errorf("divide(%d,%d) = %d, want %d", tt.a, tt.b, got, tt.want)
        }
    }
}

// Benchmark
func BenchmarkAdd(b *testing.B) {
    for i := 0; i < b.N; i++ {
        add(2, 3)
    }
}
```

```bash
# Run tests
go test ./...                    # all tests
go test -run TestAdd             # specific test
go test -v ./...                 # verbose
go test -bench .                 # benchmarks
go test -cover                   # coverage
go test -coverprofile=cover.out ./...  # coverage profile

# Other
go vet ./...                     # static analysis
go fmt ./...                     # format code
go build                         # compile
go install                       # install to $GOPATH/bin
go run main.go                   # compile + run
```

## 10. Common Patterns

```go
// Worker pool
func worker(id int, jobs <-chan int, results chan<- int) {
    for j := range jobs {
        results <- j * j
    }
}

func main() {
    jobs := make(chan int, 100)
    results := make(chan int, 100)

    for w := 1; w <= 3; w++ {
        go worker(w, jobs, results)
    }
    for j := 1; j <= 5; j++ {
        jobs <- j
    }
    close(jobs)
    for r := 1; r <= 5; r++ {
        fmt.Println(<-results)
    }
}

// Fan-in (merge channels)
func merge(cs ...<-chan int) <-chan int {
    var wg sync.WaitGroup
    out := make(chan int)
    for _, c := range cs {
        wg.Add(1)
        go func(<-chan int) {
            defer wg.Done()
            for v := range c {
                out <- v
            }
        }(c)
    }
    go func() { wg.Wait(); close(out) }()
    return out
}

// Singleton
var instance *Database
var once sync.Once
func GetDB() *Database {
    once.Do(func() {
        instance = &Database{conn: connect()}
    })
    return instance
}

// Graceful shutdown
srv := &http.Server{Addr: ":8080"}
go func() {
    if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
        log.Fatal(err)
    }
}()
<-ctx.Done()                  // wait for shutdown signal
srv.Shutdown(context.Background())
```
