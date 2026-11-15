# TrendRadar 部署说明（jjdufu/trendradar）

基于 [sansan0/TrendRadar](https://github.com/sansan0/TrendRadar) 的 GitHub Actions 部署：每 3 小时抓取国内外热榜，并在同一任务里启动 RSSHub 抓取梗/段子源，合并进一份报告。配置了邮件渠道后会发送 HTML 报告。

邮件结构：先是 AI「本期速览」（国内热点 / 国际热点 / 科技 / 梗与抽象段子，跨平台去重，梗会解释出处和好笑点），后面附精简原始榜单。未配置 AI Key 时仍会发送原始榜单，只是没有速览。

## 调度

- 工作流：`.github/workflows/crawler.yml`（Get Hot News）
- Cron（UTC）：`0 */3 * * *`，整点触发，GitHub 可能延迟几分钟
- 对应 Asia/Shanghai（UTC+8）：每天 02:00、05:00、08:00、11:00、14:00、17:00、20:00、23:00
- 报告模式：`current`（当前榜单）。未配置 S3 时 Actions 无持久盘，`incremental` 无法可靠去重
- 也可在 Actions 页面手动 Run workflow（workflow_dispatch）

上游自带的 7 天签到自动停用已关闭：定时任务不会因为未运行 Check In 而自行停止。仓库里仍保留 Check In 工作流，但已不再需要。

## 邮件 Secrets

在仓库 Settings → Secrets and variables → Actions 中添加（不要写进仓库文件）：

- `EMAIL_FROM`：发件人邮箱
- `EMAIL_PASSWORD`：邮箱授权码（不是登录密码）
- `EMAIL_TO`：收件人邮箱

可选：`EMAIL_SMTP_SERVER` / `EMAIL_SMTP_PORT`（163 邮箱一般可留空，程序会走 smtp.163.com:465）。

## AI 速览 Secrets（可选，配齐后邮件开头才会出现处理后的摘要）

- `AI_API_KEY`：API Key（必填才能启用分析/翻译）
- `AI_MODEL`：LiteLLM 格式 `提供商/模型名`
  - DeepSeek 官方：`deepseek/deepseek-chat` 或 `deepseek/deepseek-v4-flash`
  - OpenAI 官方：`openai/gpt-4o` 或 `openai/gpt-4o-mini`
  - Gemini：`gemini/gemini-2.5-flash`
  - 兼容 OpenAI 的中转/自建：模型写成 `openai/<服务商的模型名>`，并设置 `AI_API_BASE` 为接口根地址，例如 `https://your-provider.com/v1`
- `AI_API_BASE`：自定义 API 地址；官方 DeepSeek / OpenAI / Gemini 通常留空
- 可选：`AI_ANALYSIS_ENABLED=true` 覆盖配置开关（一般不必设，仓库里已打开分析）

本仓库是公开的，请不要把邮箱密码、API Key 或其他密钥提交到代码里。
