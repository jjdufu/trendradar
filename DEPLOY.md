# TrendRadar 部署说明（jjdufu/trendradar）

基于 [sansan0/TrendRadar](https://github.com/sansan0/TrendRadar) 的 GitHub Actions 部署：每 3 小时抓取国内外热榜，并在同一任务里启动 RSSHub 抓取梗/段子源，合并进一份报告。配置了邮件渠道后会发送 HTML 报告。

邮件使用自适应 Tab 速览模板（宽 100%、最大 680px 居中，15px/1.5 行高）：顶部两行锚点胶囊可跳转到各栏（QQ 邮箱以跳转+全部叠放为主），先是「每天60秒读懂世界」，再按栏展示 GitHub 每日热门（含今日星标与中文一行）、X 平台热点、抽象段子、TikTok 热点、百度、国内、国际、时政、AI 圈动态、科技。60 秒摘要与各栏一行说明由同一次 AI 调用生成。未生成速览时各栏仍尽量展示原文标题。网页版 HTML 报告不变。

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

## 当前 AI 方案：xAI Grok（SuperGrok 订阅 OAuth，无 API Key）

- Secrets：`XAI_REFRESH_TOKEN`（OAuth refresh token）、`XAI_CACHE_PASSPHRASE`（加密缓存口令）。不要设置 `AI_API_KEY`。
- 每次运行前，工作流用 refresh token 向 `https://auth.x.ai/oauth2/token` 换取 6 小时有效的 access token，并导出 `AI_API_KEY` / `AI_API_BASE=https://api.x.ai/v1` / `AI_MODEL=openai/grok-4.20-0309-non-reasoning`。
- 轮换后的新 refresh token 用 openssl（aes-256-cbc + pbkdf2）加密后存进 actions/cache（key `xai-rt-<run_id>-<attempt>`，恢复前缀 `xai-rt-`）。顺序：先用缓存里的 token，失败再用 Secret。
- 全部刷新失败时只打 warning，照常发送不带速览的原始榜单。
- 缓存 7 天未访问会被 GitHub 清除；每 3 小时一次的运行会持续刷新它。若缓存与 Secret 都失效，需要重新登录并更新 `XAI_REFRESH_TOKEN`。

## X/Twitter 源

- Secret：`TWITTER_AUTH_TOKEN`（X 网页登录后的 `auth_token` cookie）。只注入 RSSHub 服务容器，不要写进仓库或打印到日志。
- 路由：`/twitter/user/<handle>`（见 https://docs.rsshub.app/routes/twitter）。包含已核实的梗/搞笑号（PicturesFoIder、HumansNoContext、nocontextmemes、historyinmemes、WholesomeMeme、vidsthatgohard、9GAG、NoContextBrits、Dexerto、TheBabylonBee、aiyutoushushu、xiaosangawa）以及 PopCrave、Elon Musk 与主要 AI 人物/公司账号。已去掉低频或不活跃的 @dril、@TheOnion、@dog_rates，以及此前空源的 @pixelatedboat、@xai。每源最多 5 条、排除转推，RSS 请求间隔 5 秒，配合 3 小时一次的定时，降低对账号的限流风险。

## TikTok 海外热点

- 来源：TikTok Creative Center 公开接口 `POST https://ads.tiktok.com/CreativeOne/KnowledgeAPI/GetHashtagList`（无需登录）。匿名请求每个国家最多返回 3 条标签，因此默认查询 US/GB/CA/AU/DE/FR/JP/KR/BR/MX 并按标签去重，写入独立展示区「TikTok 海外热点」。
- 旧版 `creative_radar_api` 已 deprecated / 匿名 40101；RSSHub 仅有需反爬的用户主页路由、没有可用的标签/热榜路由；newsnow 无 tiktok 源。视频榜 `CreativeCenterGetTopContentsList` 在未登录时大约只能拿到 4 条且偏带货，故未采用。
- 配置见 `tiktok_trends`；抓取失败只打日志并跳过该栏，不影响其余邮件。GitHub Actions 若被 TikTok 拒绝数据中心 IP，该栏可能为空。
