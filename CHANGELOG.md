# CHANGELOG

## v2.0.0（2026-10-30）
### 新增
- Web 管理台（FastAPI + 原生单页，深色主题、移动端自适应）
- 一键发现：UGOS Docker API + 容器终端只读扫描（portMapping / container-scan / env 三源合并）
- 四态同步：new/update/expired/same；过期卡「清理建议」；勾选执行、state 快照回滚
- Sun-Panel 两级配置：OpenAPI token（必填）+ 管理员账号（可选，解锁删除）
- 健康监测：定时探测 + 仪表盘联动（默认 300s）
- 日志按大小轮转 bridge.log（5MB×5）
- 多架构镜像 ghcr（amd64+arm64），裸机 install.sh（venv+systemd）

### 变更
- 卡片客户端按官方 OpenAPI 1.8.1 契约重写（update 以 onlyName 定位）
- M1-2 口径：容器类 14/14 达标；过期/宿主服务单列为产品功能
- M1-4 图标：dashboard-icons → 应用 favicon → 手动，三级回退

### 修复
- CI workflow 顶层 `permissions: packages: write`，登录改 stdin 规避 YAML 键名解析错误
- verify.py 按 setup/config 真实状态机判定 + 不跟随 302；/open 未配置/上游异常统一 502
- internal.list_cards 支持管理员登录后枚举存量卡（否则四态全判 new）

### 验收备注（v2.0.0）
- amd64 功能验收：华为云 venv 裸机全链路 PASS（发现 36、四态预览、/open 302、verify PASS）
- Sun-Panel 同步链路补验 PASS（四态 new24/update13/expired13；3 卡入 v2-测试组、回读正确、回滚 3/0）
- 终态：v2 接管 8770（沿用 v1 口令，27 张卡无缝）；v1 文件保留、服务已 disable
- 测试分组 14（空组）/15（v2-测试）已清理，面板恢复 12 个原有分组

### 已知限制
- **arm64 运行验证：v2.1 补**（NAS SSH 通道受限）
- **ghcr.io 在部分国内云默认网络不可达**（如华为云）；此类环境请用裸机安装或自配镜像源

## v1.x
- 见 main 分支归档（免登录桥接 + 26 卡改写，生产运行）
