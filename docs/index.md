# 乐问学术搜索 API

Lewen — 学术论文搜索 RESTful API，支持语义检索、标题匹配、论文详情与引用关系查询。

---

## 核心能力

| 功能 | 端点 | 说明 |
|------|------|------|
| **语义搜索** | `GET /paper/search` | 稀疏 / 稠密 / 混合检索 |
| **标题检索** | `GET /paper/search/title` | 基于标题相似度匹配 |
| **论文详情** | `GET /paper/{paper_id}` | 支持 SHA / arXiv ID / Corpus ID / URL |
| **引用列表** | `GET /paper/{paper_id}/citations` | 引用该论文的论文 |
| **参考文献** | `GET /paper/{paper_id}/references` | 该论文引用的论文 |

## 快速开始

### 发起一次搜索

```bash
curl "http://210.45.70.162:4000/paper/search?query=transformer%20attention&limit=5"
```

```python
import requests

r = requests.get("http://210.45.70.162:4000/paper/search", params={
    "query": "transformer attention",
    "limit": 5,
})
print(r.json())
```

### 查询单篇论文

```bash
curl "http://210.45.70.162:4000/paper/2309.06180?fields=*"
```

## 技术栈

| 组件 | 选型 | 说明 |
|------|------|------|
| Web 框架 | FastAPI + uvicorn | 异步 HTTP |
| 关系数据 | SQLite (WAL) | 论文元数据、引用关系、ID 映射 |
| 全文检索 | SQLite FTS5 | BM25 排序 |
| 向量检索 | Qdrant | 高性能向量数据库 |
| Embedding | BGE-M3 (1024 维) | title + abstract 编码 |
| 混合排序 | RRF | 融合 FTS5 + Qdrant 结果 |

## 数据规模

| 数据 | 规模 |
|------|------|
| 论文元数据 | ~300 万（仅 arXiv + abstract） |
| 引用关系 | ~3000 万条边 |
| 向量索引 | ~300 万 (Qdrant) |

---

!!! tip "下一步"
    - 查看 [API 使用文档](api-zh.md) 了解完整的接口说明
    - 查看 [技术架构](architecture.md) 了解系统设计细节
