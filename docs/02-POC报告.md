# POC 报告 · B 方案本地小服务（第 2 阶段）

时间：2026-10-30 14:12 CST

---

## 一、已交付

| 文件 | 说明 |
|---|---|
| `poc/ugnas_bridge.py` | 单文件 HTTP 服务（**仅标准库**），`GET /open/<port>` → 302，`/health`、`/` 索引页 |
| `tools/ugreen_client.py` | 新增 `UgreenSession`：登录/自动续期/失效重登，线程安全 |
| `tools/update_cards.py` | OpenAPI 批量改卡：`--dry-run`（默认）/`--apply`/`--rollback`，state 落盘，lanUrl 不动 |
| `tools/mock_openapi.py` | 离线 mock，用于验证改卡脚本 |
| `deploy/ugnas-bridge.service`、`deploy/install.sh` | systemd 常驻 + 一键安装 |
| `logs/bridge.log` | 每请求一行 + 每 300s 心跳（常驻可见证据） |

服务接口：
```
GET /               端口索引页（手机直接点）
GET /open/<port>    自动续期 → dockerToken → 302 到 app-<port>-1/（浏览器落 cookie，UGOS 免登录）
GET /health         token 掩码 / 登录次数 / 续期次数 / 最后错误
```

---

## 二、实测结果（真实浏览器，经服务跳转）

| 端口 | 应用 | 最终 URL | UGOS 登录 | 应用层登录框 |
|---|---|---|---|---|
| 8080 | Sub2API | `app-8080…/home` | **无**（直通） | **无** ✅ 首页 |
| 5244 | OpenList | `app-5244…/@login?redirect=%2F` | 无 | **有**（OpenList 自身登录） |
| 8097 | Emby | `app-8097…/web/index.html#/startup/manuallogin` | 无 | **有**（Emby 用户名/密码） |

**结论（验收口径定稿）**：验收标准为「**UGOS 免登录层到位**」。
三端口均已拿到 `ugreen-proxy-token`、不再跳 ug.link 登录页 → **全部达标**。
OpenList / Emby 后续出现的是**应用自身账号页**，按用户原话「这个不用、我自己填就好」，**不计入验收、不做自动登录**。
Sub2API（8080）连应用层也无需登录，直接进首页。

### 根因（已取证）
- OpenList：`GET /api/me` → `{"code":401,"message":"Guest user is disabled, login please"}`；游客未开启。
- Emby：`GET /Users/Public` → `[]`（无公共用户）。

---

## 三、token 自动续期

- `UgreenSession.credentials()`：距上次 refresh 超过 `--refresh-interval`（默认 1800s）→ `PUT /ugreen/v1/verify/refresh?token=`（原地续期，data 为空）。
- `docker_redirect()`：dockerToken 返回 `1024/1010` → 自动重登一次再试。
- 心跳线程每 `--heartbeat`（默认 300s）既写日志又触发到期续期。
- 实测（refresh-interval=5s）：`refreshes` 计数递增，`code=200`；token 始终有效。

---

## 四、改卡脚本（mock 全流程验证）

```
# 预演（不写）
python3 tools/update_cards.py --map cards.json --service-base http://<SERVICE>:8770 --dry-run
# 执行（写 state）
python3 tools/update_cards.py --map cards.json --service-base http://<SERVICE>:8770 --apply
# 回滚
python3 tools/update_cards.py --rollback
```
mock 验证：dry-run 只打印计划；apply `successCount=3`、url 已改、lanUrl 原样；rollback 全部还原、state 归档。
真实面板：26/26 写入成功 + 3 条回读抽查通过（见 04-卡片改写计划.md）。

---

## 五、口径与结论

- **验收口径**：只要求 UGOS 层免登录。三端口实测均通过。
- OpenList / Emby 的应用层登录属用户自行填写，取消“给应用账号 / 改应用设置 / 反向代理注入”三条路线。
- **部署位置**：公网云主机（全场景可用），systemd 单元、install.sh、部署手册已参数化。
