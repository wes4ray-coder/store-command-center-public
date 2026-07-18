# Kotlin Quick Reference

> Offline reference guide for AI agents. Last updated: 2026-07-10.

## Contents
1. Variables & Types
2. Control Flow
3. Functions
4. Classes & Objects
5. Collections
6. Null Safety
7. Coroutines
8. Generics
9. Interop
10. Common Patterns

## 1. Variables & Types

```kotlin
// val = immutable (preferred), var = mutable
val name = "Wesley"            // type inferred
var age = 30                   // mutable
val pi: Double = 3.14159      // explicit type

// Basic types
val i: Int = 42
val l: Long = 9_000_000_000
val d: Double = 3.14
val f: Float = 3.14f
val b: Boolean = true
val c: Char = 'A'
val s: String = "hello"

// String templates
val greeting = "Hello, $name!"
val sum = "2 + 2 = ${2 + 2}"
val multi = """
    Multi-line
    string
""".trimIndent()

// Type conversion (explicit)
val intFromString = "42".toInt()
val doubleFromInt = 42.toDouble()
val stringFromInt = 42.toString()

// Pair & Triple
val point = Pair(10, 20)
val (x, y) = point             // destructuring
val triple = Triple(1, 2, 3)
val (a, b, c) = triple

// Unit (like void)
fun log(msg: String): Unit { println(msg) }
// Unit is the default return type, usually omitted
```

## 2. Control Flow

```kotlin
// if (expression, not statement)
val max = if (a > b) a else b
val result = if (score >= 90) "A" 
             else if (score >= 80) "B" 
             else "C"

// when (replacement for switch)
val desc = when (day) {
    "MON" -> "Monday"
    "TUE", "WED" -> "Midweek"
    in listOf("SAT", "SUN") -> "Weekend"
    else -> "Other"
}

// when with conditions
val status = when {
    age < 18 -> "minor"
    age >= 65 -> "senior"
    else -> "adult"
}

// when with type check
fun process(x: Any) {
    when (x) {
        is String -> println("String of length ${x.length}")
        is Int -> println("Integer: $x")
        is List<*>> -> println("List with ${x.size} items")
        else -> println("Unknown")
    }
}

// for loop
for (i in 0..5) { print(i) }       // 0 1 2 3 4 5 (inclusive)
for (i in 0 until 5) { print(i) } // 0 1 2 3 4 (exclusive)
for (i in 5 downTo 0) { print(i) } // 5 4 3 2 1 0
for (i in 0..10 step 2) { print(i) } // 0 2 4 6 8 10
for (item in list) { println(item) }
for ((index, value) in list.withIndex()) { println("$index: $value") }

// while
while (condition) { /* ... */ }
do { /* ... */ } while (condition)

// Ranges
val range = 1..100
range.contains(50)             // 50 in range → true
50 in 1..100                    // true
'z' in 'a'..'z'                // true
```

## 3. Functions

```kotlin
// Basic
fun add(a: Int, b: Int): Int {
    return a + b
}

// Single expression (shorthand)
fun add(a: Int, b: Int) = a + b

// Default arguments
fun greet(name: String = "World", greeting: String = "Hello"): String {
    return "$greeting, $name!"
}
greet()                        // "Hello, World!"
greet("Wes")                   // "Hello, Wes!"
greet(greeting = "Hi")         // "Hi, World!"

// Named arguments
greet(name = "Wes", greeting = "Hi")

// Vararg
fun sum(vararg nums: Int): Int {
    return nums.sum()
}
sum(1, 2, 3, 4)                // 10
val arr = intArrayOf(1, 2, 3)
sum(*arr)                     // spread

// Higher-order functions
fun operate(a: Int, b: Int, op: (Int, Int) -> Int): Int {
    return op(a, b)
}
operate(5, 3) { x, y -> x + y }  // 8
operate(5, 3) { x, y -> x * y }  // 15

// Function types
val add: (Int, Int) -> Int = { a, b -> a + b }
add(2, 3)                     // 5

// Lambda
val square = { x: Int -> x * x }
square(5)                      // 25

// it (single parameter lambda)
val double: (Int) -> Int = { it * 2 }
list.map { it * 2 }

// Inline function (performance)
inline fun <T> withLock(lock: Lock, body: () -> T): T {
    lock.lock()
    try { return body() } finally { lock.unlock() }
}

// Extension functions
fun String.isPalindrome(): Boolean {
    return this == reversed()
}
"racecar".isPalindrome()       // true

fun List<Int>.sumEven(): Int = filter { it % 2 == 0 }.sum()

// Infix
infix fun Int.times(str: String): String = str.repeat(this)
println(3 times "ha")          // "hahaha"

// Tail recursion
tailrec fun factorial(n: Int, acc: Int = 1): Int =
    if (n <= 1) acc else factorial(n - 1, acc * n)
```

## 4. Classes & Objects

```kotlin
// Basic class
class Person(val name: String, var age: Int) {
    fun greet() = "Hi, I'm $name"
}
val p = Person("Wes", 30)
p.name                         // "Wes" (property access, no getter)
p.age = 31                    // setter

// Data class (auto equals, hashCode, toString, copy, componentN)
data class User(val id: Int, val name: String, val email: String? = null)
val u = User(1, "Wes", "wes@example.com")
val u2 = u.copy(name = "Wesley")
val (id, name) = u             // destructuring

// Enum class
enum class Status {
    ACTIVE, INACTIVE, PENDING;
    
    fun isActive() = this == ACTIVE
}

// Sealed class (closed hierarchy — for when expression exhaustiveness)
sealed class Result {
    data class Success(val data: String) : Result()
    data class Error(val message: String) : Result()
    object Loading : Result()
}

fun handle(r: Result) = when (r) {
    is Result.Success -> println("Got: ${r.data}")
    is Result.Error -> println("Error: ${r.message}")
    Result.Loading -> println("Loading...")
}  // no else needed — compiler knows all cases

// Object (singleton)
object Database {
    fun connect() { /* ... */ }
    fun query(sql: String) { /* ... */ }
}
Database.connect()

// Companion object (static-like)
class Config {
    companion object {
        const val DEFAULT_PORT = 8080
        fun load(): Config = Config()
    }
}
Config.DEFAULT_PORT
Config.load()

// Interface
interface Drawable {
    fun draw()
    fun describe() = "Drawing something"  // default implementation
}

class Circle(val radius: Double) : Drawable {
    override fun draw() { println("Drawing circle") }
}

// Abstract class
abstract class Shape {
    abstract fun area(): Double
    open fun describe() = "Shape with area ${area()}"
}

class Square(val side: Double) : Shape() {
    override fun area() = side * side
}

// Object expression (anonymous)
val clickListener = object : ClickListener {
    override fun onClick() { println("Clicked!") }
}
```

## 5. Collections

```kotlin
// Immutable
val list = listOf(1, 2, 3)
val set = setOf("a", "b", "c")
val map = mapOf("a" to 1, "b" to 2)

// Mutable
val mList = mutableListOf(1, 2, 3)
val mSet = mutableSetOf(1, 2, 3)
val mMap = mutableMapOf("a" to 1)

// List operations
list.size
list[0]                        // first
list.first()                  // or NoSuchElementException
list.last()
list.isEmpty()
list.contains(2)              // 2 in list
list.indexOf(2)
list + 4                      // [1, 2, 3, 4]
list - 2                     // [1, 3]

// Functional
list.map { it * 2 }                   // [2, 4, 6]
list.filter { it > 1 }               // [2, 3]
list.filter { it > 1 }.map { it * 2 } // [4, 6]
list.reduce { acc, x -> acc + x }    // 6
list.sum()                            // 6
list.sorted()                         // [1, 2, 3]
list.sortedDescending()
list.sortedBy { it }
list.groupBy { it % 2 }               // {1=[1, 3], 0=[2]}
list.associateWith { it * it }        // {1=1, 2=4, 3=9}
list.associateBy { "key$it" }         // {"key1"=1, "key2"=2, ...}
list.partition { it > 1 }             // ([2, 3], [1])
list.chunked(2)                        // [[1, 2], [3]]
list.windowed(2)                        // [[1, 2], [2, 3]]
list.flatten()                         // flatten nested
list.flatten().distinct()            // unique
list.take(2)                           // [1, 2]
list.drop(1)                           // [2, 3]
list.takeWhile { it < 3 }             // [1, 2]
list.elementAtOrElse(5) { -1 }       // -1
list.firstOrNull { it > 2 }          // 3 or null
list.any { it > 2 }                   // true
list.all { it > 0 }                   // true
list.none { it < 0 }                  // true
list.count { it > 1 }                 // 2

// Map
map["a"]                       // 1
map.keys
map.values
map.filterKeys { it == "a" }
map.mapValues { _, v -> v * 2 }

// iterate
for (item in list) { println(item) }
for ((k, v) in map) { println("$k = $v") }
list.forEach { println(it) }
```

## 6. Null Safety

```kotlin
// Nullable types (explicit ? suffix)
var name: String = "Wes"      // non-null, can't assign null
var name2: String? = null      // nullable
name2 = "Amy"

// Safe call (returns null if receiver is null)
val len = name2?.length       // Int? (null if name2 is null)

// Safe call chain
val country = user?.address?.country   // null at any point

// Elvis operator (default for null)
val display = name2 ?: "unknown"
val length = name2?.length ?: 0

// Not-null assertion (!!) — CRASHES if null (avoid)
val force = name2!!

// Safe cast
val num: Int? = obj as? Int    // null if cast fails

// Let (execute block only if non-null)
name2?.let {
    println("Name is $it")
}

// Nullable collections
val list: List<String?> = listOf("a", null, "b")
list.filterNotNull()           // ["a", "b"]
list.map { it?.length ?: 0 }  // [1, 0, 1]
```

## 7. Coroutines

```kotlin
import kotlinx.coroutines.*

// Launch (fire and forget)
GlobalScope.launch {
    delay(1000)
    println("World!")
}
println("Hello,")
Thread.sleep(2000)             // wait for coroutine

// async/await (returns result)
suspend fun fetchData(): String {
    delay(1000)
    return "data"
}

val result = runBlocking {
    val deferred = async { fetchData() }
    println("waiting...")
    deferred.await()
}
println(result)                // "data"

// Structured concurrency
runBlocking {
    launch { doWork("task1") }
    launch { doWork("task2") }
    // both run concurrently, both complete before runBlocking returns
}

// Coroutine scope
class MyViewModel : ViewModel() {
    fun loadData() {
        viewModelScope.launch {
            try {
                val data = repository.fetch()
                _state.value = State.Success(data)
            } catch (e: Exception) {
                _state.value = State.Error(e.message)
            }
        }
    }
}

// withContext (switch dispatcher)
suspend fun saveData() {
    withContext(Dispatchers.IO) {
        // run on IO thread
        file.writeText("data")
    }
}

// Dispatchers
Dispatchers.Main               // UI thread (Android)
Dispatchers.IO                 // network/disk
Dispatchers.Default            // CPU-heavy
Dispatchers.Unconfined          // caller thread (advanced)

// Flow (reactive streams)
fun countdown(): Flow<Int> = flow {
    for (i in 5 downTo 1) {
        emit(i)
        delay(1000)
    }
}

lifecycleScope.launch {
    countdown().collect { num ->
        println(num)
    }
}

// Flow operators
flow.map { it * 2 }
    .filter { it > 4 }
    .collect { println(it) }
```

## 8. Generics

```kotlin
// Generic function
fun <T> first(list: List<T>): T = list[0]

// Generic class
class Box<T>(val item: T) {
    fun get(): T = item
}
val box = Box("hello")
box.get()                      // "hello"

// Generic constraints
fun <T : Comparable<T>> maxOf(a: T, b: T): T =
    if (a >= b) a else b

// Multiple constraints (where clause)
fun <T> copy(src: T, dest: T) where T : Readable, T : Writable {
    // ...
}

// Variance
// in (contravariant) — consumer
// out (covariant) — producer
interface Source<out T> { fun next(): T }
interface Sink<in T> { fun put(item: T) }

// Reified (inline functions only)
inline fun <reified T> typeOf() = T::class.simpleName
typeOf<String>()               // "String"

// Star projection
fun printAll(list: List<*>) { for (item in list) println(item) }
```

## 9. Kotlin/JVM Interop

```kotlin
// Kotlin → Java (seamless)
// Kotlin can call Java libraries directly
// Java: public class MyJava { public String getName() { ... } }
// Kotlin: val name = myJava.name  // property access syntax

// @JvmStatic for Java callers
object Utils {
    @JvmStatic
    fun double(x: Int): Int = x * 2
}
// Java: Utils.double(5)

// @JvmField for direct field access
class Config {
    @JvmField
    val PORT = 8080
}
// Java: config.PORT

// @JvmName for custom JVM name
@JvmName("fastFilter")
fun List<Int>.filterFast(): List<Int> = ...
```

## 10. Common Patterns

```kotlin
// Singleton (object declaration)
object AppSettings {
    var theme: String = "light"
    fun toggleTheme() { theme = if (theme == "light") "dark" else "light" }
}

// Factory
sealed class Animal {
    data class Dog(val name: String) : Animal()
    data class Cat(val name: String) : Animal()
    
    companion object {
        fun create(type: String, name: String): Animal = when (type) {
            "dog" -> Dog(name)
            "cat" -> Cat(name)
            else -> throw IllegalArgumentException("Unknown animal")
        }
    }
}

// Repository pattern
interface Repository<T> {
    suspend fun get(id: Int): T?
    suspend fun save(item: T): T
}

class UserRepository(private val db: Database) : Repository<User> {
    override suspend fun get(id: Int) = db.query<User>(id)
    override suspend fun save(item: User) = db.insert(item)
}

// Delegated properties
val lazyValue: String by lazy {
    println("computed")
    "result"
}

// Observable
import kotlin.properties.Delegates
var name by Delegates.observable("") { _, old, new ->
    println("$old → $new")
}
```
