# CHANGELOG

## v2.0.0（2026-10-31）
### 新增
- Web 管理台（FastAPI + 原生单页，深色主题、移动端自适应）：登录/配置向导/仪表盘/应用清单/四态同步/设置
- 一键发现：UGOS Docker API + 容器终端只读扫描（portMapping / container-scan / env 三源合并）
- 四态同步：new/update/expired/same；过期卡「清理建议」；勾选执行、state 快照回滚（沿用 v1 语义）
- Sun-Panel 两级配置：OpenAPI token（必填）+ 管理员账号（可选，解锁删除）
- 健康监测：定时探测 + 仪表盘联动（默认 300s）
- 日志按大小轮转 `bridge.log`（5MB×5）
- 多架构镜像 ghcr（amd64+arm64），裸机 install.sh（venv+systemd）

### 变更
- 卡片客户端按官方 OpenAPI 1.8.1 契约重写（update 以 onlyName 定位）
- M1-2 口径：容器类 14/14 达标；过期/宿主服务单列为产品功能
- M1-4 图标：dashboard-icons → 应用 favicon → 手动，三级回退

### 修复
- CI workflow 顶层 `permissions: packages: write`，登录改 stdin 规避 YAML 键名解析错误
- **QA 回归修复（2026-10-31）**：
  - P0-1 批量删除恒失败：delete 改走 `PanelInternal.delete_items_by_names()`（按 onlyName 定位 id、批量 deletes）
  - P0-2 管理员登录态不持久化：`login()` 保存 `data.token` 并注入后续请求头
  - P0-3 四态预览使用本地旧快照：`_load_cards()` 返回数据源元信息；apply 强制面板实时枚举，失败 409 拒绝
  - P1-1~P1-5：失败明细展示、测试连接合并已存凭据、保存配置字段级合并、健康探测改 `health.host` + TCP 探测、应用清单卡片视图/筛选
  - P2-1/2/3/5/6：移除管理员、全选、端口校验去重、中文登录提示、回滚还原标题/分组/重建删除卡
  - 详见 `docs/21-QA修复记录.md`；单测 14 passed + 本地 mock 面板端到端 PASS
  - **QA 复测修复（2026-10-31 第二轮）**：P1-6 同步成功提示保留（loadPreview keepMsg）；P2-7 `/api/health` 的 health 状态按有效探测地址判断；P2-8 同步页/设置页明示空 onlyName 卡片数量；单测 16 passed，详见 `docs/24-QA复测修复-20261031.md`

### 验收备注（v2.0.0）
- amd64 功能验收：华为云 venv 裸机 8771 全链路 PASS（发现 36、四态预览、/open 302、verify PASS）
- Sun-Panel 同步链路补验 PASS（四态 new24/update2/expired14/same11 实时面板；3 卡同步/回滚演练）
- QA 3 P0 真实面板复验 PASS（见 docs/22）；QA 复测 13/14 项关闭、P1-6 已复修（见 docs/24）

### 已知限制
- **arm64 运行验证：v2.1 补**（NAS SSH 通道受限）
- **ghcr.io 在部分国内云默认网络不可达**（如华为云）；此类环境请用裸机安装或自配镜像源
- **面板若未开启公开访问，需配置管理员账号**才能枚举卡片做四态预览（不配则仅本地快照且禁止 apply）

## v1.x
- 见 main 分支归档（免登录桥接 + 26 卡改写，生产运行）
