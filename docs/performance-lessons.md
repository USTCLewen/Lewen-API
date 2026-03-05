# 性能调优踩坑记录

> 记录乐问学术搜索 API 在压力测试中暴露的性能问题、排查过程和最终方案。

---

## 问题背景

数据规模：266 万篇论文，15GB SQLite 数据库，4 个 uvicorn worker 进程。

使用 10 并发、每端点 200 请求的压力测试时，观察到两类严重问题：

1. **部分请求超时（30s 504）**：citations 端点 8/200 失败，p99 延迟达 30s
2. **一次压测后服务完全卡死**：第二次压测卡在第一个请求上，必须重启才能恢复

---

## 坑 1：FTS5 Batcher 单线程串行成为瓶颈

### 症状

- 所有涉及 FTS5 搜索的请求（sparse、hybrid、title）在高并发下延迟飙升
- QPS 只有 10 左右，远低于预期

### 原架构

```
请求线程 A ──┐
请求线程 B ──┤──→ Queue ──→ [单个 Batcher 线程] ──→ SQLite FTS5
请求线程 C ──┘        串行处理，每次一个 batch
```

`FTS5SearchBatcher` 使用一个后台线程从队列中取请求，批量执行 FTS5 查询。设计初衷是减少 SQLite 连接开销。

### 问题本质

FTS5 不像 GPU 推理那样需要 batch 来摊薄开销。单线程串行反而把 **并发能力降为 1**。10 个并发请求全部排队等待一个线程处理，吞吐量被严重限制。

### 修复

废弃 `FTS5SearchBatcher` 的后台线程设计，改为连接池 + 直接并发查询：

```
请求线程 A ──→ [连接池: conn 1] ──→ SQLite FTS5
请求线程 B ──→ [连接池: conn 2] ──→ SQLite FTS5   （并发执行）
请求线程 C ──→ [连接池: conn 3] ──→ SQLite FTS5
```

### 教训

> **只有当操作本身需要 batch 才能高效时（如 GPU 推理），才应该用 batcher 模式。对于 SQLite 这类支持多读者并发的系统，串行化反而是反优化。**

---

## 坑 2：done.wait() 无超时导致线程池永久耗尽

### 症状

- 第一次压测完成后，服务对所有新请求无响应
- 必须重启服务才能恢复
- 从日志看 batcher 线程 **是活着的**（`batcher_alive: true`），但不再处理任何请求

### 根因

Batcher 的 `search()` 方法使用 `done.wait()` **无超时等待**：

```python
# 有问题的代码
def search(self, query, ...):
    done = threading.Event()
    self._queue.put(request)
    done.wait()  # ← 永远阻塞，没有 timeout
    return result
```

当 `asyncio.wait_for(future, timeout=30)` 超时后，asyncio 取消了 Future，但**底层线程无法被取消**。线程仍然卡在 `done.wait()` 上，永远不会释放回线程池。

```
时间线：
t=0s    请求提交到线程池，线程执行 batcher.search() → done.wait()
t=30s   asyncio timeout，向客户端返回 504
        但线程仍然在 done.wait()，永远不释放
t=∞     线程池 100 个线程逐渐被耗尽 → 服务卡死
```

### 修复

给 `done.wait()` 加上超时：

```python
completed = done.wait(timeout=25.0)
if not completed:
    return []  # 超时返回空结果，释放线程
```

### 教训

> **在线程池中执行的阻塞操作必须有超时机制。`asyncio.wait_for` 的 timeout 只能取消 Future，无法杀死底层线程。线程内部必须自己实现超时保护。**

---

## 坑 3：SQLite WAL Checkpoint 阻塞读操作 14 秒

### 症状

从日志中看到 FTS5 batch 处理时间出现极端值：

```
正常: batch_ms=247ms, 354ms
异常: batch_ms=14043ms, 14003ms, 14035ms  ← 14秒！
```

### 根因

SQLite WAL 模式下，自动 checkpoint（`wal_autocheckpoint` 默认 1000 页）会将 WAL 文件合并回主数据库。这个过程需要 **exclusive lock**，会阻塞所有读操作。

对于 15GB 的数据库，一次 checkpoint 可能持续数十秒。

### 修复

```python
conn.execute("PRAGMA wal_autocheckpoint = 0")  # 禁止自动 checkpoint
```

我们的数据库是**离线构建、在线只读**的，不需要 checkpoint。自动 checkpoint 在这个场景下纯属有害。

### 教训

> **WAL 模式不等于"读写不冲突"。checkpoint 操作仍然会阻塞读者。对于只读数据库，应当禁用自动 checkpoint。**

---

## 坑 4：每次请求新建 SQLite 连接开销大

### 症状

即使没有 WAL checkpoint，单个 FTS5 查询也需要 100-200ms（对于应该几十 ms 完成的查询来说偏慢）。

### 根因

原代码每次查询都 `sqlite3.connect()` 新建连接：

```python
def fts5_search(query, top_k):
    conn = sqlite3.connect(uri, uri=True)  # ← 每次都重新打开 15GB 文件
    conn.execute("PRAGMA cache_size = ...")
    conn.execute("PRAGMA mmap_size = ...")
    try:
        # 查询
    finally:
        conn.close()  # ← 用完就关，缓存丢失
```

SQLite 连接初始化（打开文件、读取 schema、设置 mmap）对大文件有不可忽略的开销。而且每次关闭连接都丢失了内存中的 page cache。

### 修复

创建全局连接池，预开 32 个连接，复用而非每次新建：

```python
class _ConnectionPool:
    def connection(self):
        conn = self._pool.get()  # 复用已有连接
        yield conn
        self._pool.put(conn)     # 归还，不关闭
```

连接初始化时统一设置所有 PRAGMA（cache_size、mmap_size、busy_timeout、wal_autocheckpoint=0）。

### 教训

> **对于大型 SQLite 数据库，连接创建和关闭不是免费的。高并发场景下必须使用连接池。`check_same_thread=False` 允许跨线程复用连接。**

---

## 坑 5：Qdrant client.search_batch 不存在

### 症状

日志中出现大量错误：

```
'QdrantClient' object has no attribute 'search_batch'
```

### 根因

`DenseSearchBatcher` 在 batch_size > 1 时调用 `client.search_batch()`，但安装的 qdrant-client 版本不支持这个方法。虽然 exception handler 捕获了错误并返回空结果，但这意味着**所有多请求 batch 的向量搜索都返回空**，结果质量受损。

### 修复

直接移除 `search_batch` 调用，`vector_search_batch()` 改为循环调用单次 `vector_search()`：

```python
def vector_search_batch(query_vectors, top_k=100):
    return [vector_search(vec, top_k=top_k) for vec in query_vectors] if query_vectors else []
```

### 教训

> **依赖第三方 API 时要做兼容性检查和 fallback。沉默吞掉异常（catch + return empty）是非常危险的——功能看似正常但结果是错的。**

---

## 修复前后对比

### 修复前

```
Total:    3000
Success:  2968 (98.9%)
QPS:      10.7
Latency:  p50=0.165s  p95=0.589s  p99=30.003s

一次压测后服务卡死，必须重启
```

### 修复后

```
Total:    3000
Success:  3000 (100.0%)
QPS:      50.8
Latency:  p50=0.214s  p95=0.401s  p99=0.501s

多次压测连续运行，服务稳定
```

| 指标 | 修复前 | 修复后 | 变化 |
|------|--------|--------|------|
| 成功率 | 98.9% | **100%** | 消除超时 |
| QPS | 10.7 | **50.8** | **4.7x** |
| p99 延迟 | 30.003s | **0.501s** | **60x** |
| 连续压测 | 卡死 | **稳定** | 根治 |

---

## 关键改动清单

| 文件 | 改动 | 解决的坑 |
|------|------|----------|
| `core/db_pool.py`（新） | 32 连接只读连接池 | 坑 3、4 |
| `core/retrieve/sparse.py` | 用连接池替代新建连接 | 坑 4 |
| `core/retrieve/fts5_search_batcher.py` | 直接并发查询，去掉后台线程 | 坑 1 |
| `core/citation/lookup.py` | 用连接池替代新建连接 | 坑 4 |
| `core/citation/database.py` | 读操作用连接池 | 坑 4 |
| `core/paper_id_resolver.py` | 用连接池替代新建连接 | 坑 4 |
| `core/retrieve/dense.py` | `vector_search_batch` fallback | 坑 5 |
| `core/retrieve/dense_search_batcher.py` | `done.wait(timeout=25)` | 坑 2 |

---

## 通用总结

1. **Batcher 不是万能的**：只有 GPU 推理等 batch 能提升吞吐的场景才需要。数据库查询应该直接并发。
2. **线程池 + 无超时阻塞 = 定时炸弹**：asyncio 的 timeout 不能杀线程，线程内部必须自保。
3. **SQLite WAL ≠ 无锁读**：checkpoint 会阻塞，只读场景要关掉 `wal_autocheckpoint`。
4. **连接池是高并发的基础设施**：对大型数据库，每次新建连接的开销足以拖垮 QPS。
5. **异常处理不能沉默吞掉**：catch + return empty 让 bug 变成了"功能降级"，更难发现。
