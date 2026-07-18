# Java Quick Reference

> Offline reference guide for AI agents. Last updated: 2026-07-10.

## Contents
1. Types & Variables
2. Classes & Objects
3. Interfaces & Abstract Classes
4. Enums
5. Generics
6. Lambda & Streams
7. Collections
8. Exceptions
9. I/O
10. Maven & Gradle

## 1. Types & Variables

```java
// Primitive types
int x = 42;
long big = 9_000_000_000L;
double d = 3.14;
float f = 3.14f;
boolean flag = true;
char c = 'A';
byte b = 127;
short s = 32767;

// Wrapper classes (for collections, null checks)
Integer boxed = 42;          // can be null
Double dBoxed = 3.14;
Boolean boolBoxed = true;

// var (Java 10+, local type inference)
var list = new ArrayList<String>();
var map = new HashMap<String, Integer>();
var name = "Wesley";

// Strings
String name = "Wesley";
String multi = """
    Multi-line
    text block
    """;
int len = name.length();
String upper = name.toUpperCase();
boolean eq = name.equals("Wesley");    // use equals, NOT ==
String[] parts = "a,b,c".split(",");
String joined = String.join(", ", "a", "b", "c");
String formatted = String.format("Name: %s, Age: %d", name, 30);
String sub = "hello world".substring(0, 5);

// Arrays
int[] arr = {1, 2, 3, 4, 5};
int[] arr2 = new int[10];
arr.length;
int first = arr[0];
Arrays.sort(arr);
int[] copy = Arrays.copyOf(arr, arr.length);
List<Integer> list = Arrays.asList(1, 2, 3);  // fixed size
List<Integer> mutable = new ArrayList<>(Arrays.asList(1, 2, 3));
```

## 2. Classes & Objects

```java
public class Person {
    // Fields
    private String name;
    private int age;

    // Constructor
    public Person(String name, int age) {
        this.name = name;
        this.age = age;
    }

    // Getters/Setters
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public int getAge() { return age; }

    // Methods
    public void introduce() {
        System.out.println("Hi, I'm " + name + ", " + age + " years old.");
    }

    // Static method
    public static Person create(String name, int age) {
        return new Person(name, age);
    }

    // equals/hashCode
    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof Person p)) return false;
        return age == p.age && name.equals(p.name);
    }

    @Override
    public int hashCode() {
        return Objects.hash(name, age);
    }

    @Override
    public String toString() {
        return "Person{name='" + name + "', age=" + age + "}";
    }
}

// Inheritance
public class Student extends Person {
    private String school;

    public Student(String name, int age, String school) {
        super(name, age);
        this.school = school;
    }

    @Override
    public void introduce() {
        super.introduce();
        System.out.println("I go to " + school);
    }
}

// Record (Java 16+ — immutable, auto equals/hashCode/toString)
public record User(String name, int age) {}
User u = new User("Wes", 30);
u.name();   // accessor
```

## 3. Interfaces & Abstract Classes

```java
// Interface
public interface Comparable<T> {
    int compareTo(T other);
}

public interface Drawable {
    void draw();
    default void describe() {           // default method (Java 8+)
        System.out.println("Drawing something");
    }
}

// Implement
public class Circle implements Drawable {
    @Override
    public void draw() {
        System.out.println("Drawing circle");
    }
}

// Abstract class (cannot be instantiated directly)
public abstract class Shape {
    protected String name;

    public Shape(String name) {
        this.name = name;
    }

    public abstract double area();     // must be implemented by subclass

    public void describe() {
        System.out.println(name + " with area " + area());
    }
}

public class Square extends Shape {
    private double side;

    public Square(double side) {
        super("Square");
        this.side = side;
    }

    @Override
    public double area() {
        return side * side;
    }
}
```

## 4. Enums

```java
public enum Day {
    MONDAY, TUESDAY, WEDNESDAY, THURSDAY,
    FRIDAY, SATURDAY, SUNDAY
}

// Enum with constructor and methods
public enum Status {
    ACTIVE("Active", 1),
    INACTIVE("Inactive", 0),
    PENDING("Pending", 2);

    private final String label;
    private final int code;

    Status(String label, int code) {
        this.label = label;
        this.code = code;
    }

    public String getLabel() { return label; }
    public int getCode() { return code; }
}

// Usage
Status s = Status.ACTIVE;
System.out.println(s.getLabel());
Status[] all = Status.values();
Status fromStr = Status.valueOf("ACTIVE");
switch (s) {
    case ACTIVE -> System.out.println("Active");
    case INACTIVE -> System.out.println("Inactive");
    default -> System.out.println("Other");
}
```

## 5. Generics

```java
// Generic class
public class Box<T> {
    private T item;
    public void set(T item) { this.item = item; }
    public T get() { return item; }
}

// Generic method
public static <T> T firstOrNull(List<T> list) {
    return list.isEmpty() ? null : list.get(0);
}

// Bounded type parameter
public static <T extends Comparable<T>> T max(List<T> list) {
    T result = list.get(0);
    for (T item : list) {
        if (item.compareTo(result) > 0) result = item;
    }
    return result;
}

// Wildcards
void printAll(List<?> list) { for (Object o : list) System.out.println(o); }
void addNumbers(List<? super Integer> list) { list.add(42); }
void process(List<? extends Number> list) { for (Number n : list) System.out.println(n); }
```

## 6. Lambda & Streams

```java
import java.util.stream.*;
import java.util.function.*;

// Lambda expressions
Function<String, String> upper = s -> s.toUpperCase();
Function<String, String> upper2 = String::toUpperCase;    // method reference
Comparator<String> byLength = (a, b) -> a.length() - b.length();

// Create stream
Stream<String> names = Stream.of("Wes", "Amy", "Bob");
List<Integer> nums = List.of(1, 2, 3, 4, 5);
nums.stream();

// Intermediate operations
nums.stream()
    .filter(n -> n % 2 == 0)                     // keep even
    .map(n -> n * 2)                            // double
    .sorted()                                    // sort
    .distinct()                                  // unique
    .limit(10)                                    // take first 10
    .skip(2)                                      // skip first 2
    .peek(n -> System.out.println("peek: " + n)) // debug
    .collect(Collectors.toList());

// Terminal operations
names.collect(Collectors.toList());
nums.stream().count();
nums.stream().reduce(0, Integer::sum);                        // sum
nums.stream().reduce(Integer::max);                           // max
String.join(", ", names.toList());
nums.stream().anyMatch(n -> n > 10);
nums.stream().allMatch(n -> n > 0);
nums.stream().noneMatch(n -> n < 0);
nums.stream().findFirst();
nums.stream().forEach(System.out::println);

// Collectors
Collectors.toList();
Collectors.toMap(User::name, u -> u);
Collectors.groupingBy(User::country);
Collectors.partitioningBy(u -> u.age() >= 18);
Collectors.joining(", ");
Collectors.counting();
```

## 7. Collections

```java
import java.util.*;

// List
List<String> list = new ArrayList<>();
list.add("a");
list.add(0, "b");
list.get(0);
list.set(0, "c");
list.remove(0);
list.size();
list.contains("a");
list.indexOf("a");
list.sort(Comparator.naturalOrder());

// Immutable (Java 9+)
List<String> immutable = List.of("a", "b", "c");
Map<String, Integer> immutableMap = Map.of("a", 1, "b", 2);

// Map
Map<String, Integer> map = new HashMap<>();
map.put("a", 1);
map.putIfAbsent("b", 2);
map.get("a");
map.getOrDefault("c", 0);
map.remove("a");
map.containsKey("a");
map.containsValue(1);
map.size();

// Iterate map
for (var entry : map.entrySet()) {
    System.out.println(entry.getKey() + ": " + entry.getValue());
}
map.forEach((k, v) -> System.out.println(k + ": " + v));

// Set
Set<String> set = new HashSet<>(List.of("a", "b", "c"));
set.add("d");
set.remove("a");
set.contains("b");
set.size();

// Queue / Deque
Queue<String> queue = new LinkedList<>();
queue.offer("a");
queue.poll();

Deque<String> stack = new ArrayDeque<>();
stack.push("a");
stack.pop();
```

## 8. Exceptions

```java
// Try-catch-finally
try {
    int result = 10 / divisor;
} catch (ArithmeticException e) {
    System.err.println("Math error: " + e.getMessage());
} catch (Exception e) {
    System.err.println("Unexpected: " + e);
} finally {
    // always runs
}

// Try-with-resources (AutoCloseable)
try (var reader = new FileReader("file.txt");
     var br = new BufferedReader(reader)) {
    String line;
    while ((line = br.readLine()) != null) {
        System.out.println(line);
    }
} catch (IOException e) {
    e.printStackTrace();
}

// Custom exception
public class ValidationException extends RuntimeException {
    public ValidationException(String message) {
        super(message);
    }
}

// Throwing
throw new IllegalArgumentException("Invalid input");
throw new ValidationException("Field required");
```

## 9. I/O

```java
import java.io.*;
import java.nio.file.*;

// Read file
List<String> lines = Files.readAllLines(Path.of("file.txt"));
String content = Files.readString(Path.of("file.txt"));
byte[] bytes = Files.readAllBytes(Path.of("data.bin"));

// Write file
Files.write(Path.of("output.txt"), "Hello".getBytes());
Files.writeString(Path.of("output.txt"), "Hello");
Files.write(Path.of("lines.txt"), List.of("line1", "line2"));

// Append
Files.writeString(Path.of("log.txt"), "entry\n",
    StandardOpenOption.CREATE, StandardOpenOption.APPEND);

// Stream lines (memory efficient)
try (Stream<String> stream = Files.lines(Path.of("big.txt"))) {
    stream.filter(l -> l.contains("ERROR")).forEach(System.out::println);
}

// Paths
Path path = Path.of("/dir", "sub", "file.txt");
Path parent = path.getParent();
String fileName = path.getFileName().toString();
Path resolved = Path.of("/base").resolve("file.txt");
boolean exists = Files.exists(path);
Files.createDirectories(Path.of("/new/dir"));
```

## 10. Maven & Gradle

```xml
<!-- pom.xml (Maven) -->
<project>
    <groupId>com.example</groupId>
    <artifactId>my-app</artifactId>
    <version>1.0.0</version>
    <packaging>jar</packaging>

    <dependencies>
        <dependency>
            <groupId>com.google.code.gson</groupId>
            <artifactId>gson</artifactId>
            <version>2.10.1</version>
        </dependency>
    </dependencies>
</project>
```

```bash
# Maven commands
mvn clean compile          # compile
mvn test                  # run tests
mvn package               # build JAR
mvn install               # install to local repo
mvn dependency:tree       # show dependency tree

# Gradle (build.gradle.kts)
```
```kotlin
plugins {
    kotlin("jvm") version "1.9.0"
    application
}
dependencies {
    implementation("com.google.code.gson:gson:2.10.1")
    testImplementation(kotlin("test"))
}
application { mainClass.set("MainKt") }
```
```bash
# Gradle commands
gradle build              # build
gradle test              # test
gradle run               # run application
gradle dependencies      # show dependency tree
```
