# rss-pipeline

> 一条零依赖的本地 RSS 采集管线：把订阅源统一拉取、去重、过滤，产出 Markdown 日报 + JSON。

## 它是什么

rss-pipeline 是一个单文件、零第三方依赖的 RSS/Atom 采集脚本。它解决「订阅了很多源，但读不完、留不下、用不上」的问题：

- **拉取**：RSS 2.0 与 Atom 双格式兼容
- **标准化**：统一字段（id / title / link / published / summary / 来源 / 分类）
- **去重**：跨次采集按 `guid → link → title` 记忆已见条目，只放行新内容
- **过滤**：标题黑名单 / 白名单规则
- **产出**：JSON（供二次开发）+ Markdown 日报（Obsidian 兼容，含 frontmatter）

数据留在本机，无云依赖。

## 30 分钟跑通

前置：安装 Python 3（无需任何第三方包）。

1. 复制示例配置为你的配置
   ```powershell
   cp sources.example.json sources.json
   ```
2. 编辑 `sources.json`，替换 / 增删 `feeds` 里的源
3. 试跑（只解析，不落盘）
   ```powershell
   python collect.py --dry
   ```
4. 正式采集
   ```powershell
   python collect.py
   ```
5. 查看 `out/` 目录：`latest.json`（本轮结果）、`YYYY-MM-DD-rss-digest.md`（日报）、`state.json`（去重基线）

## 配置说明

`sources.json` 结构：

| 字段 | 说明 |
|---|---|
| `feeds[].id` | 源唯一标识 |
| `feeds[].name` | 展示名 |
| `feeds[].category` | 分类（日报按此分组） |
| `feeds[].tier` | 层级（可选，仅记录） |
| `feeds[].url` | RSS/Atom 地址 |
| `feeds[].enabled` | 是否启用 |
| `feeds[].filters.title_blacklist` | 标题含任一关键词即丢弃 |
| `feeds[].filters.title_whitelist` | 非空时仅保留命中关键词的条目 |
| `digest.title` | 日报标题（可选） |
| `digest.tags` | 日报 frontmatter 标签（可选） |

## 可选：接入 RSSHub 源

默认示例只用公网源。如需抓取知乎、微博等依赖 [RSSHub](https://docs.rsshub.app/) 的源，参考 `examples/sources.rsshub.example.json`，把条目并入 `sources.json`，并确保本机 RSSHub 已在对应端口运行。

## 测试

```powershell
python -m unittest test_collect -v
```

## 设计原则

- 本地优先：数据留在本机
- 可追溯：每条信息带来源标注
- 产出导向：终点是日报 / 数据，不是「读完」
- 规则保底：核心去重 / 过滤离线可用，不依赖 LLM

## License

[GPL-3.0](./LICENSE)
