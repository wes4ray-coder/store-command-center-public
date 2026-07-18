# SQL Quick Reference

> Offline reference guide for AI agents. Last updated: 2026-07-10.

## Contents
1. CRUD Operations
2. Filtering & Ordering
3. JOINs
4. Aggregation
5. Subqueries & CTEs
6. Indexes
7. SQLite Specifics
8. PostgreSQL Specifics
9. Transactions
10. Common Patterns

## 1. CRUD Operations

```sql
-- INSERT
INSERT INTO users (name, email, age) VALUES ('Wes', 'wes@example.com', 30);
INSERT INTO users (name, email) VALUES ('Amy', 'amy@example.com'), ('Bob', 'bob@example.com');
INSERT INTO users SELECT * FROM temp_users WHERE valid = 1;

-- SELECT
SELECT * FROM users;
SELECT name, email FROM users;
SELECT name, email, created_at FROM users WHERE active = 1;
SELECT DISTINCT country FROM users;

-- UPDATE
UPDATE users SET name = 'Wesley', age = 31 WHERE id = 1;
UPDATE products SET price = price * 1.1 WHERE category = 'electronics';

-- DELETE
DELETE FROM users WHERE id = 1;
DELETE FROM logs WHERE created_at < '2026-01-01';
DELETE FROM temp;  -- delete all rows (use TRUNCATE for speed)

-- UPSERT (varies by DB)
-- SQLite:
INSERT INTO users (id, name) VALUES (1, 'Wes') ON CONFLICT(id) DO UPDATE SET name = 'Wes';
-- PostgreSQL:
INSERT INTO users (id, name) VALUES (1, 'Wes') ON CONFLICT(id) DO UPDATE SET name = EXCLUDED.name;
-- MySQL:
INSERT INTO users (id, name) VALUES (1, 'Wes') ON DUPLICATE KEY UPDATE name = 'Wes';
```

## 2. Filtering & Ordering

```sql
-- WHERE
SELECT * FROM users WHERE age >= 18 AND age <= 65;
SELECT * FROM users WHERE country IN ('US', 'CA', 'UK');
SELECT * FROM users WHERE name LIKE 'Wes%';
SELECT * FROM users WHERE name LIKE '_es';       -- _ = single char
SELECT * FROM users WHERE age BETWEEN 18 AND 65;
SELECT * FROM users WHERE email IS NULL;
SELECT * FROM users WHERE email IS NOT NULL;
SELECT * FROM users WHERE NOT active;

-- Multiple conditions
SELECT * FROM products WHERE (category = 'A' OR category = 'B') AND price < 100;
SELECT * FROM users WHERE age > 18 AND (country = 'US' OR country = 'CA');

-- ORDER BY
SELECT * FROM users ORDER BY name ASC;
SELECT * FROM users ORDER BY created_at DESC;
SELECT * FROM users ORDER BY country ASC, name DESC;

-- LIMIT / OFFSET
SELECT * FROM users LIMIT 10;
SELECT * FROM users LIMIT 10 OFFSET 20;    -- page 3
SELECT * FROM users LIMIT 20, 10;          -- MySQL: offset 20, limit 10

-- Pattern matching (PostgreSQL ~ regex)
SELECT * FROM users WHERE name ~ '^Wes';     -- starts with Wes
SELECT * FROM users WHERE name ~* '^wes';    -- case-insensitive
```

## 3. JOINs

```sql
-- INNER JOIN (matching rows only)
SELECT u.name, o.product, o.quantity
FROM users u
INNER JOIN orders o ON u.id = o.user_id;

-- LEFT JOIN (all from left, matching from right)
SELECT u.name, o.product
FROM users u
LEFT JOIN orders o ON u.id = o.user_id;
-- users without orders: o.product will be NULL

-- RIGHT JOIN (all from right, matching from left)
SELECT u.name, o.product
FROM users u
RIGHT JOIN orders o ON u.id = o.user_id;

-- FULL OUTER JOIN (all rows from both)
SELECT u.name, o.product
FROM users u
FULL OUTER JOIN orders o ON u.id = o.user_id;

-- Multiple JOINs
SELECT u.name, o.product, p.category
FROM users u
JOIN orders o ON u.id = o.user_id
JOIN products p ON o.product_id = p.id
WHERE p.category = 'electronics';

-- Self JOIN
SELECT e.name AS employee, m.name AS manager
FROM employees e
LEFT JOIN employees m ON e.manager_id = m.id;

-- CROSS JOIN (Cartesian product — careful!)
SELECT * FROM colors CROSS JOIN sizes;
SELECT * FROM colors, sizes;  -- same thing
```

## 4. Aggregation

```sql
-- GROUP BY
SELECT category, COUNT(*) AS count FROM products GROUP BY category;
SELECT user_id, SUM(amount) AS total FROM orders GROUP BY user_id;
SELECT country, AVG(age) AS avg_age FROM users GROUP BY country;

-- HAVING (filter after grouping)
SELECT category, COUNT(*) AS count
FROM products
GROUP BY category
HAVING COUNT(*) > 5;

-- Multiple aggregates
SELECT category,
  COUNT(*) AS total,
  AVG(price) AS avg_price,
  MIN(price) AS min_price,
  MAX(price) AS max_price,
  SUM(stock) AS total_stock
FROM products
GROUP BY category;

-- GROUP BY multiple columns
SELECT country, city, COUNT(*) AS users
FROM users
GROUP BY country, city
ORDER BY country, users DESC;
```

## 5. Subqueries & CTEs

```sql
-- Scalar subquery
SELECT name, (SELECT COUNT(*) FROM orders WHERE user_id = users.id) AS order_count
FROM users;

-- IN subquery
SELECT * FROM users WHERE id IN (SELECT user_id FROM orders WHERE amount > 100);

-- EXISTS
SELECT * FROM users u WHERE EXISTS (SELECT 1 FROM orders o WHERE o.user_id = u.id);

-- CTE (Common Table Expression)
WITH active_users AS (
  SELECT * FROM users WHERE active = 1
),
big_spenders AS (
  SELECT user_id, SUM(amount) AS total FROM orders GROUP BY user_id HAVING SUM(amount) > 1000
)
SELECT au.name, bs.total
FROM active_users au
JOIN big_spenders bs ON au.id = bs.user_id;

-- Recursive CTE (hierarchy)
WITH RECURSIVE hierarchy AS (
  SELECT id, name, manager_id, 1 AS level FROM employees WHERE manager_id IS NULL
  UNION ALL
  SELECT e.id, e.name, e.manager_id, h.level + 1
  FROM employees e JOIN hierarchy h ON e.manager_id = h.id
)
SELECT name, level FROM hierarchy ORDER BY level;

-- Window functions
SELECT name, salary,
  RANK() OVER (ORDER BY salary DESC) AS rank,
  ROW_NUMBER() OVER (ORDER BY salary DESC) AS row_num,
  DENSE_RANK() OVER (ORDER BY salary DESC) AS dense_rank,
  LAG(name, 1) OVER (ORDER BY id) AS prev_name,
  LEAD(name, 1) OVER (ORDER BY id) AS next_name,
  SUM(salary) OVER (PARTITION BY department) AS dept_total,
  AVG(salary) OVER (PARTITION BY department) AS dept_avg
FROM employees;
```

## 6. Indexes

```sql
-- Create index
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_name_age ON users(name, age);   -- composite
CREATE UNIQUE INDEX idx_unique_email ON users(email);

-- Drop index
DROP INDEX idx_users_email;
-- PostgreSQL: DROP INDEX IF EXISTS idx_users_email;

-- View indexes
-- SQLite: PRAGMA index_list(users);
-- PostgreSQL: \d users  or  SELECT * FROM pg_indexes WHERE tablename = 'users';
-- MySQL: SHOW INDEX FROM users;

-- When to index:
-- Index columns used in WHERE, JOIN, ORDER BY
-- Don't over-index (slows down writes)
-- Composite indexes: order by selectivity (most selective first)
```

## 7. SQLite Specifics

```sql
-- PRAGMA settings
PRAGMA table_info(users);
PRAGMA index_list(users);
PRAGMA journal_mode = WAL;        -- Write-Ahead Logging (better concurrency)
PRAGMA foreign_keys = ON;
PRAGMA foreign_keys;              -- check current value (0 or 1)
PRAGMA busy_timeout = 5000;       -- wait 5s on lock

-- Autoincrement (rowid by default)
CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT);

-- Date/time
SELECT date('now');
SELECT datetime('now');
SELECT date('now', '-7 days');
SELECT strftime('%Y-%m-%d', 'now');
SELECT date('2026-07-10', '+1 month');

-- SQLite types: INTEGER, REAL, TEXT, BLOB, NULL
-- No native BOOLEAN — use INTEGER 0/1
-- No native DATE — use TEXT (ISO8601) or INTEGER (unix)

-- No ALTER COLUMN — must recreate table:
-- 1. CREATE new_table with desired schema
-- 2. INSERT INTO new_table SELECT ... FROM old_table
-- 3. DROP old_table
-- 4. RENAME new_table TO old_table

-- Upsert
INSERT INTO users (id, name) VALUES (1, 'Wes') ON CONFLICT(id) DO UPDATE SET name = excluded.name;

-- JSON (SQLite 3.9+)
SELECT json_extract(data, '$.name') FROM documents;
SELECT json_array_length('[1, 2, 3]');  -- 3
```

## 8. PostgreSQL Specifics

```sql
-- Serial / identity (auto-increment)
CREATE TABLE users (id SERIAL PRIMARY KEY, name TEXT);
-- or: id GENERATED ALWAYS AS IDENTITY PRIMARY KEY

-- JSON/JSONB
INSERT INTO config (settings) VALUES ('{"theme": "dark", "lang": "en"}');
SELECT settings->'theme' FROM config;
SELECT settings->>'theme' FROM config;          -- as text
SELECT * FROM config WHERE settings @> '{"theme": "dark"}';  -- contains
CREATE INDEX ON config USING gin(settings);     -- GIN index for JSONB

-- Arrays
SELECT * FROM users WHERE 'admin' = ANY(roles);
SELECT array_length(roles, 1) FROM users;
UPDATE users SET roles = array_append(roles, 'editor');

-- UPSERT
INSERT INTO users (id, name) VALUES (1, 'Wes')
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name;

-- RETURNING (get values back after insert/update)
INSERT INTO users (name) VALUES ('Wes') RETURNING id, created_at;
UPDATE users SET active = false WHERE id = 1 RETURNING *;
DELETE FROM users WHERE active = false RETURNING id;

-- String functions
SELECT string_agg(name, ', ' ORDER BY name) FROM users;
SELECT array_agg(name ORDER BY name) FROM users;

-- Date/time
SELECT NOW(), CURRENT_DATE, CURRENT_TIMESTAMP;
SELECT age('2026-07-10', '1995-03-15');         -- interval
SELECT '2026-07-10'::date + 7;                  -- date arithmetic
SELECT EXTRACT(MONTH FROM created_at) FROM users;
```

## 9. Transactions

```sql
BEGIN;
  UPDATE accounts SET balance = balance - 100 WHERE id = 1;
  UPDATE accounts SET balance = balance + 100 WHERE id = 2;
COMMIT;
-- or ROLLBACK on error

-- SAVEPOINT
BEGIN;
  INSERT INTO orders (user_id, amount) VALUES (1, 50);
  SAVEPOINT after_order;
  INSERT INTO items (order_id, name) VALUES (1, 'widget');
  -- if this fails:
  ROLLBACK TO after_order;
  -- order still there, items rolled back
COMMIT;

-- Isolation levels (PostgreSQL)
SET TRANSACTION ISOLATION LEVEL READ COMMITTED;    -- default
SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;
SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;
```

## 10. Common Patterns

```sql
-- Pagination
SELECT * FROM users ORDER BY id LIMIT 20 OFFSET 40;
-- Keyset pagination (faster for large tables):
SELECT * FROM users WHERE id > 100 ORDER BY id LIMIT 20;

-- Find duplicates
SELECT email, COUNT(*) FROM users GROUP BY email HAVING COUNT(*) > 1;

-- Delete duplicates (keep first)
DELETE FROM users WHERE id NOT IN (
  SELECT MIN(id) FROM users GROUP BY email
);

-- Pivot (conditional aggregation)
SELECT user_id,
  SUM(CASE WHEN category = 'A' THEN amount ELSE 0 END) AS total_a,
  SUM(CASE WHEN category = 'B' THEN amount ELSE 0 END) AS total_b
FROM orders GROUP BY user_id;

-- Running total
SELECT id, amount,
  SUM(amount) OVER (ORDER BY id) AS running_total
FROM orders;

-- Top N per group
SELECT * FROM (
  SELECT *,
    ROW_NUMBER() OVER (PARTITION BY category ORDER BY price DESC) AS rn
  FROM products
) WHERE rn <= 3;

-- Concatenate rows
-- PostgreSQL:
SELECT string_agg(name, ', ') FROM users;
-- SQLite:
SELECT group_concat(name, ', ') FROM users;
-- MySQL:
SELECT GROUP_CONCAT(name SEPARATOR ', ') FROM users;

-- Difference between consecutive rows
SELECT id, value,
  value - LAG(value) OVER (ORDER BY id) AS diff
FROM measurements;
```
