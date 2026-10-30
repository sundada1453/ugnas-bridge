# M5 补验 · Sun-Panel 同步链路（华为云 8771）

> 日期：2026-10-31｜前提：华为云到 NAS 13002 恢复
> 结论：同步链路补验 PASS，「同步待 NAS 侧补验」已销账

## 1. 配置与连通
- Sun-Panel `http://100.111.245.21:13002`，OpenAPI token 加密落盘
- 管理员账号加密落盘（存量卡枚举/删除）
- `test_sunpanel = True`

## 2. 真实四态预览
`new 24 / update 13 / expired 13 / same 0`

## 3. 同步 apply（只进 v2-测试 分组）
- 分组「v2-测试」= itemGroupID 15
- 选 3 张代表卡（ugnas-1053/2080/2443）：apply ok 3 / fail 0
- 快照 `state/snapshots/cards_state_20261031_060324.json`
- 回读：3 张均 itemGroupID=15，url=`http://1.94.204.44:8771/open/<port>?k=…`
- v1 的 ugreen-nas 分组与 26 张现役卡未动

## 4. 快照回滚演练
rollback ok 3 / fail 0

## 5. 最终 verify
PASS health 200 / 无口令 401 / 带口令 302 → RESULT: PASS

## 6. 事故与纠正（主动报备）
- 首次 systemd unit 端口误写 8770，与 v1 冲突导致 v1 短暂停止（约 2 分钟）
- 已修为 8771 并重启 v1：v1 /health = 200，26 卡未动
- v2 口令从误用的 v1 KEY 轮换为独立随机 32 位

## 7. v2.1 挂账（剩两项）
- arm64 运行验证（NAS SSH 通道受限）
- 14 号空组清理（同为 NAS SSH 通道）
