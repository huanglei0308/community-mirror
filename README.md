# community-mirror

跨社区开源仓库同步状态中心 — **由各社区自行运行同步，Hub 统一展示状态**。

👉 **[查看同步仪表盘](https://huanglei0308.github.io/community-mirror/)**

---

## 这是什么？

很多开源社区需要把代码从 Gitcode/Gitee 镜像到 GitHub，或反过来。这个项目解决两个问题：

1. **对于有同步需求的社区** — 提供开箱即用的模板，3 步配置好自动同步
2. **对于想了解同步状态的人** — 一个统一的仪表盘，展示所有社区的同步进展

## 谁在用？

<!-- COMMUNITY_TABLE_START -->
| 社区 | 源 | 目的 | 负责人 | 状态 |
|------|-----|------|--------|------|
| openEuler | gitcode/openeuler | github/openeuler-mirror | @huanglei0308 | [查看](https://github.com/openeuler-mirror) |
| My Test (lei0308) | gitcode/lei0308 | github/huanglei0308 | @huanglei0308 | [查看](https://github.com/huanglei0308) |
<!-- COMMUNITY_TABLE_END -->

> 你的社区也在这里？见下方接入指南。

---

## 我要接入同步

→ **[3 步接入指南](docs/setup-guide.md)**

1. 复制 `template/` 到你的仓库
2. 填入你的 src/dst 和 Secrets
3. 向本仓库提 PR 注册你的社区 — 在 `config/orgs.json` 加一行

## 如何工作？

```
各社区仓库 (自己管密钥)
  ├─ hub-mirror-action 同步代码
  ├─ check_sync_status.py 检查结果 → results.json
  └─ 推到自己的 gh-pages (公开 URL)
         │
         ▼
本仓库 gh-pages (纯静态页面, 零 Token)
  ├─ index.html
  └─ app.js ──浏览器里 fetch 所有社区的 results.json ──→ 渲染仪表盘
```

## FAQ

**Q: Hub 需要我的密钥吗？**
不需要。密钥放在你自己的仓库 Secrets 里，Hub 完全不碰。

**Q: 支持哪些平台？**
GitHub、Gitee、Gitcode、GitLab。基于 [Yikun/hub-mirror-action](https://github.com/Yikun/hub-mirror-action)。

**Q: 同步失败了怎么办？**
仪表盘会显示失败仓库列表。检查你的 workflow 日志排查具体原因。常见原因：源端认证过期、仓库过大超时、网络问题。

**Q: 我不用 Gitcode，用 Gitee，可以吗？**
可以。模板中的 `src` 和 `dst` 改成你的平台即可，比如 `src: gitee/my-org`。

## 文件结构

```
community-mirror/
├── README.md               ← 你在这里
├── docs/setup-guide.md     ← 新社区接入教程
├── template/               ← 复制到你仓库就能用
│   └── repo-mirror.yml
├── scripts/                ← 所有社区复用
│   └── check_sync_status.py
├── config/
│   └── orgs.json           ← 社区注册表 (接入时 PR 改这个)
├── public/                 ← gh-pages 仪表盘
│   ├── index.html
│   ├── app.js
│   └── style.css
└── .github/workflows/
    └── deploy-pages.yml
```
