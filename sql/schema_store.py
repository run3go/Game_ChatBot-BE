import os
from langchain_openai import OpenAIEmbeddings
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_core.documents import Document
from sqlalchemy.orm import Session

from sql.schema_builder import SchemaBuilder
# from sql.game_knowledge import GAME_KNOWLEDGE_DOCS


class SchemaVectorStore:

    def __init__(self):
        self._store: InMemoryVectorStore | None = None
        self._summary: dict = {}
        self._detail: dict = {}

    def load(self, db: Session):
        builder = SchemaBuilder(db)
        self._summary = builder.build_summary()
        self._detail = builder.build_all()

        embeddings = OpenAIEmbeddings(
            model="openai/text-embedding-3-small",
            openai_api_key=os.getenv("OPENROUTER_API_KEY"),
            openai_api_base="https://openrouter.ai/api/v1",
        )

        docs = []
        for table, comment in self._summary.items():
            docs.append(Document(page_content=f"{table}: {comment}", metadata={"table": table}))
        for table, schema in self._detail.items():
            for col in schema["columns"]:
                if col["comment"]:
                    docs.append(Document(page_content=col["comment"], metadata={"table": table}))
        # docs.extend(GAME_KNOWLEDGE_DOCS)

        self._store = InMemoryVectorStore.from_documents(docs, embeddings)
        return len(docs)

    def search(self, keywords: list[str], threshold: float = 0.45) -> dict:
        if not self._store:
            return self._summary
        seen = set()
        tables = []
        for keyword in keywords:
            results = self._store.similarity_search_with_score(keyword, k=30)
            added = 0
            for doc, score in results:
                t = doc.metadata["table"]
                if t not in seen:
                    if score >= threshold or added == 0:
                        seen.add(t)
                        tables.append(t)
                        added += 1
                    else:
                        break
        return {t: self._summary[t] for t in tables}

    def get_schema(self, tables: list) -> dict:
        return {t: self._detail[t] for t in tables if t in self._detail}

    def get_all(self) -> dict:
        return self._summary


SCHEMA_STORE = SchemaVectorStore()
