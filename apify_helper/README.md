# 短剧数据台（apify_helper）

局域网内给内容运营看 TikTok 短剧公开数据的小站。后端 Flask + SQLite，每天定时抓一次，也可手动刷新。

数据源两种，操作台「设置」里切换（或改 `config.json` 的 `source`）：

| 模式 | `source` | 怎么抓 | 费用 | 前提 |
|---|---|---|---|---|
| Apify 云端 | `apify` | 调 Apify 上的 `rainminer/tiktok-short-drama-scraper`，所有剧一次 run | 约 $2 / 千集 | Apify token |
| 自建直连 | `direct` | 本机直接请求 tiktok.com 网页端的 `/api/drama/detail/` 和 `/api/drama/episode/item_list/` | 免费 | 机器能访问 TikTok；国内网络在设置里填 HTTP 代理 |

自建模式 2026-09-07 实测无需登录、无需签名参数。缺点：拿不到剧封面（用作者头像兜底），依赖 TikTok 网页接口不改；
连续两天失败就切回 Apify。两种模式写同一张表，切换不影响历史数据和日增量。

## 部署（Windows）

1. 机器上装好 Python 3.10+（安装时勾选 Add to PATH）。
2. 把整个 `apify_helper` 目录拷到机器上，双击 `start.bat`。首次会自动装依赖并生成 `config.json`。
3. 浏览器打开 `http://<这台机器的IP>:8765/`，进「操作台」填 Apify token，添加剧 ID。
4. 想开机自启和放行防火墙端口：右键 `install_autostart.bat` → 以管理员身份运行（只需一次）。

改端口 / 定时时间 / 代理：操作台的「设置」，或直接改 `config.json` 后重启。

## 目录

| 文件 | 作用 |
|---|---|
| `app.py` | Flask 路由、后台抓取线程、每日定时 |
| `apify_client.py` | Apify 模式：调 actor、轮询、解析字段 |
| `tiktok_client.py` | 自建模式：直连 TikTok 网页接口、分页、解析 |
| `db.py` | SQLite 表结构、快照写入、所有指标查询 |
| `templates/` `static/` | 页面、样式、Chart.js 本地副本 |
| `tests/test_smoke.py` | Apify 模式全链路：`python tests/test_smoke.py` |
| `tests/test_direct.py` | 自建模式：真实响应夹具解析 + 分页 + run_job：`python tests/test_direct.py` |

## 指标口径

- **日增量**：最新快照 − 上一个自然日的最后一次快照。同一天手动刷多次不影响。
- **末集留存**：末集播放 ÷ 首集播放。
- **付费墙断崖**：最后一集免费的播放 ÷ 第一集付费的播放，越大越劝退。
- **互动率**：(点赞+评论+分享+收藏) ÷ 播放。收藏率单列。
- 首页趋势图取每天每部剧的最后一次快照按分组求和；某天没抓的剧当天不计入。

## 边界

只有公开数据。留存曲线（3 秒、5 秒）、完播、解锁人数、收入在 TikTok Studio / Drama Center 后台，这里没有。
