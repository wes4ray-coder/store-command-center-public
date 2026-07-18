# PHP Quick Reference

> Offline reference guide for AI agents. Last updated: 2026-07-10.

## Contents
1. Types & Variables
2. Arrays
3. Strings
4. Functions
5. Classes & OOP
6. Namespaces
7. Error Handling
8. Composer
9. Common Patterns
10. Gotchas

## 1. Types & Variables

```php
// Variables (always start with $)
$name = "Wesley";
$age = 30;
$price = 19.99;
$active = true;
$nothing = null;

// Type checking
gettype($var);                  // "string", "integer", etc.
is_int($var); is_string($var); is_array($var); is_null($var);
is_bool($var); is_float($var); is_object($var);

// Type casting
$int = (int) "42";
$float = (float) "3.14";
$str = (string) 42;
$arr = (array) $obj;
$bool = (bool) 1;              // true

// Constants
define("MAX_USERS", 100);
const PI = 3.14159;            // can be in class
echo MAX_USERS;

// Null coalescing
$name = $_GET['name'] ?? "default";
$name = $user['name'] ?? $profile['name'] ?? "anonymous";

// Null safe operator (PHP 8+)
$country = $user?->address?->country;   // null instead of error

// Spread operator
$args = [1, 2, 3];
sum(...$args);                 // same as sum(1, 2, 3)
$merged = [...$arr1, ...$arr2];
```

## 2. Arrays

```php
// Indexed array
$fruits = ["apple", "banana", "cherry"];
$fruits[] = "date";            // append
$fruits[0];                    // "apple"
count($fruits);                // 4
array_push($fruits, "elderberry");
array_pop($fruits);            // remove last
array_shift($fruits);           // remove first
array_unshift($fruits, "apricot"); // prepend

// Associative array
$user = ["name" => "Wes", "age" => 30, "active" => true];
$user["name"];                 // "Wes"
$user["email"] = "wes@example.com";  // add key
isset($user["email"]);         // true
unset($user["email"]);          // remove key
count($user);

// Multidimensional
$matrix = [[1, 2], [3, 4]];
$people = [
    ["name" => "Wes", "age" => 30],
    ["name" => "Amy", "age" => 25],
];

// Array functions
array_map(fn($x) => $x * 2, [1, 2, 3]);      // [2, 4, 6]
array_filter([1, 2, 3, 4], fn($x) => $x > 2); // [3, 4]
array_reduce([1, 2, 3], fn($carry, $x) => $carry + $x, 0); // 6
array_merge($arr1, $arr2);
array_slice($arr, 1, 2);       // elements at offset 1, length 2
array_keys($assoc);            // ["name", "age", "active"]
array_values($assoc);          // re-index numerically
array_unique($arr);            // remove duplicates
array_search("banana", $fruits); // index or false
in_array("apple", $arr);       // boolean
sort($arr); rsort($arr);       // sort ascending/descending
asort($assoc);                  // sort by value, preserve keys
ksort($assoc);                  // sort by key
usort($arr, fn($a, $b) => $a - $b);  // custom sort

// Iterate
foreach ($fruits as $fruit) { echo $fruit; }
foreach ($user as $key => $value) { echo "$key: $value"; }

// Destructuring
[$a, $b, $c] = [1, 2, 3];
["name" => $name, "age" => $age] = $user;
```

## 3. Strings

```php
// Basic
$s = "Hello World";
strlen($s);                    // 11
str_word_count($s);            // 2
strtoupper($s); strtolower($s);
ucfirst($s);                   // Capitalize first
str_replace("World", "PHP", $s);
substr($s, 0, 5);              // "Hello"
strpos($s, "World");            // 6 (or false)
str_contains($s, "World");     // true (PHP 8+)
str_starts_with($s, "Hello");  // true (PHP 8+)
str_ends_with($s, "World");    // true (PHP 8+)
trim("  hi  ");                 // "hi"
explode(",", "a,b,c");         // ["a", "b", "c"]
implode(",", ["a", "b", "c"]); // "a,b,c"

// String interpolation
$name = "Wes";
echo "Hello, $name!";          // double quotes interpolate
echo "Hello, {$name}!";        // braces for complex
echo 'Hello, $name!';          // single quotes: NO interpolation
sprintf("Name: %s, Age: %d", $name, 30);

// Heredoc / Nowdoc
$text = <<<EOT
Multi-line string with $interpolation
EOT;

$raw = <<<'EOT'
No interpolation here
EOT;
```

## 4. Functions

```php
// Basic
function add(int $a, int $b): int {
    return $a + $b;
}

// Default values
function greet(string $name = "World"): string {
    return "Hello, $name!";
}

// Variadic
function sum(int ...$nums): int {
    return array_sum($nums);
}
sum(1, 2, 3, 4);               // 10

// Named arguments (PHP 8+)
function create_user(string $name, int $age, bool $active = true) { /* ... */ }
create_user(name: "Wes", age: 30);
create_user(age: 25, name: "Amy", active: false);

// Anonymous functions (closures)
$multiplier = function($x) { return $x * 2; };
$multiplier(5);               // 10

// Arrow functions (PHP 7.4+)
$double = fn($x) => $x * 2;
$double(5);                    // 10

// Closures capturing variables
$count = 0;
$increment = function() use (&$count) { $count++; };
$increment(); $increment();
echo $count;                  // 2

// First-class function Syntax
$fns = fn($n) => $n ** 2;
array_map($fns, [1, 2, 3]);   // [1, 4, 9]
```

## 5. Classes & OOP

```php
class User {
    // Properties
    public string $name;
    protected int $age;
    private string $email;
    
    // Constructor promotion (PHP 8+)
    public function __construct(
        string $name,
        int $age,
        string $email = ''
    ) {
        $this->name = $name;
        $this->age = $age;
        $this->email = $email;
    }
    
    // Methods
    public function greet(): string {
        return "Hi, I'm {$this->name}";
    }
    
    // Static
    public static int $count = 0;
    public static function create(): self {
        self::$count++;
        return new self("User" . self::$count, 0);
    }
    
    // Magic methods
    public function __toString(): string {
        return $this->name;
    }
    
    public function __get($key) {
        return $this->$key ?? null;
    }
}

// Inheritance
class Admin extends User {
    public array $permissions;
    
    public function __construct(string $name, int $age, array $permissions) {
        parent::__construct($name, $age);
        $this->permissions = $permissions;
    }
    
    // Override
    public function greet(): string {
        return parent::greet() . " (Admin)";
    }
}

// Interfaces
interface Repository {
    public function find(int $id): ?array;
    public function save(array $data): int;
    public function delete(int $id): bool;
}

class UserRepo implements Repository {
    public function find(int $id): ?array { /* ... */ }
    public function save(array $data): int { /* ... */ }
    public function delete(int $id): bool { /* ... */ }
}

// Abstract classes
abstract class Model {
    abstract protected function table(): string;
    
    public function all(): array {
        // use $this->table()
    }
}

// Traits (horizontal reuse)
trait Timestamps {
    public function createdAt(): DateTime { /* ... */ }
    public function updatedAt(): DateTime { /* ... */ }
}

class Post extends Model {
    use Timestamps;
}

// Enums (PHP 8.1+)
enum Status: string {
    case Active = 'active';
    case Inactive = 'inactive';
    case Pending = 'pending';
    
    public function label(): string {
        return ucfirst($this->value);
    }
}
Status::Active->label();       // "Active"
```

## 6. Namespaces

```php
namespace App\Services;

use App\Models\User;
use App\Repositories\UserRepository;
use Exception;

class UserService {
    public function __construct(
        private UserRepository $repo
    ) {}
    
    public function getUser(int $id): ?User {
        return $this->repo->find($id);
    }
}

// Autoloading via Composer (PSR-4)
// composer.json:
// "autoload": { "psr-4": { "App\\": "src/" } }
```

## 7. Error Handling

```php
try {
    throw new Exception("Something went wrong");
} catch (Exception $e) {
    echo $e->getMessage();
} catch (TypeError $e) {
    echo "Type error: " . $e->getMessage();
} finally {
    // always runs
}

// Custom exceptions
class ValidationException extends Exception {
    public function __construct(string $field, string $message) {
        parent::__construct("$field: $message");
    }
}

// Error reporting
error_reporting(E_ALL);
ini_set('display_errors', '1');
set_error_handler(function($severity, $message, $file, $line) {
    throw new ErrorException($message, 0, $severity, $file, $line);
});
```

## 8. Composer

```bash
# Initialize
composer init

# Add package
composer require guzzlehttp/guzzle
composer require --dev phpunit/phpunit

# Autoload
composer dump-autoload
composer dump-autoload --optimize

# Update
composer update
composer update guzzlehttp/guzzle

# Scripts
# composer.json:
# "scripts": {
#     "test": "phpunit",
#     "serve": "php -S localhost:8000 -t public"
# }
composer test
composer serve
```

```json
{
    "require": {
        "php": ">=8.1",
        "guzzlehttp/guzzle": "^7.0"
    },
    "require-dev": {
        "phpunit/phpunit": "^10.0"
    },
    "autoload": {
        "psr-4": { "App\\": "src/" }
    }
}
```

## 9. Common Patterns

```php
// Singleton
class Database {
    private static ?Database $instance = null;
    public static function getInstance(): self {
        return self::$instance ??= new self();
    }
    private function __construct() {}
}

// Factory
interface Shape { public function area(): float; }
class Circle implements Shape {
    public function __construct(private float $r) {}
    public function area(): float { return pi() * $this->r ** 2; }
}
class ShapeFactory {
    public static function create(string $type, array $params): Shape {
        return match($type) {
            'circle' => new Circle($params['radius']),
            default => throw new InvalidArgumentException("Unknown: $type")
        };
    }
}

// Dependency injection
class UserController {
    public function __construct(
        private UserService $service
    ) {}
}

// Match expression (PHP 8+)
$status = match($code) {
    200, 201 => 'success',
    404 => 'not found',
    500 => 'server error',
    default => 'unknown'
};
```

## 10. Gotchas

```php
// == vs === (ALWAYS use ===)
"0" == 0                       // true (type juggling)
"0" === 0                      // false (strict)
null == false                   // true
null === false                  // false
"abc" == 0                      // true (string cast to int = 0)
"abc" === 0                     // false

// Array vs Object comparison
[1, 2] == [1, 2]               // true
(new stdClass) == (new stdClass) // true
// But comparing objects: == checks properties, === checks same instance

// foreach modifies array copy by default
$arr = [1, 2, 3];
foreach ($arr as &$val) { $val *= 2; }  // & for reference
unset($val);                   // break reference after foreach

// json_decode returns stdClass by default, assoc array with true
$obj = json_decode('{"a":1}');  // stdClass, $obj->a
$arr = json_decode('{"a":1}', true);  // array, $arr['a']

// Null coalescing for array access prevents notices
$name = $data['user']['name'] ?? 'unknown';  // no notice if missing
```
