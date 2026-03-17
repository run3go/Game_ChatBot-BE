from sqlalchemy.orm import Session
from sqlalchemy import text

class SchemaBuilder:

    def __init__(self, db : Session):
        self.db = db

    def build_summary(self):

        rows = self.db.execute(text("""
            SELECT 
                C.relname AS table_name,
                obj_description(C.oid, 'pg_class') AS table_comment
            FROM pg_class C
            LEFT JOIN pg_namespace N ON N.oid = C.relnamespace
            WHERE nspname = 'lostark' 
              AND C.relkind = 'r'
            ORDER BY table_name;
        """))

        return {row.table_name: (row.table_comment or "") for row in rows}

    def build(self, relevant_tables: list):

        if not relevant_tables:
            return {}

        rows = self.db.execute(text("""
            SELECT
                t.table_name,
                obj_description((t.table_schema || '.' || t.table_name)::regclass) AS table_comment,
                c.column_name,
                col_description(
                    (t.table_schema || '.' || t.table_name)::regclass::oid,
                    c.ordinal_position
                ) AS column_comment
            FROM information_schema.tables t
            JOIN information_schema.columns c
                ON t.table_name = c.table_name
                AND t.table_schema = c.table_schema
            WHERE t.table_schema = 'lostark'
            AND t.table_name IN :table_list  -- 파라미터 바인딩 추가
            ORDER BY t.table_name, c.ordinal_position
        """), {"table_list": tuple(relevant_tables)})

        schema = {}

        for row in rows:
            table = row.table_name
            table_comment = row.table_comment or ""
            column = row.column_name
            column_comment = row.column_comment or ""

            if table not in schema:
                schema[table] = {
                    "comment": table_comment,
                    "columns": []
                }

            schema[table]["columns"].append({
                "column": column,
                "comment": column_comment
            })

        return schema
    
    