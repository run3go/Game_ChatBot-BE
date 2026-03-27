import os
from langchain_openai import OpenAIEmbeddings
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_core.documents import Document
from sqlalchemy.orm import Session

from sql.schema_builder import SchemaBuilder


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

        docs = [
            Document(
                page_content=f"{table}: {comment}",
                metadata={"table": table},
            )
            for table, comment in self._summary.items()
        ]

        self._store = InMemoryVectorStore.from_documents(docs, embeddings)
        return len(docs)

    def search(self, question: str, k: int = 3) -> dict:
        if not self._store:
            return self._summary
        results = self._store.similarity_search(question, k=k)
        return {
            doc.metadata["table"]: self._summary[doc.metadata["table"]]
            for doc in results
        }

    def get_schema(self, tables: list) -> dict:
        return {t: self._detail[t] for t in tables if t in self._detail}

    def get_all(self) -> dict:
        return self._summary


SCHEMA_STORE = SchemaVectorStore()
