# 3 步接入同步

## 前置条件

- 一个 GitHub 仓库，用于存放 workflow 配置文件
- 源平台和目标平台的账号及权限
- SSH 密钥对（公钥配在目标平台，私钥作为 Secret）

### 准备 Secrets

在你的 GitHub 仓库 **Settings → Secrets and variables → Actions** 中添加：

| Secret 名称 | 内容 | 说明 |
|-------------|------|------|
| `SRC_TOKEN` | 源平台 API Token | 用于获取仓库列表（Gitcode/Gitee 需要） |
| `DST_TOKEN` | 目标平台 API Token | 用于在目标平台创建仓库 |
| `DST_PRIVATE_KEY` | SSH 私钥 | 对应公钥需配置在目标平台上 |

---

## Step 1: 复制模板

从本仓库的 `template/repo-mirror.yml` 复制到你自己的仓库：

```
your-repo/
└── .github/workflows/
    └── repo-mirror.yml    ← 复制到这里
```

---

## Step 2: 修改配置

编辑 `repo-mirror.yml`，替换以下内容：

```yaml
# 改这里 ↓
src: gitcode/MY_ORG          # 你的源，如 gitcode/openeuler
dst: github/MY_ORG_MIRROR     # 你的目的，如 github/openeuler-mirror
account_type: org             # org / user / group

# 可选：黑/白名单
# black_list: "huge-repo1,huge-repo2"   # 这些仓库不参与同步
# static_list: "only-this-repo"         # 只同步指定仓库

# 可选：大仓库超时
# timeout: '1h'

# 目标为 Gitee/GitHub 且分支保护阻止 force push 时，
# 可在 mirror_repos.py 参数中追加 --clear-branch-rules
# 注意：GitHub secret scanning push protection 不是分支保护，不能靠此参数绕过。
```

如果你想同步到 GitHub 以外的平台，修改 `src`/`dst` 前缀：
- GitHub: `github/org-name`
- Gitee: `gitee/org-name`
- Gitcode: `gitcode/org-name`
- GitLab: `gitlab/group-name`

---

## Step 3: 注册你的社区

向本仓库（`huanglei0308/community-mirror`）提一个 PR，在 `config/orgs.json` 中添加你的社区信息（注意 `main` 替换为你的默认分支名）：

```json
{
  "org": "你的社区名",
  "owner": "GitHub 组织或用户名",
  "contact": "负责人 GitHub 账号",
  "source": "gitcode/my-org",
  "destination": "github/my-org-mirror",
  "results_url": "https://raw.githubusercontent.com/YOUR_ORG/YOUR_REPO/main/results.json"
}
```

PR 合并后，你的社区就会出现在 [统一仪表盘](https://huanglei0308.github.io/community-mirror/) 上。

---

## 验证

1. 手动触发你的 `repo-mirror` workflow
2. 确认 workflow 跑完后 `https://raw.githubusercontent.com/<your-org>/<your-repo>/main/results.json` 可访问
3. 打开 [仪表盘](https://huanglei0308.github.io/community-mirror/) 确认你的社区已出现

---

## 常见问题

### Q: 我的仓库是私有的，results.json 不想公开怎么办？

目前仪表盘通过 raw.githubusercontent.com 读取各社区仓库中的 results.json。如果你的同步目标是公开仓库，results.json 只包含仓库名和计数，不包含源码，公开通常没有安全风险。

### Q: 我想自定义同步频率？

修改 `repo-mirror.yml` 里的 `schedule` cron 表达式。默认是每天 01:00 UTC。

### Q: 源和目标仓库名不一样？

使用 `mappings` 参数。例如 `mappings: "old-name=>new-name"`。
