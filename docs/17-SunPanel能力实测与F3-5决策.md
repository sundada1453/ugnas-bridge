# Sun-Panel OpenAPI 能力实测 + F3-5 实现决策

> 日期：2026-10-30｜实测目标：真实面板 1.8.1（经 AWS → http://100.111.245.21:13002）
> 结论先行：**官方 OpenAPI 没有「卡片列表 / 卡片删除 / 分组修改 / 分组删除」**，F3-5 的 expired 枚举与删除必须走面板内部 API，方案见 §4。

## 1. 官方接口清单（doc.sun-panel.top/zh_cn/openapi/v1，1.8.1）

| 模块 | 接口 | 说明 |
|---|---|---|
| 其他 | POST /openapi/v1/version | 联通测试 |
| 卡片 | POST /openapi/v1/item/create | url 必填 |
| 卡片 | POST /openapi/v1/item/getInfoByOnlyName | onlyName 查询单卡 |
| 卡片 | POST /openapi/v1/item/update | **onlyName 必填**，支持 itemGroupID 移组 |
| 卡片 | POST /openapi/v1/item/batchUpdate | 仅 v2.0.0-dev-13+，本面板无 |
| 分组 | POST /openapi/v1/itemGroup/create | title 必填 |
| 分组 | POST /openapi/v1/itemGroup/getInfo | itemGroupID / onlyName |
| 分组 | POST /openapi/v1/itemGroup/getList | 无参 |

**缺失**：item 列表、item 删除、itemGroup 修改、itemGroup 删除（官方文档无；实测路径均 404/SPA 回落）。

## 2. 实测记录（真实面板）

| 调用 | 结果 |
|---|---|
| POST /openapi/v1/version | code:0, version:1.8.1 ✅ |
| POST /openapi/v1/item/getInfoByOnlyName {"onlyName":"ugnas-5244"} | code:0 返回真实卡片 ✅ |
| POST /openapi/v1/itemGroup/getList | code:0, count 12（初测）✅ |
| POST /openapi/v1/item/update | code:0 路由存在 ✅（按 onlyName 定位） |
| POST /openapi/v1/itemGroup/create | code:0 路由存在 ✅ |
| POST /openapi/v1/item/getList 及多种候选名 | SPA HTML 回落 = 无此路由 ❌ |
| POST itemGroup/delete|del|remove… | SPA HTML 回落 = 无此路由 ❌ |
| POST item/delete|del|remove… | SPA HTML 回落 = 无此路由 ❌ |

## 3. 内部面板 API（源码 v1.8.1 确认，用于补足 OpenAPI 缺口）

| 能力 | 接口 | 鉴权 |
|---|---|---|
| 分组列表 | POST /api/panel/itemIconGroup/getList | **公开模式可读** |
| 分组内卡片 | POST /api/panel/itemIcon/getListByGroupId {itemIconGroupId} | **公开模式可读** |
| 卡片删除 | POST /api/panel/itemIcon/deletes {ids:[...]} | 需登录 |
| 分组删除 | POST /api/panel/itemIconGroup/deletes {ids:[...]} | 需登录 |

## 4. F3-5 落地方案（定稿）

1. **expired 枚举**：用两组「公开模式」内部接口（分组列表 → 分组内卡片）枚举全部既有卡片；失败回退本地 cards 表 / v1 cards_state.json。只读、无需管理员凭据。
2. **移回收站**：itemGroup/create 建「回收站」组 → item/update {onlyName,itemGroupID} 移动。全官方 API，已具备。
3. **删除卡片**：官方 OpenAPI 无删除 → 需管理员登录后调 itemIcon/deletes；作为**可选能力**（默认只给移回收站，配置管理员凭据后才开放删除，删除二次确认）。
4. **回滚**：快照严格沿用 v1 语义 {ts, service_base, changed:{onlyName:{new_url, old_url}}}；回滚按 old_url 还原。

## 5. 需清理的实测副作用（待办）

- 探测 itemGroup/create {} 时面板未校验 title 即创建，产生空标题分组 itemGroupID=14。官方无分组删除接口，需管理员登录后用 itemIconGroup/deletes {ids:[14]} 清理。
- 本次 AWS SSH 两次连接被远端关闭（kex_exchange_identification: Connection closed by remote host），按纪律停止重试，待通道恢复后立即清理并在 docs/14 记录。
