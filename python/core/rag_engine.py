"""
RAG 知识库引擎 — 基于 ChromaDB 的向量检索引擎。

功能：
1. 从 Markdown 文档构建向量索引
2. 语义检索最相关的知识片段
3. 支持多知识库（营地信息、五力框架等）

JD 对应：JD 加分项「RAG/知识库构建，做过数据沉淀类产品」

若无 chromadb 则自动回退到关键词匹配。
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    HAS_CHROMADB = True
except ImportError:
    HAS_CHROMADB = False
    logger.info("chromadb not installed, RAG engine will use keyword fallback")


class DocumentChunk:
    """知识库文档片段。"""

    def __init__(self, text: str, source: str, chunk_id: str,
                 metadata: dict | None = None) -> None:
        self.text = text
        self.source = source
        self.chunk_id = chunk_id
        self.metadata = metadata or {}


class RAGEngine:
    """RAG 检索引擎，包装 ChromaDB 作为向量存储。"""

    def __init__(
        self,
        knowledge_dir: str = "data/knowledge",
        persist_dir: str = "data/chroma",
        embedding_model: str = "text-embedding-3-small",
    ) -> None:
        self._knowledge_dir = Path(knowledge_dir)
        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._embedding_model = embedding_model
        self._chunks: list[DocumentChunk] = []

        self._client = None
        self._collection = None

        if HAS_CHROMADB:
            self._client = chromadb.PersistentClient(
                path=str(self._persist_dir),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            self._collection = self._client.get_or_create_collection(
                name="langyou_knowledge",
                metadata={"description": "青少年营地教育知识库"},
            )

    def build_index(self, force_rebuild: bool = False) -> int:
        """从 Markdown 文件构建/更新向量索引。返回新增 chunk 数。"""
        if not self._knowledge_dir.exists():
            logger.warning("Knowledge directory not found: %s", self._knowledge_dir)
            return 0

        md_files = list(self._knowledge_dir.glob("**/*.md"))
        new_chunks: list[DocumentChunk] = []

        for md_file in md_files:
            chunks = self._split_markdown(md_file)
            for chunk in chunks:
                if not force_rebuild and self._collection:
                    existing = self._collection.get(ids=[chunk.chunk_id])
                    if existing["ids"]:
                        continue
                new_chunks.append(chunk)
                self._chunks.append(chunk)

        # 批量写入 ChromaDB
        if self._collection and new_chunks:
            batch_size = 20
            for i in range(0, len(new_chunks), batch_size):
                batch = new_chunks[i: i + batch_size]
                self._collection.add(
                    ids=[c.chunk_id for c in batch],
                    documents=[c.text for c in batch],
                    metadatas=[{"source": c.source, **c.metadata} for c in batch],
                )

        logger.info("RAG index built: %d new chunks from %d files",
                     len(new_chunks), len(md_files))
        return len(new_chunks)

    def _split_markdown(self, filepath: Path) -> list[DocumentChunk]:
        """按标题切分 Markdown 文档为片段。"""
        text = filepath.read_text(encoding="utf-8")
        source = str(filepath.relative_to(self._knowledge_dir))

        sections = re.split(r"\n(?=## )", text)
        chunks: list[DocumentChunk] = []

        for i, section in enumerate(sections):
            section = section.strip()
            if not section or len(section) < 10:
                continue

            title_match = re.match(r"^#+\s*(.+)", section)
            title = title_match.group(1) if title_match else ""

            chunk_id = hashlib.md5(f"{source}:{i}:{section[:50]}".encode()).hexdigest()
            chunks.append(DocumentChunk(
                text=section,
                source=source,
                chunk_id=chunk_id,
                metadata={"title": title, "section_index": i},
            ))

        return chunks

    async def search(self, query: str, top_k: int = 5) -> list[DocumentChunk]:
        """语义检索最相关的知识片段。"""
        if self._collection and HAS_CHROMADB:
            try:
                results = self._collection.query(
                    query_texts=[query],
                    n_results=min(top_k, len(self._chunks) or 1),
                )
                return self._results_to_chunks(results)
            except Exception as e:
                logger.warning("ChromaDB query failed, falling back to keyword: %s", e)

        return self._keyword_search(query, top_k)

    def search_sync(self, query: str, top_k: int = 5) -> list[DocumentChunk]:
        """同步版搜索（兼容非 async 场景）。"""
        return self._keyword_search(query, top_k)

    def _results_to_chunks(self, results: dict) -> list[DocumentChunk]:
        """将 ChromaDB 查询结果转为 DocumentChunk 列表。"""
        chunks = []
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]

        for i in range(len(ids)):
            chunks.append(DocumentChunk(
                text=docs[i] if i < len(docs) else "",
                source=metas[i].get("source", "") if i < len(metas) else "",
                chunk_id=ids[i],
                metadata=metas[i] if i < len(metas) else {},
            ))
        return chunks

    def _keyword_search(self, query: str, top_k: int) -> list[DocumentChunk]:
        """关键词匹配回退方案。"""
        keywords = set(query.lower().split())
        scored = []

        for chunk in self._chunks:
            text_lower = chunk.text.lower()
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [chunk for _, chunk in scored[:top_k]]

    def get_context(self, query: str, top_k: int = 3) -> str:
        """将检索结果拼接为上下文字符串，用于注入 LLM Prompt。"""
        chunks = self.search_sync(query, top_k)
        if not chunks:
            return ""

        lines = ["# 相关知识库内容\n"]
        for i, chunk in enumerate(chunks):
            lines.append(f"## 来源: {chunk.source}")
            lines.append(chunk.text)
            lines.append("")
        return "\n".join(lines)
