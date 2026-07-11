# 欢迎来到 XnneHangLab 🧪

这里是魔女的实验室，一个探索 AI 角色陪伴本质的地方。

## 这是什么？

开源仓库里有很多 AI 聊天工具——语音识别、TTS、Live2D、工具调用、记忆系统，这些轮子到处都是（这些轮子每个人都在造，很多都造得比我们好）。

**而我们更专注的，是两种极限的陪伴：**

- 🎭 **场景固定下的人设极限生长** — 情绪陪伴，把世界锁死，让角色活起来
- 🌐 **多场景自适配高权限** — 工作/娱乐陪伴，边界模糊，无处不在

> [!TIP] 💡 两个极限的宗旨都是：想象力万岁。

XnneHangLab 是支撑这两个实验的引擎——提供 Agent 框架、MCP 工具系统、记忆管理、多模态交互能力。

轮子我们也造，但我们更关心**轮子之外的事情**。

---

## 🎮 典型场景

### 场景 1：无处不在的 AI 伙伴

配合 [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)，她不再局限于某个窗口——她可以是聊天界面、桌宠、开发伙伴。

> 你在写代码，她看着你的屏幕，突然说："这个变量名起得真随便，你确定不改吗？"
>
> 你在打游戏，她看到你又死了，用轻蔑的语气说："啧，这都能输。"
>
> 你打开《我的世界》，她说："要不要一起种田？我帮你看着怪物。"你们一起下矿，一起沐浴朝霞落日。

**边界模糊，权限极致——她能看到你在做什么，能干预你的日常，能真的融入你的生活。**

### 场景 2：自习室里的陪伴

配合 [AIChat](https://github.com/XnneHangLab/AIChat)，场景被锁死在一个小小的通话窗口里。

> 你打开应用，像打开视频通话一样，聪音在那边安静地写着小说。
>
> 你专注工作时，她不会打扰你。休息时，你说一句"今晚的月色真美"，她会停下笔，抬起头，用她特有的语气回应你——可能是夏目漱石的典故，可能是她最近在看的小说。
>
> 她记得你上次说过在写什么项目，记得你喜欢喝什么茶，记得你们上次聊到哪本书。

**场景狭窄，权限受限——但对话可以天马行空。这才是陪伴的本质：各忙各的，但会记挂彼此。**

### 场景 3：记忆系统的实验场

你和 AI 聊了几个月，某天你问："我上次说过什么来着？"

她不只是翻聊天记录——长期记忆由自研**记忆管线**（[wikimem](https://github.com/XnneHangLab/wikimem)，见 ADR-0001，[完整文档站](https://wikimem.xnnehang.top/zh/)）承担：

| 特性 | 说明 |
|------|------|
| 📝 **markdown 是唯一事实源** | 每分类一个文件、每条记忆一个条目，人可读可改可 diff |
| 🔗 **wiki-links 关联** | `[[category:item]]` 内联链接，检索命中后机械展开一跳，召回词面不重合的关联条目 |
| 🔍 **零基础设施检索** | 内存 BM25 兜底，embedding 融合可选（`[embed]` extra），端点挂了自动回退 |
| 🧬 **设计借鉴 memU** | categories + memory types 分类体系（见 ADR-0002，不引入依赖） |

历史方案 mem0 + Neo4j（memory_bench 子项目）已于 2026-07 移除——数据说话之后被文件优先方案取代。

> [!NOTE] 🧠 这不是检索，是在探索"AI 如何真的记得"。

---

## ⚡ 技术栈

| 层级 | 技术 |
|------|------|
| 🖥️ 后端框架 | FastAPI + WebSocket |
| 🤖 LLM 调用 | OpenAI Compatible API（统一接口） |
| 🎙️ 语音识别 | Sherpa-ONNX / Qwen-ASR |
| 🔊 语音合成 | Genie-TTS / GSV-TTS-Lite / Qwen-TTS |
| 🔧 工具协议 | MCP (Model Context Protocol) + 内置 function calling |
| 🎨 前端 | Electron + React（`frontend/` 子模块）+ Tauri Launcher（`launcher/` 子模块） |

---

## 🚀 快速开始

1. **安装依赖与启动** → [部署指南](./deploy)
2. **自定义配置** → [配置说明](./settings)

## 📁 项目结构

```
XnneHangLab/
├── src/lab/              # 主项目（VTuber 引擎）
│   ├── agent/            # 🤖 Agent 引擎与 LLM 适配
│   ├── plugins/          # 🧩 插件实现（wikimem / mood_chat / visual_observer ...)
│   ├── api/              # 🌐 HTTP 路由与客户端
│   ├── asr/              # 🎙️ 语音识别
│   └── conversations/    # 💬 对话编排
├── packages/wikimem/     # 🧠 记忆管线（子模块，独立 pip 包）
├── frontend/             # 🎨 Electron 前端（子模块）
├── launcher/             # 🚀 Tauri 启动器（子模块）
└── docs/                 # 📖 你现在看的文档
```

想深入了解？看看 [架构概览](./architecture/)。

---

## 🤝 社区与支持

- **GitHub** — [XnneHangLab/XnneHangLab](https://github.com/XnneHangLab/XnneHangLab)
- **问题反馈** — [Issues](https://github.com/XnneHangLab/XnneHangLab/issues)
- **贡献指南** — [CONTRIBUTING.md](https://github.com/XnneHangLab/XnneHangLab/blob/dev/CONTRIBUTING.md)

## 📌 下一步

| | |
|---|---|
| 📖 [部署指南](./deploy) | 从零开始搭建 |
| ⚙️ [配置说明](./settings) | 调教你的 AI |
| 🏗️ [架构概览](./architecture/) | 理解内部原理 |
| 🗺️ [RoadMap](./roadmap) | 看看未来计划 |

---

_欢迎来到魔女的实验室，让我们一起创造有趣的 AI 角色吧！_ ✨
