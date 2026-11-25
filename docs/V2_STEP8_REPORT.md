# Network Locator V2 第 8 步报告：设置与高级功能

> 日期：2026-11-25  
> 分支：`v2/step-2-shell`  
> 版本：`1.4.0`（预览服务 `1.4.0-preview`）  
> 预览端口：`4185`  
> 截图目录：`docs/screenshots/step8/`

## 结论

**通过（有条件）**。设置页与高级功能已按 spec 八.8 + 4.7 落地：扫描默认参数、超时、并发、默认网卡、自动扫描策略、数据存储位置、CSV 配置、主题、语言与关于均接入真实后端并持久化；并发与超时实际进入扫描执行；自动扫描由服务进程托管；存储迁移跨重启生效且越界目录被拒绝。中英 × 明暗、1180×720 与 900/760/620 响应式均在最终代码上复测通过。

发布前仍有真机 TOS 全流程回归未执行（按要求不碰 189/190，等待机器窗口）；45 分钟自动扫描的实际墙钟触发未等待，改由调度器状态与 fake-clock 单测覆盖。1.3.8 未提交审核，详见文末。

| 检查项 | 结果 |
| --- | --- |
| 设置保存与重启保留 | 通过（WSL 真实后端：超时 2400、并发 17、CSV `;`、深色、英文，重启后全部保留） |
| 非法值校验 | 通过（超时 99 被前端拦截；目录越界返回 400；中英文提示均正确） |
| 主题切换与持久化 | 通过（PATCH 200；刷新后 `dark`/`dark`；服务端 `theme=dark`） |
| 自动扫描托管 | 通过（`thread_alive=true`；重启后仍为 true；策略变更后重新计时） |
| 默认网卡生效 | 通过（选 `eth0` 后仅选择 `eth0\|10.18.15.0/24`，无回退告警） |
| 超时/并发实际进入扫描 | 通过（`ScanManager` 单测读取持久化参数并传入探测环境） |
| 数据存储迁移 | 通过（复制到 `/tmp/nl-step8/moved/network-locator.db`，指针落盘，重启仍使用新位置；旧库保留） |
| 存储越界拒绝 | 通过（`/tmp/outside-step8` 返回 400，中文错误 `存储目录必须位于应用数据目录 … 内`） |
| CSV 配置生效 | 通过（分号 / 无表头 / 无 BOM；恢复默认后 BOM + 表头 + 逗号，11 行） |
| 中英双语 | 通过（设置页四套；7 个页面英文浅/深扫描均无中文残留、无横向溢出） |
| 明暗主题 | 通过（浅色/深色四套截图与 DOM 属性一致） |
| 响应式 | 通过（1180×720、900、760、620 均无横向溢出） |
| 后端测试 | 通过（105 / 105） |
| 前端测试 | 通过（44 / 44） |
| 语法检查 | 通过（全部前端 `node --check`；后端 `compileall`） |
| 构建 x86_64 / aarch64 | 通过（Verification OK；SHA 见下） |
| 打包契约 | 未改动（app id、包内路径、systemd unit、socket、运行用户、1180×720） |
| 真机 TOS 安装 / 7 页 / 扫描 / 卸载 | **未执行（发布前阻塞，等待机器窗口）** |

## 1. 实现范围

后端：

- `store.py`：设置项严格校验（布尔、数值、主题、语言、网卡、CSV 分隔符），持久化到 SQLite；新增 `storage-location.json` 指针，`relocate_storage()` 使用 SQLite backup 将数据库复制到 `APP_DATA` 内的新目录，旧库保留作回滚；重启时从指针恢复位置，越界指针不跟随。
- `v2_api.py`：`GET/PATCH/POST /v2/settings` 返回 `storage`、`automation`、能力列表；新增 `POST /v2/settings/storage`（扫描进行中返回 409）；新增服务内 `AutoScanScheduler`，策略变更后重新计时并记录运行状态与错误；库存扫描与普通扫描均使用持久化默认网卡。
- `core.py`：`ScanManager.start()` / `_run()` 接受 `default_interface`；网卡不可用时回退全部网段并给出告警，不伪装成功。
- `server.py`：启动时应用持久化扫描参数，启动/停止自动扫描调度线程。

前端：

- 设置页补充默认网卡、自动扫描策略、存储目录与迁移、自动扫描托管状态、主题与语言、关于信息；保存后立即刷新摘要。
- 主题选择写入后端设置，刷新后从服务端与本地一致恢复；语言切换同步服务端 locale。
- `i18n.js` 补齐设置、迁移、自动扫描与校验错误的中英文案；`translateMessage()` 在中文模式保持原文，修复中文界面误显示英文后端错误的回归。
- `preview_server.py` 镜像存储迁移与 automation 字段，预览端口行为与真实后端一致。

测试：

- 新增 8 个后端测试，覆盖存储迁移、越界/已有数据库拒绝、设置校验、默认网卡、真实超时/并发读取、调度器执行与错误记录。

## 2. 实测数据

- 真实后端（WSL Unix socket）：`scan_timeout_ms=2400`、`scan_concurrency=17`、`csv_delimiter=;`、`theme=dark`、`locale=en` 重启后保留；迁移后路径 `/tmp/nl-step8/moved/network-locator.db`，指针 `{"directory": "/tmp/nl-step8/moved"}`。
- 默认网卡扫描：`default_interface=eth0`，`selected_network_ids=["eth0|10.18.15.0/24"]`，`warnings=[]`。
- 调度器：保存 45 分钟策略后 `seconds_until_next=2699`，重启后 `thread_alive=true`、仍为 `2699`。
- 预览设置保存：2500 / 17 / `enp2s0` / 自动 60 分钟 / 分号 / 无表头 / 无 BOM，刷新后字段保留。
- 预览 CSV：自定义配置 10 行、无 BOM、无表头、分号；恢复默认 11 行（表头 + 10 设备）、BOM、逗号。
- 英文设置页存储提示：`Storage root: /var/lib/network-locator. Migration copies device profiles and scan history; the old database is kept as a rollback backup.`
- 英文校验提示：`Probe timeout (ms) must be between 100–30000`。

## 3. 构建

| 架构 | 文件 | 大小 | SHA256 |
| --- | --- | --- | --- |
| x86_64 | `apps/tos7/dist/network-locator_1.4.0_x86_64.deb` | 136344 bytes | `e39eb2a3ed3dd3d55f847ef679c05fbe933421f2c1843edb812b463d491cbed5` |
| aarch64 | `apps/tos7/dist/network-locator_1.4.0_aarch64.deb` | 136344 bytes | `b4a45bd2e8f358848b4767abe22af6bf13d5082d96a0406721a5201f3c544727` |

两次构建均输出 `Verification: OK`。未打 tag、未发 Release、未提交审核。

## 4. 截图

- 四套完整设置页：`docs/screenshots/step8/v8-settings-zh-light-full.png`、`v8-settings-zh-dark-full.png`、`v8-settings-en-light-full.png`、`v8-settings-en-dark-full.png`
- 1180×720：`docs/screenshots/step8/v8-settings-1180x720-zh-light.png`
- 响应式：`v8-settings-responsive-900-zh-light.png`、`v8-settings-responsive-760-zh-light.png`、`v8-settings-responsive-620-zh-light.png`
- 自动扫描开启：`v8-settings-automation-zh-light.png`
- 存储迁移：`v8-settings-storage-zh-light.png`
- 四套 fullPage 对照：`v8-settings-zh-light.png`、`v8-settings-zh-dark.png`、`v8-settings-en-light.png`、`v8-settings-en-dark.png`

## 5. 未完成项与已知问题

1. **真机 TOS 全流程回归未执行**：安装、服务 active、平台入口、7 个页面、真实网络扫描、卸载仍需在 TOS 机器上完成。按要求未触碰 189/190，等待机器窗口。
2. **45 分钟自动扫描未做墙钟等待**：通过调度器状态（`thread_alive`、`seconds_until_next`）和 fake-clock 单测验证策略与执行路径，未实际等待 45 分钟。
3. **存储迁移边界（设计约束）**：只允许 `APP_DATA` 内的绝对路径；目标已有数据库文件会明确拒绝；旧库保留作回滚，不自动删除。
4. **遗留导航控制台错误（非第 8 步引入）**：从设备总览切到“网络扫描”时，`app.js` 遗留 `sidebarWidthBounds()` 访问不存在的 `#sidebarResizer` 会抛一次 `parentElement` 空引用；页面渲染与功能不受影响，本次未改无关代码，留待后续清理。
5. **英文深色 1081px 表格内 4px 滚动条**：之前已记录的外观问题，按要求本次不投入处理。

## 6. 1.3.8 审核状态

- **未提交审核**：当前无使用个人令牌提交审核的证据，本地记录为 `status=0`；本次也未提交审核、未打 Release。
- 版本号：`1.3.8`
- Version ID：x86_64 `b1ed1dfb-be80-4517-9f72-6021c9acd5d4`；aarch64 `9a55f662-b54a-4877-86a3-b4e97c7781c8`

