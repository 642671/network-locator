# Network Locator V2 第 7 步报告：网络分析 + 扫描历史

> 日期：2026-11-25  
> 分支：`v2/step-2-shell`（第 7 步提交在本分支）  
> 版本：`1.4.0`  
> 预览端口：`4185`（常规样例）、`4186`（`--bulk 120 --bulk-tasks 60`，分页/导出）  
> 截图：`docs/screenshots/step7/`（29 张）

## 结论

**通过（有条件）**。网络分析与扫描历史已按 V2 规范完成：接口/IP/掩码/网关/DNS、
网段设备分布、厂商分布、网关连通性、指定 IP ping、延迟与丢包统计均读取真实
后端数据；扫描历史提供时间、范围、发现/新增/离线/IP 变化、任务详情、
设备事件时间线、结果分页与完整 CSV 导出；历史列表、详情结果与详情事件均
每页 50 条；中英 × 明暗、1180×720 / 900 / 760 / 620 与空/加载/错误态均已
本地验证。真实后端已完成本机网络与 ping 验证；真机 TOS 回归仍未执行，仍是
发布前阻塞项。

| 检查项 | 结果 |
| --- | --- |
| 真实接口 / 本机 IP / 掩码 / 网段 | 通过（WSL 真实后端：`eth0 10.18.15.119/24`、`eth3 192.168.2.185/24`） |
| 网关 / DNS | 通过（`10.18.15.1`、`192.168.2.1`；DNS `10.255.255.254`） |
| 网段设备分布 / 厂商分布 | 通过（读取设备档案聚合，不用前端假计数） |
| 网关连通性 | 通过（真实网关 4/4 收到，min 1.452 / avg 1.739 / max 2.023 ms） |
| 指定 IP ping / 延迟 / 丢包 | 通过（真实 ping 统计；不可达返回 100% 丢包且 `reachable=false`） |
| Ping 非法输入 / 命令失败 | 通过（空目标与非法次数 400；`ping` 不可用 503，不伪装成功） |
| 扫描历史列表字段 | 通过（完成时间、类型、范围、状态、发现、新增、离线、IP 变化、耗时） |
| 历史列表 50 条分页 | 通过（预览 63 条：1–50 / 51–63；页码与按钮状态正确） |
| 任务详情摘要 / 错误 / 警告 | 通过（失败任务显示 error 与空事件/空结果态） |
| 设备事件时间线 | 通过（关联设备档案，设备名可打开详情抽屉） |
| 详情结果分页 / 事件分页 | 通过（两者独立分页；120 条预览显示 1–50 / 120） |
| CSV 导出完整结果 | 通过（120 条任务的 CSV 为表头 + 120 行，末条 `10.99.0.120` 在文件中） |
| 空 / 加载 / 错误态 | 通过 |
| 中文 / 英文 × 明 / 暗 | 通过（两页 2×2 覆盖；英文 DOM 扫描无残留中文） |
| 响应式 1180×720 / 900 / 760 / 620 | 通过（四档页面均无横向溢出） |
| 后端 / 前端测试 | 通过（97 / 97、44 / 44） |
| 构建 x86_64 / aarch64 | 通过（SHA 见下） |
| 打包契约 | 未改动 |
| 真机 TOS 安装 / 7 页 / 扫描 / 卸载回归 | **未执行（发布前阻塞项）** |

## 1. 实现范围

后端：

- `GET /v2/analysis` 聚合真实接口与网段（`discover_networks`）、本机 IP/掩码/
  网关/本机 MAC、`/etc/resolv.conf` DNS、设备档案的网段/厂商分布，并记录
  网络快照；接口级设备数来自 SQLite，不由前端编造。
- `POST /v2/analysis/ping` 支持指定 IP/主机名、1–20 次探测与
  `gateway:true`（使用已发现的默认网关）；返回 transmitted/received/
  loss/min/avg/max/mdev。空目标与非法次数返回 400，`CommandError` 返回 503。
- `GET /v2/scans?limit&offset` 返回分页任务与 `total`/`has_more`；limit 限制
  1–200，offset 有上界，避免异常参数拖垮服务。
- `store.get_task(task_id, result_limit, result_offset, event_limit,
  event_offset)`：任务详情的结果与设备事件分别分页；事件关联 `devices` 表
  取得当前名称与状态，结果保留 `device_id` 关联。
- 任务事件按时间倒序返回，结果按 `result_id` 稳定分页；任务不存在返回 404。

前端：

- 网络分析页：加载态、错误横幅、刷新按钮忙碌态、接口卡片、网关与 DNS、
  网段分布表、厂商分布、ping 表单与结果；网关检测和自定义 ping 分别显示
  真实的失败原因。
- 扫描历史页：50 条分页、页码范围、刷新保持当前页、清理旧记录后回到第 1 页；
  任务详情包含摘要、错误/警告、设备事件时间线与扫描结果表。
- 设备事件与扫描结果各自有独立分页；切换其中一个分页时保留另一个的偏移。
- “导出结果”会循环请求 500 条一页，直到 `results_has_more=false`，CSV 不受
  当前详情页大小影响；导出期间显示忙碌态，失败提示导出失败。
- 所有新增文案进入 `i18n.js`，包括加载、错误、ping 失败、分页、空态；
  英文模式生成文本不夹中文，用户输入文本保持原样。

## 2. 真实后端验证（Unix socket）

环境：`APP_DATA=/tmp/nl-step7`、`APP_SOCKET_PATH=/tmp/nl-step7.sock`。

| 场景 | 结果 |
| --- | --- |
| `/v2/analysis` | `eth0 10.18.15.119/24`、`eth3 192.168.2.185/24`、DNS `10.255.255.254` |
| 网关 ping | `transmitted=4`、`received=4`、`loss=0`、avg `1.739 ms` |
| 不可达地址 | `203.0.113.1`：`reachable=false`、`loss_percent=100` |
| 空 ping 目标 | 400，“请输入要测试的 IP 或主机名” |
| 非法 ping 次数 | 400，“Ping 次数必须是 1 到 20 之间的整数” |
| 真实 `/29` 扫描 | 6 个探测主机、发现 5 台设备，任务进入历史 |
| 任务详情分页 | `result_limit=2`：`results_total=5`、`events_total=5`、`has_more=true` |

预览服务器另用 `sample: true` 标记样例数据，仅用于界面、分页与状态截图，
不进入 Deb；生产路径使用系统真实接口、DNS、ping 与 SQLite 扫描记录。

## 3. 自检中发现并修复的问题

1. **任务详情没有设备事件**：原详情只返回结果，无法解释新增/离线/IP 变化。
   新增 `device_events` 关联查询与时间线，并链接设备详情抽屉。
2. **历史列表与详情无分页**：原实现最多取固定数量，任务或结果多时页面会变慢。
   列表、详情结果与详情事件均改为 50 条分页，并显示范围/总数。
3. **导出只包含当前页**：详情分页后原导出只拿到当前 50 条。改为循环拉取全部
   结果页；120 条任务实测导出 121 行（含表头）。
4. **Ping 失败被伪装成“不可达”**：原前端把所有异常都渲染成 100% 丢包。
   现在区分可达/不可达/请求错误，失败显示 error 横幅与 toast；后端对空目标、
   非法次数和命令缺失分别返回 400/503。
5. **英文模式缺少分析/历史文案**：补齐加载、错误、分页、ping 与空态文案，
   并对英文页面做 DOM 级中文残留扫描（结果为空）。

## 4. 测试与构建

```bash
python3 -m unittest discover -s apps/tos7/backend/tests -p 'test_*.py'   # 97 / 97
node --test apps/tos7/tests/*.test.js                                  # 44 / 44
node --check frontend/{app,csv,i18n,v2-data,v2-shell,v2-pages}.js      # 通过
python3 -m compileall -q backend tools                                 # 通过
python3 build.py --platform x86_64                                     # Verification: OK
python3 build.py --platform aarch64                                    # Verification: OK
```

产物：

- `apps/tos7/dist/network-locator_1.4.0_x86_64.deb`（131890 B）
  SHA256 `84268f39cb919b59f77934026cf460089645cb5003ba86e397ffc81c7bdc4cdf`
- `apps/tos7/dist/network-locator_1.4.0_aarch64.deb`（131890 B）
  SHA256 `b3e1c62513dca7e968416bd6d4ec68f3773136f9403cbc952b76aa0845776a12`

新增测试覆盖：

- 历史任务列表分页与 `has_more`。
- 任务详情结果/事件双分页、事件设备名与 detail code。
- 历史列表/详情 API 路由分页。
- ping 空目标、非法次数、`CommandError` → 503、网关目标解析。
- 前端分析与历史英文文案、ping 错误本地化。

## 5. 截图

目录 `docs/screenshots/step7/`（29 张）：

- 网络分析主路径：`zh-light-analysis.png`、`zh-light-analysis-1180x720.png`、
  `zh-dark-analysis.png`、`en-light-analysis.png`、`en-dark-analysis.png`
- Ping：`zh-light-ping-ok.png`、`zh-light-ping-unreachable.png`、
  `en-light-ping-error.png`
- 状态：`en-light-analysis-loading.png`、`en-light-analysis-error.png`、
  `zh-light-history-error.png`
- 扫描历史：`zh-light-history.png`、`zh-light-history-1180x720.png`、
  `zh-dark-history.png`、`en-light-history.png`、`en-dark-history.png`
- 任务详情：`zh-light-history-detail.png`、`en-dark-history-detail.png`、
  `en-light-history-detail-paged.png`、`en-light-history-events-pager.png`、
  `en-light-history-results-pager.png`、`en-light-history-failed.png`
- 历史分页：`zh-light-history-page1.png`、`zh-light-history-page1-pager.png`、
  `zh-light-history-page2.png`
- 响应式：`zh-light-analysis-900.png`、`zh-light-analysis-760.png`、
  `zh-light-analysis-620.png`、`zh-light-history-620.png`

说明：预览端口 `4186` 的 63 个任务与 120 条结果用于分页/导出规模验证；
截图中的预览横幅明确标注 sample UI data。

## 6. 打包契约

未改动：App ID `network-locator`、systemd unit `networklocator-system`、
socket `/var/api/network-locator.sock`、运行用户 `network-locator`、包内路径、
默认窗口 1180×720、`build.py` 打包规则。
`dpkg-deb -f` 复核：`Package: network-locator`、`Version: 1.4.0`、
`Depends: python3 (>= 3.10), systemd`；x86_64/arm64 包内
`usr/local/network-locator/lib/network_locator/`、`webui.bz2`、`config.ini`、
`init.d/networklocator-system.service`、`data/`、`logs/` 均在原路径。

## 7. 未完成项 / 已知边界

1. **真机 TOS 回归未执行（发布前阻塞）**：需在 TOS 7.1 NAS 上完成安装、
   服务 active、TOS 入口、7 个页面、真实网络扫描与卸载回归。
   按要求未触碰审核设备 189/190，继续等待机器窗口。
2. **预览数据为样例**：`4185/4186` 的接口、历史与设备分布均带 sample 标记，
   不进入 Deb；本报告的真实后端数据来自 WSL Unix socket 验证。
3. **Ping 依赖系统命令与权限**：目标不可达会如实显示丢包；命令缺失/执行失败
   返回错误并提示，不会伪造成功。
4. **任务详情分页为 50 条/页**：结果与事件独立分页；CSV 导出覆盖全部结果，
   但设备事件只用于界面查看，不写入 CSV。
5. **既有 1081px 英文深色设备表约 4px 内部滚动**：按上一步要求仅记录，
   本轮不处理；本步新增的分析/历史页面在 1180/900/760/620 无页面级溢出。
6. 本阶段未打 Release、未提交审核；1.3.8 审核记录仍为 `status=0`
   （x86_64 `b1ed1dfb-be80-4517-9f72-6021c9acd5d4`、
   aarch64 `9a55f662-b54a-4877-86a3-b4e97c7781c8`）。
