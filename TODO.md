# TODO: 社区镜像方案优化

## 1. 新社区接入简化 — Issue 表单自动注册

**现状：** 新社区接入需要 fork → 编辑 `config/orgs.json` → 提 PR → 等合并。

**目标：** 社区只需开一个 Issue，workflow 自动校验并写入 `orgs.json`。

**方案：**
- 新增 `.github/ISSUE_TEMPLATE/register-community.yml` — Issue 表单模板（org/owner/contact/source/destination/results_url）
- 新增 `.github/workflows/auto-register.yml` — 监听 Issue → 校验 results_url 可访问 → 写入 orgs.json → 关闭 Issue
- 校验失败则评论说明原因 + 打 `invalid` 标签，不关闭 Issue
- PR 路径保留作为备选

---

## 2. 每个社区独立状态页

**目标：** 给每个社区一个专属链接，业务方打开只看到自己社区的同步情况，不用在总览页里翻找。

**方案：**

- 在 `public/` 下新增 `community.html`，通过 URL 参数 `?org=社区名` 展示单个社区
- 链接格式：`https://huanglei0308.github.io/community-mirror/community.html?org=openEuler`
- 页面内容：
  - 社区名 + 源→目的流向
  - 统计卡片（总数 / 成功 / 失败 / 跳过）+ 进度条
  - 失败仓库列表（含错误分类，业务方最关心的信息）
  - 已同步仓库列表（可折叠）
  - 最后更新时间 + 数据状态（是否过期）
  - "返回总览" 链接
- 总览仪表盘每个社区卡片增加 "查看详情" 按钮，链接到独立页
- `orgs.json` 中可选增加 `detail_url` 字段

**实现：** 纯静态页面，和现有 `index.html` + `app.js` 同模式，复用 `config/orgs.json` 和 fetch 逻辑。用小模型生成一个干净的独立页。
