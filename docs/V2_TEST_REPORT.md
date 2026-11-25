# Network Locator V2 功能测试报告

> 版本：1.4.0  
> 日期：2026-11-25  
> 环境：TOS 7.1 目标包；本地预览 Ubuntu-24.04 / Python 3.12 / Node 22 / Orca Chromium  
> 预览地址：`http://127.0.0.1:4178/`  
> 浏览器视口：1081×881（Orca 桌面窗口 1200×900 的 iframe 尺寸）  
> 生产扫描：真实 NAS `eth0 10.18.15.119/24`，网关 `10.18.15.1`，清单扫描发现 114 台设备

## 1. 自动化测试

| 测试集 | 命令 | 结果 |
| --- | --- | --- |
| 后端单元/契约测试 | `python3 -m unittest discover -s apps/tos7/backend/tests -p 'test_*.py'` | **72 / 72 通过** |
| 前端 Node 测试 | `node --test apps/tos7/tests/frontend_csv.test.js apps/tos7/tests/frontend_saved_macs.test.js apps/tos7/tests/frontend_search_state.test.js apps/tos7/tests/frontend_v2_data.test.js` | **34 / 34 通过** |
| JS 语法 | `node --check`（`app.js`、`csv.js`、`i18n.js`、`v2-data.js`、`v2-shell.js`、`v2-pages.js`） | 全部通过 |
| Python 编译 | `python3 -m compileall -q apps/tos7/backend` | 通过 |

新增专项测试覆盖：

- 设备身份：MAC 优先、IP+接口 7 天兜底、IP 变化不新建设备、用户改名/备注/收藏不被扫描覆盖。
- 状态：完整扫描未发现→离线；只有邻居表→未知；超时→未知。
- 扫描历史：任务写入、结果详情、清理历史。
- 设置：范围校验、保存与读取。
- MAC：完整/前缀/后缀识别、OUI 厂商、批量查询、格式错误。
- 自定义范围：CIDR、起止 IP、去重、与活动网段合并。
- 暂停/恢复：真实 `ScanManager` 暂停、状态快照、恢复完成。
- CSV：分隔符、表头开关、UTF-8 BOM。

## 2. 页面与交互验证（浅色、中文）

| 页面 | 验证项 | 结果 |
| --- | --- | --- |
| 全局框架 | 210px 左导航、60px 工具栏、41px TOS 标题栏、8px 圆角、无页面横向溢出 | 通过 |
| 设备总览 | 6 张统计卡（3×2）、接口/网段、最近发现、全局设备表、搜索、状态筛选、排序、复制 IP/MAC、立即扫描、导出 CSV | 通过 |
| 网络扫描 | 2 个物理网段、自动本机 IP/掩码、多选、自定义 CIDR、开始/停止/暂停/恢复、实时结果、错误提示、导出 | 通过 |
| 设备管理 | 全部/在线/离线/未知/收藏筛选、名称/IP/MAC/厂商搜索、排序、批量选择、批量收藏、批量导出、详情抽屉 | 通过 |
| 详情抽屉 | 440px、摘要字段、设备名称、备注、收藏、保存、复制 IP/MAC、IP 历史、设备事件 | 通过 |
| MAC 定位 | 完整 MAC、6 位前缀、4 位后缀、自动格式提示、批量模式、厂商 OUI、设备关联、live 标记 | 通过 |
| 网络分析 | 接口、IP/掩码/网关/DNS、网段分布、厂商分布、网关连通性、指定 IP ping、延迟与丢包 | 通过 |
| 扫描历史 | 任务时间、类型、范围、状态、发现/新增/离线/IP 变化、耗时、任务详情、结果导出、清理历史 | 通过 |
| 系统设置 | 超时、并发、默认网卡、在线有效期、自动扫描、存储位置、CSV 分隔符/表头/BOM、主题、语言、关于 | 通过 |
| 深色模式 | 所有页面、标题栏、表格、抽屉、按钮、空状态、警告状态 | 通过 |

关键实测数据：

- `document.documentElement.scrollWidth - clientWidth = 0`；设备总览、设备管理、扫描历史在 1081、900、760、620 宽度下页面均无横向溢出。
- 1081 宽时 `.v2-nav` = 210px；≤1050px 折叠为 72px。设备管理表在 ≤1150 隐藏网段列、≤900 隐藏厂商/最近发现、≤700 隐藏状态/操作列；详情仍可通过行点击打开。
- 设备表行高 46px，按钮 36px，详情抽屉 440px，页面内边距 24px。
- 扫描历史英文模式曾在 1081 宽溢出 27px，已通过紧凑范围显示和响应式列收敛修复，现为 `scrollWidth == clientWidth == 821`。
- `orca console` 交互全程 0 条错误。

## 3. 真实后端验证

在真实 NAS 网络上启动 `python3 -m network_locator.server` 并代理到本地：

- 网卡：`eth0 10.18.15.119/24`，网关 `10.18.15.1`。
- 设备清单扫描：发现 **114** 台，新增 **109** 台，IP 变化 **5** 台。
- 本机 ping：0.124 ms；网关 ping：11.379 ms；丢包统计来自真实 `ping` 输出。
- `v2/summary`、`v2/devices`、`v2/scans`、`v2/settings` 均返回真实数据；没有用示例数据冒充扫描结果。

## 4. 预览模式说明

`apps/tos7/tools/preview_server.py` 只用于本地 UI 预览，所有 `/v2/*` 示例响应都带
`"sample": true`，界面上显示橙色“预览模式”提示。生产包不包含预览服务器，
生产扫描路径不会读取任何示例设备。

## 5. 截图证据

浅色与深色均在 1081×925 浏览器视口完成，页面语言为中文：

- `docs/screenshots/v2-dashboard-light.png` / `v2-dashboard-dark.png`
- `docs/screenshots/v2-dashboard-table-light.png`
- `docs/screenshots/v2-inventory-light.png` / `v2-inventory-dark.png`
- `docs/screenshots/v2-mac-lookup-light.png` / `v2-mac-lookup-dark.png`
- `docs/screenshots/v2-analysis-light.png` / `v2-analysis-dark.png`
- `docs/screenshots/v2-history-light.png` / `v2-history-dark.png`
- `docs/screenshots/v2-settings-light.png` / `v2-settings-dark.png`
- `docs/screenshots/v2-discovery-light.png` / `v2-discovery-dark.png`
- `docs/screenshots/v2-drawer-light.png` / `v2-drawer-dark.png`
- 任务 A 标题栏（1.4.0 当前 UI）：`docs/screenshots/titlebar-1.4.0-light.png` / `titlebar-1.4.0-dark.png`
- 任务 A 标题栏（1.3.8 历史证据）：`docs/screenshots/titlebar-1.3.8-light.png` / `titlebar-1.3.8-dark.png`

## 6. 待真机回归项

- 在 TOS 7.1 测试 NAS 上安装 1.4.0 Deb，确认系统标题栏、按钮栏、iframe 高度。
- 多网卡、多网段、扫描中断、重复扫描、IP 变化、收藏/备注持久化的真机回归。
- 大量设备（>1000）滚动性能与内存占用。
- deb 安装/卸载/重装后的数据保留与清理行为。
