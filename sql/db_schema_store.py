import os
from langchain_openai import OpenAIEmbeddings
from sqlalchemy import text
from sqlalchemy.orm import Session


class DBSchemaStore:
    """
    pgvector 기반 온-디맨드 스키마 검색.
    앱 시작 시 아무것도 로드하지 않고, 요청마다:
      1. 키워드 임베딩 → schema_comments_tb에서 유사 테이블명 검색
      2. 검색된 테이블(2~5개)의 컬럼 정보만 DB에서 조회
    """

    def __init__(self):
        self._embeddings: OpenAIEmbeddings | None = None

    def _get_embeddings(self) -> OpenAIEmbeddings:
        if self._embeddings is None:
            self._embeddings = OpenAIEmbeddings(
                model="openai/text-embedding-3-small",
                openai_api_key=os.getenv("OPENROUTER_API_KEY"),
                openai_api_base="https://openrouter.ai/api/v1",
            )
        return self._embeddings

    def search(self, db: Session, keywords: list[str], threshold: float = 0.45) -> list[str]:
        seen: set = set()
        tables: list[str] = []

        for keyword in keywords:
            vector = self._get_embeddings().embed_query(keyword)
            rows = db.execute(text("""
                SELECT table_name,
                       1 - (comment_embedding <=> CAST(:vec AS vector)) AS score
                FROM lostark.schema_comments_tb
                WHERE schema_name = 'lostark'
                  AND comment_embedding IS NOT NULL
                ORDER BY comment_embedding <=> CAST(:vec AS vector)
                LIMIT 10
            """), {"vec": str(vector)}).mappings().all()

            added = 0
            for row in rows:
                t = row["table_name"]
                score = float(row["score"])
                if t not in seen:
                    if score >= threshold or added == 0:
                        seen.add(t)
                        tables.append(t)
                        added += 1
                    else:
                        break

        return tables

    def get_schema(self, db: Session, tables: list[str]) -> dict:
        """선택된 테이블의 컬럼 정보만 on-demand 조회."""
        if not tables:
            return {}
        rows = db.execute(text("""
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
              AND t.table_name = ANY(:tables)
            ORDER BY t.table_name, c.ordinal_position
        """), {"tables": tables}).mappings().all()

        schema: dict = {}
        for row in rows:
            tname = row["table_name"]
            if tname not in schema:
                schema[tname] = {"comment": row["table_comment"] or "", "columns": []}
            schema[tname]["columns"].append({
                "column": row["column_name"],
                "comment": row["column_comment"] or "",
            })
        return schema

    def get_all_tables(self, db: Session) -> set[str]:
        """허용 테이블 목록 조회 (SQL 유효성 검증용)."""
        rows = db.execute(text("""
            SELECT DISTINCT table_name
            FROM lostark.schema_comments_tb
            WHERE schema_name = 'lostark'
        """)).mappings().all()
        return {row["table_name"] for row in rows}


DB_SCHEMA_STORE = DBSchemaStore()
