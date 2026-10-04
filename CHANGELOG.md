# CHANGELOG

本文件按版本记录面向用户的变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [0.1.0] - 2026-09-13

### 新增
- RSS 2.0 / Atom 双格式采集、标准化、去重、规则过滤、Markdown 日报生成。
- 源配置两层抽离（`sources.example.json` 示例层 / `sources.json` 用户层）。
- `--dry`（只解析不落盘）与 `--out-dir`（自定义输出目录）参数。
- 20 项回归测试。
- README 快速开始指南。
