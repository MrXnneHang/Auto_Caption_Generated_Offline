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
            { text: "0001 记忆管线（曾用名 LLM Mode）", link: "/adr/0001-llm-mode-memory" },
            { text: "0002 memU：借鉴设计而非引入依赖", link: "/adr/0002-memu-design-not-dependency" },
            { text: "0003 memU 双面集成（CLI 先行）", link: "/adr/0003-memu-cli-integration" },
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
            { text: "memU 记忆（sidecar，实验）", link: "/guide/architecture/memu-memory" },
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
