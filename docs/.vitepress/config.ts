import { defineConfig } from "vitepress";

export default defineConfig({
  title: "XnneHangLab",
  description: "魔女の实验室 - 文档站",
  lang: "zh-CN",

  head: [["link", { rel: "icon", href: "/logo.svg" }]],

  themeConfig: {
    outline: "deep",
    logo: "/logo.svg",
    siteTitle: "XnneHangLab",

    nav: [
      { text: "首页", link: "/" },
      { text: "指南", link: "/guide/intro" },
      { text: "Memory Bench", link: "/memory-bench/" },
      { text: "ADR", link: "/adr/" },
      {
        text: "GitHub",
        link: "https://github.com/XnneHangLab/XnneHangLab",
      },
    ],

    sidebar: {
      "/adr/": [
        {
          text: "架构决策记录",
          items: [
            { text: "ADR 索引", link: "/adr/" },
            { text: "0001 LLM Mode 记忆系统", link: "/adr/0001-llm-mode-memory" },
            { text: "0002 memU：借鉴设计而非引入依赖", link: "/adr/0002-memu-design-not-dependency" },
          ],
        },
      ],

      "/guide/": [
        {
          text: "开始",
          items: [
            { text: "项目介绍", link: "/guide/intro" },
            { text: "部署", link: "/guide/deploy" },
            { text: "配置", link: "/guide/settings" },
            { text: "FastAPI 服务", link: "/guide/fastapi" },
            { text: "翻译引擎", link: "/guide/translate" },
          ],
        },
        {
          text: "架构",
          items: [
            { text: "概览", link: "/guide/architecture/" },
            { text: "Agent", link: "/guide/architecture/agent" },
            { text: "API", link: "/guide/architecture/api" },
            { text: "ASR", link: "/guide/architecture/asr" },
            { text: "Conversations", link: "/guide/architecture/conversations" },
            { text: "Config", link: "/guide/architecture/config" },
            { text: "Memory Agent", link: "/guide/architecture/memory-agent" },
            { text: "工具系统", link: "/guide/architecture/tools" },
            { text: "Plugin 系统", link: "/guide/architecture/plugin-system" },
            { text: "Profile 系统", link: "/guide/architecture/profile-system" },
            { text: "Skill 系统", link: "/guide/architecture/skills" },
            { text: "System Prompt 分层", link: "/guide/architecture/system-prompt-layers" },
          ],
        },
        {
          text: "开发",
          items: [
            { text: "RoadMap", link: "/guide/roadmap" },
            { text: "已知问题", link: "/guide/issue" },
            { text: "分支", link: "/guide/branches" },
            { text: "贡献指南", link: "/guide/contributing" },
            { text: "插件开发指北", link: "/guide/dev/plugin-development" },
          ],
        },
      ],

      "/memory-bench/": [
        {
          text: "总览",
          items: [
            { text: "文档地图", link: "/memory-bench/" },
            { text: "脚本指南", link: "/memory-bench/scripts-guide" },
          ],
        },
        {
          text: "Server 架构",
          items: [
            { text: "设计理念", link: "/memory-bench/server/design" },
            { text: "路由与端点", link: "/memory-bench/server/routes" },
          ],
        },
        {
          text: "Schema",
          items: [
            {
              text: "节点 Schema（离线）",
              link: "/memory-bench/schema/node",
            },
            {
              text: "节点 Schema（实时）",
              link: "/memory-bench/schema/realtime-node",
            },
            {
              text: "边 Schema（离线）",
              link: "/memory-bench/schema/edge",
            },
            {
              text: "边 Schema（实时）",
              link: "/memory-bench/schema/realtime-edge",
            },
            {
              text: "锚点与模板",
              link: "/memory-bench/schema/anchors",
            },
          ],
        },
        {
          text: "Prompt 设计",
          items: [
            { text: "标注提示词", link: "/memory-bench/prompts/annotator" },
            { text: "场景宪法", link: "/memory-bench/prompts/scene-canon" },
            { text: "角色圣典", link: "/memory-bench/prompts/persona-canon" },
            {
              text: "Claim 抽取提示词",
              link: "/memory-bench/prompts/claim-extractor",
            },
          ],
        },
        {
          text: "类型系统",
          items: [
            { text: "Typing 设计", link: "/memory-bench/typing-design" },
          ],
        },
        {
          text: "脚本详情",
          collapsed: true,
          items: [
            {
              text: "annotate_all",
              link: "/memory-bench/scripts/annotate-all",
            },
            {
              text: "bench_logger",
              link: "/memory-bench/scripts/bench-logger",
            },
            {
              text: "build_index",
              link: "/memory-bench/scripts/build-index",
            },
            { text: "chat_cli", link: "/memory-bench/scripts/chat-cli" },
            {
              text: "chat_server",
              link: "/memory-bench/scripts/chat-server",
            },
            {
              text: "claim_extractor",
              link: "/memory-bench/scripts/claim-extractor",
            },
            {
              text: "claimify_all",
              link: "/memory-bench/scripts/claimify-all",
            },
            {
              text: "claims_to_graph",
              link: "/memory-bench/scripts/claims-to-graph",
            },
            {
              text: "compile_events",
              link: "/memory-bench/scripts/compile-events",
            },
            {
              text: "compiled_claims",
              link: "/memory-bench/scripts/compiled-claims",
            },
            {
              text: "export_edge_schema",
              link: "/memory-bench/scripts/export-edge-schema",
            },
            {
              text: "export_node_schema",
              link: "/memory-bench/scripts/export-node-schema",
            },
            {
              text: "graph_to_cypher",
              link: "/memory-bench/scripts/graph-to-cypher",
            },
            {
              text: "graph_writer",
              link: "/memory-bench/scripts/graph-writer",
            },
            {
              text: "latest_file",
              link: "/memory-bench/scripts/latest-file",
            },
            {
              text: "mem0_to_graph",
              link: "/memory-bench/scripts/mem0-to-graph",
            },
            {
              text: "neo4j_apply_cypher",
              link: "/memory-bench/scripts/neo4j-apply-cypher",
            },
            {
              text: "neo4j_clear",
              link: "/memory-bench/scripts/neo4j-clear",
            },
            {
              text: "neo4j_queries",
              link: "/memory-bench/scripts/neo4j-queries",
            },
            {
              text: "rate_limiter",
              link: "/memory-bench/scripts/rate-limiter",
            },
            {
              text: "replay_mem0",
              link: "/memory-bench/scripts/replay-mem0",
            },
            { text: "startup", link: "/memory-bench/scripts/startup" },
            {
              text: "tag_registry",
              link: "/memory-bench/scripts/tag-registry",
            },
          ],
        },
      ],
    },

    socialLinks: [
      {
        icon: "github",
        link: "https://github.com/XnneHangLab/XnneHangLab",
      },
    ],

    search: {
      provider: "local",
    },

    footer: {
      message: "魔女の实验室",
      copyright: "© 2026 XnneHangLab",
    },
  },
});
