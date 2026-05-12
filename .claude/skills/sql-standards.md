---
name: sql-standards
description: Detailed SQL formatting and procedure standards
---

# SQL Standards

## Formatting Rules

### Indentation & Layout

- **Tab indentation only** — no spaces
- All SQL keywords **UPPERCASE**
- No blank lines between clauses
- Semicolon on its own final line
- Leading commas on all multi-line lists

Example:
```sql
SELECT
	,user_id
	,user_name
	,CASE
		WHEN status = 'active' THEN 1
		ELSE 0
	END AS is_active
FROM
	users
WHERE
	created_date >= '2024-01-01'
	AND status IN ('active', 'pending')
ORDER BY
	user_id DESC
;
```

### CTEs (Common Table Expressions)

Never use subqueries — use CTEs instead:

```sql
-- CORRECT: Using CTE
WITH active_users AS (
	SELECT
		,user_id
		,user_name
	FROM
		users
	WHERE
		status = 'active'
)
SELECT
	,au.user_id
	,au.user_name
	,COUNT(o.order_id) AS order_count
FROM
	active_users au
LEFT JOIN
	orders o ON au.user_id = o.user_id
GROUP BY
	au.user_id
	,au.user_name
;

-- WRONG: Using subquery
-- SELECT
--	,user_id
--	,order_count
-- FROM (
--	SELECT ... FROM ... WHERE ...
-- ) subq
```

### Large IN Lists

Never inline long IN lists — move to CTE and join:

```sql
-- CORRECT
WITH user_filter AS (
	SELECT 123 AS user_id UNION ALL
	SELECT 456 UNION ALL
	SELECT 789
)
SELECT
	,u.user_id
	,u.user_name
FROM
	users u
INNER JOIN
	user_filter uf ON u.user_id = uf.user_id
;

-- WRONG
-- WHERE user_id IN (123, 456, 789, 1011, 1213, ...)
```

### Aliasing

- Aliased columns one per line
- Meaningful aliases (not `a`, `b`, `c`)
- Include full alias path: `table_alias.column_name AS alias_name`

```sql
SELECT
	,u.user_id AS user_id
	,u.user_name AS user_name
	,COUNT(o.order_id) AS total_orders
	,SUM(o.order_amount) AS total_spent
FROM
	users u
LEFT JOIN
	orders o ON u.user_id = o.user_id
GROUP BY
	u.user_id
	,u.user_name
;
```

---

## Prohibited SQL Patterns

- ❌ **WHERE 1=1** — Never use as placeholder
- ❌ **Subqueries** — Use CTEs instead
- ❌ **Inline large IN lists** — Move to CTE and join
- ❌ **String-formatted SQL** — Use parameterized queries always
- ❌ **Inventing column/table names** — Preserve exactly

---

## Performance Optimization

Query design for:

- **Large tables** (millions to terabytes)
- **Predicate-driven queries** — filter early and aggressively
- **Reporting-heavy workloads** — optimize for analytical queries
- **Zero-downtime environments** — avoid locks and blocking operations

### Best Practices

- Index on WHERE and JOIN predicates
- Aggregate and filter in SQL, not in application
- Use window functions for complex aggregations instead of subqueries
- Avoid SELECT * — specify only needed columns
- Use EXPLAIN to verify query plans on large datasets

---

## Stored Procedures

### Structure

Procedures must follow this pattern:

```sql
CREATE PROCEDURE sp_process_batch
	@environment VARCHAR(10)
	,@batch_id INT
	,@chunk_size INT = 1000
AS
BEGIN
	SET NOCOUNT ON;
	
	DECLARE @step_name NVARCHAR(100);
	DECLARE @rows_processed INT = 0;
	DECLARE @start_time DATETIME = GETUTCDATE();
	
	BEGIN TRY
		-- Step 1: Validate inputs
		SET @step_name = 'Validate inputs';
		IF @batch_id IS NULL
			THROW 50001, 'Batch ID required', 1;
		
		-- Step 2: Process records
		SET @step_name = 'Process records';
		WHILE @rows_processed < @chunk_size
		BEGIN
			-- Process logic here
			SET @rows_processed = @rows_processed + 1;
		END
		
		-- Step 3: Log completion
		SET @step_name = 'Log completion';
		INSERT INTO audit_log (procedure_name, status, duration_seconds)
		VALUES (
			'sp_process_batch'
			,'SUCCESS'
			,DATEDIFF(SECOND, @start_time, GETUTCDATE())
		);
	
	END TRY
	BEGIN CATCH
		-- Log error and re-raise
		INSERT INTO audit_log (procedure_name, status, error_message)
		VALUES (
			'sp_process_batch'
			,'ERROR'
			,ERROR_MESSAGE()
		);
		THROW;
	END CATCH
END
;
```

### Procedure Rules

- **Restart-safe** — must be idempotent; safe to retry
- **Logging** — log all dynamic SQL and critical steps
- **No hidden side effects** — document all writes/deletes
- **Deterministic behavior** — same inputs produce same results
- **Parameterized** — all WHERE clauses use parameters, never string-formatted
- **Chunking** — break large operations into batches to avoid locks
- **Error handling** — explicit TRY/CATCH with meaningful error messages

### Dynamic SQL

If dynamic SQL required:

```sql
-- Log the dynamic SQL before executing
DECLARE @sql NVARCHAR(MAX);
DECLARE @table_name NVARCHAR(100) = 'users';

SET @sql = 'SELECT COUNT(*) FROM ' + QUOTENAME(@table_name);

-- Log it (audit trail)
INSERT INTO procedure_audit (sql_text, executed_at)
VALUES (@sql, GETUTCDATE());

-- Execute safely
EXEC sp_executesql @sql;
```

---

## Parameter Usage

Always use parameterized queries — never string-formatted SQL:

```sql
-- CORRECT: Parameterized
DECLARE @user_id INT = 123;
SELECT * FROM users WHERE user_id = @user_id;

-- WRONG: String-formatted (dangerous and slow)
-- EXEC ('SELECT * FROM users WHERE user_id = ' + @user_id);
```

---

## Large Table Operations

For operations on tables with millions of rows:

1. **Add WHERE clause** to limit scope
2. **Chunk operations** — process in batches to avoid locks
3. **Index predicates** — ensure WHERE columns are indexed
4. **Avoid temp tables** unless explicitly justified
5. **Monitor duration** — log execution time
6. **Test on production-sized data** — don't assume smaller datasets behave the same

Example:
```sql
-- Process 10,000 records at a time
DECLARE @batch_size INT = 10000;
DECLARE @max_id INT = (SELECT MAX(id) FROM large_table);
DECLARE @current_id INT = 0;

WHILE @current_id < @max_id
BEGIN
	UPDATE
		large_table
	SET
		status = 'processed'
		,updated_at = GETUTCDATE()
	WHERE
		id > @current_id
		AND id <= @current_id + @batch_size
		AND status = 'pending'
	;
	
	SET @current_id = @current_id + @batch_size;
	
	-- Log progress
	PRINT CONCAT('Processed up to ID: ', @current_id);
END
;
```

---

## Testing

- Run EXPLAIN/execution plan on all queries before production
- Test with production-scale data volumes
- Verify indexes are used (no table scans on large tables)
- Check for locks/blocking with long-running procedures
- Validate edge cases: empty result sets, NULL values, boundary conditions

