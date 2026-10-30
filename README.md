# ugnas-bridge

绿联 NAS（UGOS）容器应用「点开即达」免登录桥接服务，配合 Sun-Panel 导航面板使用。

## 是什么

在 Sun-Panel 导航里点击绿联 NAS 的容器卡片（OpenList / Emby / alist / qBittorrent…），经本服务在点击瞬间完成绿联官方通道的一次性 token 交换，302 直达 `app-<port>-<alias>.<dockerDomain>` 应用首页——**无绿联登录框、无静态地址造假**，电脑/手机/外网全场景可用。

原理等价于开源项目 [BlackHolesYvan/ugport](https://github.com/BlackHolesYvan/ugport)（Android WebView 实现）的纯服务端复刻：

```
浏览器 → GET /open/<port>?k=<KEY> → (持有效 keepalive token)
       → GET /ugreen/v1/docker/app/dockerToken?port=<port>
          x-ugreen-token:        base64(RSA/ECB/PKCS1Padding(token, NAS公钥))
          x-ugreen-security-key: <token_id>
       → data.redirect_url（一次性）
       → GET redirect_url → Set-Cookie: ugreen-proxy-token
       → 302 https://app-<port>-<alias>.<dockerDomain>/  ✅ 免登录直达
```

## 关键协议要点（UGOS 固件 1.21 实测）

- `verify/check` 必须 **POST + JSON**（GET 返回 1005）
- 登录体：`{username, [secret:UGREEN_NAS_PASS]: RSA加密, keepalive, otp:true, is_simple:true, support_force_otp:true}`
- `dockerToken` 缺任一头 → `9405`；明文 token 或 RSA-OAEP → `1010`
- `redirect_url` **一次性**；token 失效码 `1024/1010` 自动重登
- 必须携带客户端头：`Client-Id: <uuid4>-WEB`、`Client-Version: 78578`、`Client-Version-Str: 1.20.0`、`UG-Agent: PC/WEB`、`X-Specify-Language: zh-CN`
- 旧固件接口 `docker/app/dockerToken`（不带双头）在 1.21 恒 9405

## 目录

```
tools/ugreen_client.py   绿联协议客户端（登录/RSA/换token/自动续期，线程安全）
poc/ugnas_bridge.py      单文件 HTTP 桥接服务（纯标准库，/?k= 口令闸 + /open/<port> + /health）
tools/update_cards.py    Sun-Panel OpenAPI 卡片批量改写（1.8.1 无 batchUpdate 自动降级逐条）
deploy/                  systemd unit + install.sh（参数化，--dry-run/--apply/--rollback）
docs/                    需求说明书 / 部署手册 / 卡片改写计划 / 最终验证证据
state/                   卡片改写 state 示例（已脱敏）
```

## 快速部署

```bash
# 目标机（任意可常开的 Linux，有 Python3 即可）
sudo bash deploy/install.sh --host 0.0.0.0 --port 8770
# 服务端环境变量：UGNAS_BRIDGE_{USER,KEY,REFRESH,HEARTBEAT,LOG,BASE,ALIAS}
# 公网部署务必保留 ?k= 口令闸；云主机再放行安全组端口
```

Sun-Panel 卡片：`url = http://<服务地址>:<端口>/open/<端口>?k=<KEY>`，`lanUrl = http://<NAS内网IP>:<端口>`。

## 已知限制

- 应用自身（OpenList/Emby 等）的账号页与绿联通道无关，需各自登录
- redirect_url 一次性，不能把 `app-<port>` 地址直接写进卡片
- Sun-Panel 1.8.x 无 `item/batchUpdate`，脚本自动逐条写入
- 某些机房/运营商网络对非常用端口的明文 HTTP 有干扰（TCP 通、数据包丢），换网络或加 TLS 即可

## 免责

仅用于访问**自己拥有**的绿联 NAS 设备；遵守所在服务商条款，风险自担。
