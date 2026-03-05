# 增量更新指南

本文档说明如何基于 [S2 Datasets API - Incremental Updates](https://api.semanticscholar.org/api-docs/datasets#tag/Incremental-Updates) 对 PaperData 进行增量更新。

---

## 1. 增量更新原理

- **全量数据**：每次 release 包含完整快照，体积大。
- **增量 diff**：只包含相邻两次 release 之间的变更（`update_files` 新增/更新，`delete_files` 删除）。
- **Release 周期**：通常每周一次（如 2026-01-27 → 2026-02-03 → 2026-02-10）。

### S2 API 端点

```
GET /diffs/{start_release_id}/to/{end_release_id}/{dataset_name}
```

- `start_release_id`：你当前持有的 release（如 `2026-01-27`）
- `end_release_id`：目标 release，或 `latest`
- `dataset_name`：`papers` | `authors` | `citations` | `abstracts` | `paper-ids`

### 返回结构

```json
{
  "dataset": "papers",
  "start_release": "2026-01-27",
  "end_release": "2026-02-24",
  "diffs": [
    {
      "from_release": "2026-01-27",
      "to_release": "2026-02-03",
      "update_files": ["https://..."],
      "delete_files": ["https://..."]
    },
    ...
  ]
}
```

- `update_files`：需按主键 upsert 的记录（JSONL）
- `delete_files`：需按主键删除的记录（JSONL）

---

## 2. 主键说明

| 数据集      | 主键字段     |
|-------------|--------------|
| papers      | `corpusid`   |
| abstracts   | `corpusid`   |
| paper-ids   | `corpusid`   |
| authors     | `authorid`   |
| citations   | `citationid` |

---

## 3. 下载增量 diff（按 PaperData 形式保存）

### 使用脚本

```bash
# 在项目根目录执行
python build_corpus/data/download_incremental_diffs.py
```

脚本默认参数（可在 `if __name__ == "__main__"` 中修改）：

- `START = "2026-01-27"`：你当前的全量 release
- `END = "2026-02-27"`：目标日期（会解析为最近可用 release，如 2026-02-24）

### 输出目录结构

```
PaperData/
  incremental/
    2026-01-27_to_2026-02-24/
      papers/
        updates/   # 来自 update_files
        deletes/   # 来自 delete_files
      authors/
        updates/
        deletes/
      citations/
        updates/
        deletes/
      abstracts/
        updates/
        deletes/
      paper-ids/
        updates/
        deletes/
```

每个 `updates/`、`deletes/` 下的文件为 JSONL（或 .gz），格式与 PaperData 全量一致。

---

## 4. 合并到现有 PaperData

增量 diff 只是“变更集”，要得到完整 PaperData，需要：

1. 加载现有 PaperData（或从全量 release 下载）
2. 对每个 diff：
   - 遍历 `update_files`，按主键 upsert
   - 遍历 `delete_files`，按主键 delete
3. 将合并结果写回 PaperData 目录（保持原有分区结构）

示例逻辑（伪代码）：

```python
# papers 示例
for diff in diffs["diffs"]:
    for url in diff["update_files"]:
        for line in requests.get(url).iter_lines():
            record = json.loads(line)
            datastore.upsert(record["corpusid"], record)
    for url in diff["delete_files"]:
        for line in requests.get(url).iter_lines():
            record = json.loads(line)
            datastore.delete(record["corpusid"])
```

若使用 SQLite / Qdrant 等存储，可先加载全量，再按上述方式应用 diff。

---

## 5. 场景示例：2026-01-27 → 2026-02-27

1. **列出可用 release**

   ```python
   import requests
   r = requests.get("https://api.semanticscholar.org/datasets/v1/release/").json()
   # 2026-01-27 到 2026-02-27 之间：2026-02-03, 2026-02-10, 2026-02-17, 2026-02-24
   ```

2. **获取增量 diff**

   ```bash
   python build_corpus/data/download_incremental_diffs.py
   ```

3. **合并到 PaperData**

   - 使用 `build_corpus/data/download_incremental_diffs.py` 下载的 `updates/`、`deletes/`
   - 按主键对现有 PaperData 做 upsert 和 delete
   - 或先导入到数据库，再导出为 PaperData 格式

---

## 6. 相关脚本

| 脚本                               | 作用                         |
|------------------------------------|------------------------------|
| `build_corpus/data/download_incremental_diffs.py` | 下载增量 diff 到 PaperData 目录 |
| `demo.py`                          | 下载全量 release 的 URL 列表 |
| `build_corpus/ingest_citations.py`       | 将引用数据导入 SQLite        |

---

## 7. 注意事项

- 需要配置 `S2_API_KEY`（`.env` 或环境变量）以访问 Datasets API。
- diff 的 `update_files`、`delete_files` 为预签名 URL，有时效，建议下载后本地保存。
- 合并时需保证主键一致（如 `corpusid`、`citationid`、`authorid`）。
