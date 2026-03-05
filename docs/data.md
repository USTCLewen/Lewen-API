# 数据集结构说明

本文档描述 PaperData（S2 2026-01-27 版本）的数据结构，以及 `papers.json` 与各表的关系。

---

## 1. PaperData 目录结构

| 目录 | 文件数量 | 格式 | 规模 | 说明 |
|------|----------|------|------|------|
| **paper-ids** | 30 | `.gz` | ~3 亿 | 全量 paper 的 corpus_id ↔ sha 映射 |
| **abstracts** | 30 | `.gz` | ~3–4 千万 | 有 abstract 的 paper，含 corpus_id |
| **citations** | 359 | `.gz` | - | 引用关系 |
| **authors** | 30 | `.gz` | - | 作者信息 |
| **papers** | 60 | `.gz` | - | 论文元数据，含 externalids（ArXiv 等） |

**说明**：abstracts 已含 corpus_id，可单独定义「有 abstract」的 corpus；paper-ids 主要用于 corpus_id → sha 解析，构建时只需为 abstracts 中的 corpus_id 做解析。有 ArXiv ID 的 paper（abstracts 与 papers 的交集）约 300 万。

所有文件均为 **JSON Lines (JSONL)**，每行一条 JSON 记录，经 gzip 压缩。

---

## 2. 各表结构

### 2.1 paper-ids（论文 ID 映射）

```json
{
  "sha": "af1b1c80730c83390340c39db88aa93997662c2a",
  "corpusid": 99745734,
  "primary": true
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `sha` | string | 论文的 SHA 哈希（对应 API 的 paperId） |
| `corpusid` | int | S2 Corpus ID |
| `primary` | bool | 是否为该论文的主版本 |

---

### 2.2 papers（论文元数据）

```json
{
  "corpusid": 9139823,
  "externalids": {"MAG": "...", "PubMed": "...", "DOI": "...", ...},
  "url": "https://www.semanticscholar.org/paper/...",
  "title": "Interpersonal issues in prescribing medication.",
  "authors": [{"authorId": "38540751", "name": "M. París"}],
  "venue": "Archives of General Psychiatry",
  "publicationvenueid": "...",
  "year": 1982,
  "referencecount": 0,
  "citationcount": 0,
  "influentialcitationcount": 0,
  "isopenaccess": false,
  "s2fieldsofstudy": [{"category": "Medicine", "source": "s2-fos-model"}, ...],
  "publicationtypes": ["LettersAndComments"],
  "publicationdate": "1982-02-01",
  "journal": {"name": "...", "pages": "...", "volume": "..."}
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `corpusid` | int | 论文 Corpus ID |
| `externalids` | object | 外部 ID（MAG、PubMed、DOI、ArXiv 等） |
| `title` | string | 标题 |
| `authors` | array | 作者列表，含 `authorId` 和 `name` |
| `venue` | string | 发表场所（会议/期刊名） |
| `year` | int | 发表年份 |
| `referencecount` | int | 参考文献数量 |
| `citationcount` | int | 被引次数 |
| `s2fieldsofstudy` | array/null | 研究领域 |
| `publicationtypes` | array/null | 出版类型 |
| `publicationdate` | string/null | 发表日期 |
| `journal` | object/null | 期刊信息 |

---

### 2.3 abstracts（摘要）

```json
{
  "corpusid": 265224679,
  "openaccessinfo": {
    "disclaimer": "...",
    "externalids": {"Medline": "...", "DOI": "...", "PubMedCentral": "...", ...},
    "license": "CCBY",
    "url": null,
    "status": "GOLD"
  },
  "abstract": "Introduction Understanding speech in a noisy environment..."
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `corpusid` | int | 论文 Corpus ID |
| `openaccessinfo` | object | 开放获取信息（来源、DOI、许可证等） |
| `abstract` | string | 摘要正文 |

---

### 2.4 citations（引用关系）

```json
{
  "citationid": 2407430849,
  "citingcorpusid": 147294757,
  "citedcorpusid": 1138704,
  "isinfluential": false,
  "contexts": ["...引用上下文文本..."],
  "intents": [["background"], null]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `citationid` | int | 引用记录 ID |
| `citingcorpusid` | int | 引用方论文的 Corpus ID |
| `citedcorpusid` | int | 被引用论文的 Corpus ID |
| `isinfluential` | bool | 是否为高影响力引用 |
| `contexts` | array/null | 引用上下文文本列表 |
| `intents` | array/null | 引用意图（如 background、methodology 等） |

---

### 2.5 authors（作者）

```json
{
  "authorid": "2174269421",
  "externalids": {"DBLP": ["Wanying Guo"], "ORCID": null},
  "url": "https://www.semanticscholar.org/author/2174269421",
  "name": "Wanying Guo",
  "aliases": null,
  "affiliations": null,
  "homepage": null,
  "papercount": 16,
  "citationcount": 129,
  "hindex": 5
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `authorid` | string | 作者 ID |
| `externalids` | object | 外部 ID（DBLP、ORCID 等） |
| `name` | string | 作者姓名 |
| `aliases` | array/null | 别名 |
| `papercount` | int | 论文数量 |
| `citationcount` | int | 被引次数 |
| `hindex` | int | h 指数 |

---

## 3. papers.json 与各表的关系

### 3.1 数据来源说明

当前项目中的 `build_corpus/data/papers.json` 由 **S2 API** 生成（早期 `crawl_papers.py` 调用 `/paper/search`），并非直接从 PaperData 转换而来。

但从数据模型角度看，papers.json 的字段等价于以下三张表的合并结果。

### 3.2 三表合并构成 papers.json

| 表 | 贡献的字段 |
|----|------------|
| **paper-ids** | `sha` → papers.json 的 `paperId` |
| **papers** | `title`, `authors`, `venue`, `year`, `referencecount`, `citationcount`, `s2fieldsofstudy`, `publicationtypes`, `publicationdate`, `externalids`, `journal` 等 |
| **abstracts** | `abstract`, `openaccessinfo`（对应 `openAccessPdf`） |

三张表通过 **`corpusid`** 关联，合并后得到完整的论文对象。

### 3.3 独立的两张表

| 表 | 作用 |
|----|------|
| **citations** | 引用关系：`citingcorpusid` → `citedcorpusid`，与论文元数据分开存储 |
| **authors** | 作者档案：`authorid`, `name`, `papercount`, `citationcount`, `hindex` 等，是作者维度的补充信息 |

- **papers** 表内已有 `authors: [{authorId, name}]`，表示每篇论文的作者列表
- **authors** 表是作者维度的扩展信息，需要时通过 `authorId` 关联

### 3.4 结构示意

```
papers.json  ≈  paper-ids ⋈ papers ⋈ abstracts   (on corpusid)
                      │
citations  ───────────┼── 独立表，通过 corpusid 关联
                      │
authors  ─────────────┴── 独立表，通过 papers.authors[].authorId 关联
```

### 3.5 Corpus 约束与规模

本项目仅构建以下约束下的 corpus：

| 约束 | 说明 | 规模 |
|------|------|------|
| 有 abstract | 仅 abstracts 中的论文 | ~3–4 千万 |
| 仅 arXiv | 仅 papers 中有 ArXiv ID 的论文 | ~300 万 |
| 引用关系 | 仅 citing、cited 均在 arXiv 的边；`cited_corpus_id IS NULL` 不插入 | ~3000 万（按每篇 ~10 条估算） |

---

## 4. 字段映射（PaperData → papers.json）

| papers.json 字段 | PaperData 来源 |
|------------------|----------------|
| `paperId` | paper-ids.sha |
| `externalIds.CorpusId` | papers.corpusid / paper-ids.corpusid |
| `title` | papers.title |
| `abstract` | abstracts.abstract |
| `authors` | papers.authors |
| `venue` | papers.venue |
| `year` | papers.year |
| `referenceCount` | papers.referencecount |
| `citationCount` | papers.citationcount |
| `fieldsOfStudy` | papers.s2fieldsofstudy |
| `publicationTypes` | papers.publicationtypes |
| `publicationDate` | papers.publicationdate |
| `openAccessPdf` | abstracts.openaccessinfo |

---

## 5. 读取示例

```python
import gzip
import json

# 读取 citations 示例
with gzip.open("PaperData/citations/0.gz", "rt", encoding="utf-8") as f:
    for i, line in enumerate(f):
        if i >= 3:
            break
        record = json.loads(line)
        print(record["citingcorpusid"], "->", record["citedcorpusid"])
```

---

## 6. 相关脚本

| 脚本 | 作用 |
|------|------|
| `build_corpus/ingest_paper_metadata.py` | 从 PaperData 加载论文元数据，构建 SQLite |
| `build_corpus/ingest_citations.py` | 将引用数据导入 SQLite 引用库 |
| `build_corpus/encode_embeddings.py` | 编码论文向量并保存到 npz |
| `build_corpus/load_embeddings_to_qdrant.py` | 从 npz 加载向量写入 Qdrant |
