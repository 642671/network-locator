# Network Locator V2 第 5 步报告：重构网络扫描

> 日期：2026-11-25  
> 分支：`v2/step-2-shell`（第 3/4 步提交 `3c2eae7`、`47094fa`；第 5 步提交在本分支）  
> 版本：`1.4.0`  
> 预览端口：`4180`（常规样例）、`4181`（`--bulk 10000`）、`4182`（慢速扫描，暂停截图）、`4183`（`--no-match`，空结果）  
> 截图：`docs/screenshots/step5/`（17 张）

## 结论

**通过（有条件）**。网络扫描已按 V2 规范重做：真实接口/网段识别、多网段与自定义 CIDR、后台任务、进度/暂停/恢复/停止、实时结果、去重、失败不伪装成功、50 条分页与完整 CSV 均已落地并本地验证。真机 TOS 回归未执行，仍是发布前阻塞项。

| 检查项 | 结果 |
| --- | --- |
| 自动识别接口 / 本机 IP / 掩码 / 网段 | 通过（真实 `eth0 10.18.15.119/24`、`eth3 192.168.2.185/24`） |
| 多网段选择、全选 / 全不选 | 通过 |
| 任意私有 CIDR / 起止范围自定义 | 通过（真实 `/29` 自定义扫描 6 主机） |
| 进度、暂停、恢复、停止 | 通过（真实扫描暂停 64 主机、停止 128 主机） |
| 实时结果与停止保留结果 | 通过（停止后保留 38 条） |
| 任务不依赖页面生命周期 | 通过（后台线程 + 状态轮询） |
| 重复扫描去重 | 通过（87 台设备 = 87 个唯一 MAC，0 重复 IP/MAC） |
| 手动名称 / 备注 / 收藏不被扫描覆盖 | 通过（真实重扫后保留） |
| 扫描失败不伪装成功 | 通过（不可用网段 → `error`；超时/无权限单测） |
| 并发扫描返回 409 | 通过 |
| 每页 50 条 + 10,009 条结果分页 | 通过（`Page 1 · 1–50 / 10009`） |
| CSV 完整导出 | 通过（10,009 条结果 → 表头 + 10,009 行） |
| 中文 / 英文 × 明 / 暗 | 通过（静态与动态文案 0 缺失） |
| 响应式 1180 / 900 / 760 / 620 | 通过 |
| 旧“我的设备”保存 MAC 能力 | 通过（迁入 MAC 定位页，沿用 `networkLocator.savedMacs.v1`） |
| 构建 x86_64 / aarch64 | 通过（SHA 见下） |
| 真机 TOS 安装 / 扫描 / 卸载回归 | **未执行（发布前阻塞项）** |

## 1. 实现范围

后端：

- `ScanManager.start(..., scan_all=False)`：网络扫描与 MAC 后缀扫描共用状态机；新增 `kind`（`mac` / `network`）。
- 网络扫描返回本机接口记录 + 该网段全部邻居；MAC 扫描仍只返回后缀匹配项。
- 新路由：`GET /v2/networks`、`POST /v2/scan/start`、`GET /v2/scan/status`、
  `POST /v2/scan/{pause,resume,stop}`；启动返回 `kind`，能力表新增 `network-scan`。
- `scan_hosts` 返回 `ping_available=False` 时写入告警“仅来自邻居表”，不伪造在线结果。
- `store.record_scan_task`：只有 `kind in {inventory, network}`、完成且非自定义扫描时，
  才把未发现设备标记为离线。
- 扫描失败（超时、权限、网段不可用）任务状态为 `error`，不写成 `completed`。

前端：

- Discovery 页整体 V2 化：网络范围卡片、全选/全不选、自定义范围与 chip、
  当前任务卡片、0–100% 进度、探测主机数、当前接口/网段、错误横幅、
  5 列实时结果表、50 条分页、CSV 导出。
- 轮询 350/700/1800ms；暂停/恢复/停止即时反馈；扫描完成后广播
  `networklocator:scan-finished`。
- 自定义范围持久化键：`networkLocator.v2.discoveryRanges.v1`。
- MAC 定位页新增“已保存的 MAC”卡片：保留旧版“我的设备”的后缀 + 备注，
  支持新增、删除、用于查询；用户输入原文保持不变。

## 2. 自检中发现并修复的问题

1. **`matches_request` 归一化异常**：`scan_all=False` 且后缀为空时抛
   `ValueError`，导致状态匹配崩溃；改为先判断 `scan_all`，再安全归一化。
2. **停止扫描丢失已发现结果**：只在整段扫完后收集邻居，单网段中途停止会得到
   0 条；改为按进度节流实时收集，并在 `ScanCancelled` 时强制回填当前网段。
   真实扫描验证：暂停 64 主机 20 条结果，停止 128 主机 38 条结果。
3. **网段复选框一直禁用**：初次加载完成只恢复控件、未重绘列表，导致无法改选网段；
   在加载结束时重绘网络列表。
4. **顶栏状态一直“正在连接服务”**：V2 shell 只拉取版本、未更新 `backendBadge`；
   健康检查成功后显示“服务在线 / Service online”，失败显示“服务不可用”。
5. **旧“我的设备”能力消失**：把保存 MAC 列表迁入 MAC 定位页，继续读写原有
   `localStorage` 键，不丢用户数据。

## 3. 真实扫描证据（WSL 真实后端）

环境：`APP_DATA=/tmp/nl-real`，`APP_SOCKET_PATH=/tmp/nl-real.sock`，真实接口
`eth3 192.168.2.185/24`（网关 `192.168.2.1`）。

| 场景 | 结果 |
| --- | --- |
| 真实网段扫描 `192.168.2.0/24` | 254 / 254 主机，首次 77 条结果 |
| 重复扫描 | 87 台档案、87 个唯一 MAC、0 重复 MAC/IP；增长来自新进入邻居表的设备 |
| 暂停 | `paused=true`，64 主机时已有 20 条实时结果 |
| 恢复 + 停止 | 恢复后停止于 128 主机，状态 `stopped`，保留 38 条结果 |
| 自定义 `192.168.2.0/29` | 6 主机（网络/广播地址除外），3 条结果 |
| 不可用网段 | 状态 `error`，错误“所选网段当前不可用，请刷新网段后重试” |
| 并发启动 | 第一次 `202`，第二次 `409`“另一个扫描任务正在进行中” |
| 手动字段保护 | PATCH `E2E 测试设备 / 人工备注保留 / 收藏` 后重扫，字段保持不变 |

## 4. 测试与构建

```bash
python3 -m unittest discover -s apps/tos7/backend/tests -p 'test_*.py'   # 86 / 86
node --test apps/tos7/tests/*.test.js                                  # 40 / 40
node --check frontend/{app,csv,i18n,v2-data,v2-shell,v2-pages}.js      # 通过
python3 -m compileall -q backend tools                                 # 通过
python3 build.py --platform x86_64                                     # Verification: OK
python3 build.py --platform aarch64                                    # Verification: OK
```

产物：

- `apps/tos7/dist/network-locator_1.4.0_x86_64.deb`
  SHA256 `ae0f039f06b1c88198642f1ea379499c4384b00e6e1886deb4b1f4b5201dd927`
- `apps/tos7/dist/network-locator_1.4.0_aarch64.deb`
  SHA256 `8a7f9d777f0f41ecd082d3a26ba1ac60b9ecdaec8beeb35bb500572d5e3c9a54`
- x86_64 连续构建两次 SHA 一致。

新增/调整测试：

- 新增 `test_scan_manager_scan_all_single_group_stop_keeps_live_results`
  （单网段中途停止仍保留实时结果）。
- 新增 `test_saved_mac_legacy_carryover_contract`（旧保存 MAC 迁移到 MAC 定位页）。
- **契约测试更新说明**：第 5 步移除了旧单页 Discovery 标记，原
  `test_saved_devices_contract` / `test_ui_contract` /
  `test_default_window_layout_contract` 中针对旧 DOM 的断言改为断言 V2 真实
  界面（导航 7 页、Discovery/Inventory、抽屉、分页、i18n、CSV）。打包契约
  （app id、unit、socket、用户、包内路径、1180×720、`build.py`）未放宽。

## 5. 截图

目录 `docs/screenshots/step5/`：

- 空闲：`zh-light-idle.png`、`zh-dark-idle.png`、`en-light-idle.png`、`en-dark-idle.png`
- 选择与自定义：`zh-light-selected-custom.png`
- 运行 / 暂停：`zh-light-running.png`、`zh-light-paused.png`
- 完成结果：`zh-light-results.png`、`en-dark-results.png`
- 分页：`en-dark-results-page1.png`、`en-dark-results-page2.png`
- 空态：`zh-light-empty.png`
- 响应式：`zh-light-900.png`、`zh-light-760.png`、`zh-light-620.png`
- 保存 MAC：`zh-light-saved-macs.png`、`en-dark-saved-macs.png`

说明：`en-dark-results-page2.png` 显示 `Page 2 · 51–100 / 10009`；预览中的
`10.99.0.0/16` 与批量设备均为 `sample: true` 的合成数据，生产路径不使用。

## 6. 打包契约

未改动：App ID / package `network-locator`、systemd unit
`networklocator-system`、socket `/var/api/network-locator.sock`、运行用户
`network-locator`、包内路径、默认窗口 1180×720、`build.py` 打包规则。
`dpkg-deb -f` 复核：`Package: network-locator`、`Version: 1.4.0`、
`Depends: python3 (>= 3.10), systemd`；包内 `webui.bz2`、`config.ini`、
`init.d/networklocator-system.service`、`data/`、`logs/` 均在原路径。

## 7. 未完成项 / 已知边界

1. **真机 TOS 回归未执行（发布前阻塞）**：需在 TOS 7 真机安装 Deb、确认服务
   active、从 TOS 入口打开、走完 7 页、扫描真实网段、暂停/恢复/停止、卸载。
   按主人要求未触碰审核设备 189/190，等待机器窗口。
2. 错误横幅截图未单独产出：错误路径已由真实“不可用网段”与超时/权限单测覆盖，
   预览服务器没有可注入的扫描失败开关。
3. 预览的自定义范围会以示例网段代替真实探测，并在界面明确提示
   “预览模式：自定义范围由示例网段代替，未执行真实扫描”；生产后端按真实 CIDR 扫描。
4. 1081px 英文深色下设备表仍有约 4px 内部横向滚动（上阶段已知），按要求本轮不处理。
5. 本阶段未打 Release、未提交审核、未收到 1.3.8 审核结果。

## 附：1.3.8 平台状态（只读复核）

1.3.8 已使用个人令牌提交审核，当前均 `status=0`（审核中）：

| 架构 | App ID | 版本 | Version ID | 提交时间 |
| --- | --- | --- | --- | --- |
| x86_64 | `f5d5fede-c204-45fa-8132-fb007cf55d23` | 1.3.8 | `b1ed1dfb-be80-4517-9f72-6021c9acd5d4` | 2026-11-25 11:13:55 +08:00 |
| aarch64 | `dc579d95-1f9e-424e-8595-20f109c0336d` | 1.3.8 | `9a55f662-b54a-4877-86a3-b4e97c7781c8` | 2026-11-25 11:14:05 +08:00 |
