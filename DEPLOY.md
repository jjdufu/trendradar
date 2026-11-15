# TrendRadar 部署说明（jjdufu/trendradar）

基于 [sansan0/TrendRadar](https://github.com/sansan0/TrendRadar) 的 GitHub Actions 部署：每 3 小时抓取国内外热榜，并在同一任务里启动 RSSHub 抓取梗/段子源，合并进一份报告。配置了邮件渠道后会发送 HTML 报告。

## 调度

- 工作流：`.github/workflows/crawler.yml`（Get Hot News）
- Cron（UTC）：`0 */3 * * *`，整点触发，GitHub 可能延迟几分钟
- 对应 Asia/Shanghai（UTC+8）：每天 02:00、05:00、08:00、11:00、14:00、17:00、20:00、23:00
- 报告模式：`current`（当前榜单）。未配置 S3 时 Actions 无持久盘，`incremental` 无法可靠去重
- 也可在 Actions 页面手动 Run workflow（workflow_dispatch）

上游自带 7 天签到：请定期在 Actions 里运行 **Check In**，否则 Get Hot News 会被自动禁用。

## 还需要你配置的 Secrets

在仓库 Settings → Secrets and variables → Actions 中添加（不要写进仓库文件）：

- `EMAIL_FROM`：发件人邮箱
- `EMAIL_PASSWORD`：邮箱授权码（不是登录密码）
- `EMAIL_TO`：收件人邮箱

可选：按需再加 SMTP（`EMAIL_SMTP_SERVER` / `EMAIL_SMTP_PORT`），或 AI 分析（`AI_API_KEY` / `AI_MODEL`）。

本仓库是公开的，请不要把邮箱密码或其他密钥提交到代码里。
