-- ============================================================================
-- Procedure: dbo.pCreateTableIfMissing
--
-- Creates a table if it does not exist, using a schema-qualified table name
-- and a CSV string of columns with datatypes.
--
-- Parameters:
--   @TableName NVARCHAR(256)   -- Schema-qualified table name (e.g. 'dbo.MyTable')
--   @Columns   NVARCHAR(MAX)   -- CSV: 'col1 INT, col2 VARCHAR(50), ...'
--
-- Returns:
--   0 = Table already existed or was created successfully
--   1 = Error (see RAISERROR)
-- ============================================================================
CREATE PROCEDURE dbo.pCreateTableIfMissing
    @TableName NVARCHAR(256),
    @Columns   NVARCHAR(MAX)
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @SchemaName NVARCHAR(128);
    DECLARE @ObjectName NVARCHAR(128);
    DECLARE @SQL NVARCHAR(MAX);

    -- Parse schema and object name
    IF CHARINDEX('.', @TableName) > 0
    BEGIN
        SET @SchemaName = LEFT(@TableName, CHARINDEX('.', @TableName) - 1);
        SET @ObjectName = RIGHT(@TableName, LEN(@TableName) - CHARINDEX('.', @TableName));
    END
    ELSE
    BEGIN
        SET @SchemaName = 'dbo';
        SET @ObjectName = @TableName;
    END

    -- Check if table exists
    IF EXISTS (
        SELECT 1 FROM sys.tables t
        INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE t.name = @ObjectName AND s.name = @SchemaName
    )
    BEGIN
        RETURN 0; -- Table exists
    END

    -- Compose CREATE TABLE statement
    SET @SQL = N'CREATE TABLE [' + @SchemaName + N'].[' + @ObjectName + N'] (' + @Columns + N');';


        [dbo].[pRun_LoggedSQL]
	@sql as nvarchar(max)
	, @BatchID as integer = null
	, @recompile as bit = 0


    RETURN 0;
END
GO
