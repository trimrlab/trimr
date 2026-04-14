[English](#english) | [中文](#中文)

---

# English

# Trimr

> **Alpha Stage** — This project is under active development. Features may change and bugs may exist. Feedback and issues are welcome.

**AI Agent Cost Control Engine — Optimize tokens, preserve intelligence.**

Trimr is a local connector that sits between your AI Agent and LLM providers, transparently reducing token costs through context compression and request deduplication.

## Features

- **Context Compression** — Summarizes long conversation history to reduce input tokens
- **Request Deduplication** — Caches identical requests to avoid redundant LLM calls
- **Cost Tracking** — Real-time dashboard showing token usage, costs, and savings
- **Multi-Provider Support** — OpenAI, Anthropic, Gemini, DeepSeek, Mistral, Groq, Moonshot, Qwen, and 20+ more
- **Multi-Agent Support** — Compatible with OpenClaw, CodeBuddy, and more
- **Cloud Sync** — Encrypted activity log synchronization
- **Cross-Platform** — macOS, Linux, Windows

## Quick Install

```bash
curl -fsSL https://trimrlab.cloud/install.sh | bash
```

## Manual Install

```bash
git clone https://github.com/trimrlab/trimr.git
cd trimr
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

## Configuration

Edit `.env` to configure:

```env
HOST=0.0.0.0
PORT=8000
DEBUG=False
DATABASE_URL=sqlite:///./trimr.db
CLOUD_API_URL=
```

## How It Works

### Architecture

```
┌──────────────┐         ┌──────────────────────────────────────┐         ┌──────────────┐
│              │         │              Trimr (local)           │         │              │
│   AI Agent   │────────>│                                      │────────>│ LLM Provider │
│  (OpenClaw)  │<────────│  ┌────────┐ ┌────────┐ ┌─────────┐  │<────────│  (Gemini/..) │
│              │         │  │ Dedup  │ │Compress│ │ Tracker │  │         │              │
└──────────────┘         │  └────────┘ └────────┘ └─────────┘  │         └──────────────┘
                         │       │          │           │       │
                         │  ┌────┴──────────┴───────────┴────┐  │
                         │  │         SQLite (local)         │  │
                         │  └────────────────────────────────┘  │
                         │                  │                   │
                         └──────────────────┼───────────────────┘
                                            │ (encrypted)
                                     ┌──────┴──────┐
                                     │ Trimr Cloud │
                                     └─────────────┘
```

### Request Flow

```
Request In ──> Dedup Check ──> Cache Hit? ──Yes──> Return Cached Response
                                   │
                                   No
                                   │
                              Compression ──> ROI Check ──> Not Worth It ──> Skip
                                   │
                                Worth It
                                   │
                          Generate Summary ──> Compress Messages
                                   │
                          Forward to LLM ──> Stream/Normal Response
                                   │
                         Track Usage & Cost ──> Sync to Cloud
```

### Core Modules

| Module | What it does |
|--------|-------------|
| **Dedup Engine** | Hashes request messages to create cache keys. If the same request arrives within TTL (default 3600s), returns the cached response without calling the LLM. Works for both streaming and non-streaming requests. |
| **Compression Engine** | When input tokens exceed a threshold (default 2000), splits messages into system/history/recent window. Sends history to a cheap LLM (e.g. gemini-2.5-flash-lite) to generate a summary, replacing verbose history with a concise recap. Includes ROI pre-check — skips compression if the summary cost would exceed the savings. |
| **Tracker** | Records every request: original tokens, actual tokens, saved tokens, cost, latency, strategies used. Factors in compression LLM cost to show real net savings. |
| **Cloud Sync** | Periodically syncs usage stats and encrypted activity logs to Trimr Cloud. All action logs are encrypted with a user-set password before upload. |
| **Connector** | Trimr Cloud for remote commands (strategy updates, config changes). Manages agent configuration files locally with backup and rollback support. |

## Project Structure

```
app/
├── api/          # HTTP endpoints (proxy, dashboard)
├── core/         # Compression engine, dedup, tracker
├── auth/         # Authentication and encryption
├── db/           # Database models and cloud sync
├── agent/        # Agent configuration and connector
└── utils/        # Logging, i18n, platform detection
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /v1/chat/completions` | OpenAI-compatible proxy |
| `GET /dashboard/stats` | Overall statistics |
| `GET /dashboard/trends` | Daily trends |
| `GET /dashboard/requests` | Request history |
| `GET /health` | Service health check |

## License

MIT

---

# 中文

# Trimr

> **Alpha 阶段** — 本项目正在积极开发中，功能可能会调整，运行中可能存在 Bug。欢迎反馈和提交 Issue。

**AI Agent 成本控制引擎 — 优化 Token，保留智能。**

Trimr 是一个本地连接器，部署在 AI Agent 和 LLM 之间，通过上下文压缩和请求去重，透明地降低 Token 成本。

## 功能

- **上下文压缩** — 对长对话历史生成摘要，减少输入 Token
- **请求去重** — 缓存相同请求的响应，避免重复调用 LLM
- **费用追踪** — 实时面板展示 Token 用量、费用和节省金额
- **多供应商支持** — 支持 OpenAI、Anthropic、Gemini、DeepSeek、Mistral、Groq、Moonshot、通义千问等 20+ 供应商
- **多 Agent 支持** — 兼容 OpenClaw、CodeBuddy 等 AI Agent
- **云端同步** — 加密行为日志同步到云端
- **跨平台** — 支持 macOS、Linux、Windows

## 快速安装

```bash
curl -fsSL https://trimrlab.cloud/install.sh | bash
```

## 手动安装

```bash
git clone https://github.com/trimrlab/trimr.git
cd trimr
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

## 配置

编辑 `.env` 进行配置：

```env
HOST=0.0.0.0
PORT=8000
DEBUG=False
DATABASE_URL=sqlite:///./trimr.db
CLOUD_API_URL=
```

## 工作原理

### 架构

```
┌──────────────┐         ┌──────────────────────────────────────┐         ┌──────────────┐
│              │         │            Trimr（本地）              │         │              │
│   AI Agent   │────────>│                                      │────────>│  LLM 供应商   │
│  (OpenClaw)  │<────────│  ┌────────┐ ┌────────┐ ┌─────────┐  │<────────│  (Gemini/..) │
│              │         │  │  去重  │ │  压缩  │ │  追踪   │  │         │              │
└──────────────┘         │  └────────┘ └────────┘ └─────────┘  │         └──────────────┘
                         │       │          │           │       │
                         │  ┌────┴──────────┴───────────┴────┐  │
                         │  │       SQLite（本地存储）         │  │
                         │  └────────────────────────────────┘  │
                         │                  │                   │
                         └──────────────────┼───────────────────┘
                                            │（加密传输）
                                     ┌──────┴──────┐
                                     │ Trimr Cloud │
                                     └─────────────┘
```

### 请求流程

```
请求进入 ──> 去重检查 ──> 缓存命中？──是──> 直接返回缓存响应
                              │
                              否
                              │
                          压缩判断 ──> ROI 预估 ──> 不划算 ──> 跳过压缩
                              │
                            划算
                              │
                      生成摘要 ──> 压缩消息
                              │
                    转发到 LLM ──> 流式/普通响应
                              │
                   记录用量和费用 ──> 同步到云端
```

### 核心模块

| 模块 | 说明 |
|------|------|
| **去重引擎** | 对请求消息做哈希生成缓存键。相同请求在 TTL（默认 3600 秒）内再次到达时，直接返回缓存响应，不调用 LLM。支持流式和非流式请求。 |
| **压缩引擎** | 当输入 Token 超过阈值（默认 2000）时，将消息拆分为系统消息/历史消息/最近窗口。将历史消息发送给低成本 LLM（如 gemini-2.5-flash-lite）生成摘要，用简洁的回顾替换冗长的历史。包含 ROI 预估——如果摘要成本大于节省，则跳过压缩。 |
| **追踪器** | 记录每次请求：原始 Token、实际 Token、节省 Token、费用、延迟、使用的策略。将压缩 LLM 的成本计入，展示真实的净节省。 |
| **云端同步** | 定期将使用统计和加密的行为日志同步到 Trimr Cloud。所有行为日志在上传前使用用户设置的密码加密。 |
| **连接器** | Trimr Cloud 获取远程指令（策略更新、配置变更）。在本地管理 Agent 配置文件，支持备份和回滚。 |

## 项目结构

```
app/
├── api/          # 接口层（代理、数据面板）
├── core/         # 核心引擎（压缩、去重、追踪）
├── auth/         # 认证和加密
├── db/           # 数据库和云端同步
├── agent/        # Agent 配置和连接器
└── utils/        # 日志、国际化、平台检测
```

## 接口

| 接口 | 说明 |
|------|------|
| `POST /v1/chat/completions` | 兼容 OpenAI 的代理接口 |
| `GET /dashboard/stats` | 总体统计 |
| `GET /dashboard/trends` | 每日趋势 |
| `GET /dashboard/requests` | 请求历史 |
| `GET /health` | 健康检查 |

## 许可

MIT
