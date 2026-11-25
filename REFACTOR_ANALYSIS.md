# Network Locator V2.0 — 现有功能盘点与重构影响分析

> 分析对象：`apps/tos7`（TOS 7 iframe Deb 应用）
> **分析基线：HEAD `c43b2ae` / `1.3.8`（任务 A 已提交）**
> 分析日期：2026-11-25（代码核对与截图复核：11:32 Asia/Shanghai）
> 分析范围：后端 `network_locator`、前端 `frontend/`、打包脚本、测试与部署契约
> 截图证据：`docs/screenshots/titlebar-1.3.8-light.png`、`docs/screenshots/titlebar-1.3.8-dark.png`
> 结论：**现有功能可完整保留；V2 需要新增后端持久化/设备身份层和前端多页面框架，但不能改动 Deb 包内路径、app id、systemd unit、socket 与运行用户。**

---

## 0. 结论摘要

1. 当前是**单页 iframe 应用**：左侧固定控制栏（304px）+ 右侧“我的设备 / 设备总表 / 匹配结果”表格，没有导航、页面路由或设置页。
2. 后端是**纯 Python 标准库**：JSON API 跑在 Unix socket `/var/api/network-locator.sock`，由 TOS 平台以 `/v2/proxy/network-locator` 代理。无第三方依赖、无数据库、无后端持久化。
3. 扫描是真实能力：`ip -j route/addr/link` 识别“带默认网关的物理 IPv4 网卡”→ 计算网段 → 分批 ICMP ping + 空 UDP 预热邻居表 → 读 `ip neigh` 过滤 `REACHABLE/STALE/DELAY/PROBE` → 按 MAC 后四位匹配。**生产代码里没有假数据**（`tools/preview_server.py` 仅本地预览）。
4. 现有“持久化”全部在浏览器 `localStorage`：网段缓存、设备缓存（最多 1000 条）、搜索意图、所选网段、面板尺寸、最多 8 条收藏 MAC。清除站点数据/换浏览器/换设备即丢失。
5. 现有数据以 `{interface, scan_range, ip, mac, state, matched_suffixes}` 临时字典表示，**没有 `device_id`、没有 IP 历史、没有设备事件、没有扫描历史**；IP 变化会表现为一条新记录。
6. 在线/离线只是页面上的派生标签（`REACHABLE/LOCAL`→在线，`DELAY/STALE/PROBE`→近期，无记录→离线/未知），后端没有明确定义的在线/离线判定规则。
7. V2 的七页架构、设备档案、收藏/备注/改名、MAC 前缀/厂商查询、网络分析、扫描历史、设置，均需要**新增能力**；不能靠改颜色或复制现有表格实现。
8. 打包契约（包内路径、`network-locator` app id、`networklocator-system` unit、`/var/api/network-locator.sock`、`network-locator` 用户）与现有扫描 API 必须在重构中保持兼容；`build.py` 会自动打包 `frontend/` 下所有新文件，新增前端模块不需要改包内路径。

### 0.1 任务 A 已完成基线（供 V2 参考）

- `--titlebar-height: 41px`、`--radius: 8px`；`body padding-top`、`body::before inset`、`.window-titlebar height` 均引用 `var(--titlebar-height)`，`body` 与 `.window-titlebar` 均为 `border-box`。
- `styles.css` 共 5 个 `:root` 块（4 个顶层 + 1 个 `@media (max-width: 980px)` 内）；所有定义 `--radius` 的块均为 `8px`，没有后置规则再覆盖成 14px。
- `.window-titlebar`：`padding: 0 168px 0 16px`、`border-bottom: 1px solid #e5e6eb`；深色模式仅把底线改为 `rgba(148,163,184,.16)`。
- 品牌 20px 图标 + 14px 标题 + `gap: 8px`；状态徽标 `padding: 2px 8px; font-size: 11px`；品牌、图标、徽标中线均为 `y=20px`。
- 实测（1180×720，Orca embedded browser）：标题栏 `h=41`、`padding=0 168px 0 16px`、品牌 `x=16`、徽标右边界 `1012px`（= 1180 − 168）、无横向溢出。
- 任务 A 截图：`docs/screenshots/titlebar-1.3.8-light.png`、`docs/screenshots/titlebar-1.3.8-dark.png`。
- 基线测试：后端 54 项、前端 Node 30 项全部通过；`node --check` 通过。

### 0.2 工作区并发状态（重要）

本次核对期间（2026-11-25 11:32 起），HEAD 仍为 `c43b2ae`，但工作区存在**未提交且仍在变化的 V2 WIP**。这些内容不属于“现有已发布功能”，也未经过本报告的验收：

- 后端：`core.py` 已从基线的 1059 行增至约 1326 行（新增 `ping_statistics`、`read_dns_servers` 等）；新增未跟踪 `store.py`（SQLite 持久化/设备档案/历史/设置）与 `oui.py`（离线 OUI 子集）。
- 前端：`app.js`、`csv.js`、`index.html`、`styles.css` 有未提交修改；新增未跟踪 `i18n.js`、`v2-shell.js`、`v2-shell.css`、`v2-tokens.css`。`index.html` 已把原单页包进 V2 壳的 `discovery` 页，并加入 Dashboard/Settings 等占位页。
- 测试：`backend/tests/test_package_contract.py` 也有未提交修改；当前 WIP 未纳入 54 + 30 基线结果。
- 另有临时脚本 `.patch_core.py`、`.patch_server.py`、`tmp_api_test*.sh` 等出现在工作区（WIP 产物，非基线）。

该清单是核对时的快照，不是穷尽列表；核对后仍观察到 `server.py` 修改和新增 `v2_api.py`，说明 WIP 仍在推进。判断当前状态请以 `git status --short` 为准。

**本报告的“现状”行号、功能结论和测试数字全部以 HEAD `c43b2ae` 为准**；WIP 仅作为并发风险记录。任何继续重构的动作都应先决定保留、评审或回退这些 WIP，避免在未确认代码上叠加。若需要复核基线，可用 `git archive HEAD` 导出干净副本（本报告的截图即来自该副本）。

---

## 1. 运行形态与技术栈

| 层 | 现状 | 证据 |
|---|---|---|
| 应用类型 | TOS 7 `iframe` Deb，`exec: true`，窗口默认 1180×720 | `config.ini` |
| 后端语言 | Python 3.10+（打包依赖 `python3 (>= 3.10), systemd`），**仅标准库** | `DEBIAN/control`、`core.py`、`server.py` |
| 后端服务 | `network_locator.server`，HTTP over Unix socket，`ThreadingMixIn` | `server.py:400-436` |
| 平台接入 | TOS 反向代理到 `/v2/proxy/network-locator`；前端按 3 个候选值（去重后）探测根路径 | `app.js:38-52`、`server.py:34-52` |
| 前端 | 原生 HTML/CSS/JS，无框架、无构建、无模块系统；`var`/函数式单文件 | `index.html`、`app.js` 4932 行、`styles.css` 3471 行 |
| 数据存储 | 无后端存储；浏览器 localStorage | `core.py`/`server.py` 无文件写入 |
| 进程约束 | systemd：`MemoryMax=256M`、`CPUQuota=75%`、`LimitNOFILE=65536`、`ProtectSystem=strict` | `init.d/networklocator-system.service` |
| 可写目录 | `/usr/local/network-locator/data`、`logs`、`/var/api` | 同 unit `ReadWritePaths` |

代码规模：

| 文件 | 行数 | 说明 |
|---|---:|---|
| `backend/network_locator/core.py` | 1059 | 发现、探测、匹配、扫描状态机 |
| `backend/network_locator/server.py` | 449 | 路由、JSON API、CORS、socket 生命周期 |
| `frontend/app.js` | 4932 | 全部交互、渲染、缓存、扫描轮询 |
| `frontend/styles.css` | 3471 | 5 个 `:root`（含 1 个媒体查询内）、17 个深色覆盖块、2 个后期整体覆盖层 |
| `frontend/index.html` | 523 | 单页结构 |
| `frontend/csv.js` | 74 | CSV 构造与转义 |
| `backend/tests` + `frontend/tests` | ~2000 | 54 + 30 项测试 |

---

## 2. 不可变打包契约（V2 红线）

来自 `docs/PROJECT_LAYOUT.md`、`build.py:321-331`、`DEBIAN/*`、`test_package_contract.py`：

```text
/usr/local/network-locator/config.ini
/usr/local/network-locator/network-locator.lang
/usr/local/network-locator/network-locator.env
/usr/local/network-locator/LICENSE
/usr/local/network-locator/bin/network-locator-service
/usr/local/network-locator/images/icons/network-locator.svg
/usr/local/network-locator/init.d/networklocator-system.service
/usr/local/network-locator/lib/network_locator/*.py
/usr/local/network-locator/webui.bz2
/usr/local/network-locator/docs/PRIVACY.md
/usr/local/network-locator/data/、logs/
```

固定项：

- app id / package：`network-locator`
- systemd unit：`networklocator-system`
- socket：`/var/api/network-locator.sock`
- 运行用户：`network-locator`（无同名组，使用主组）
- 前端入口：`webui.bz2` 解压后 `./index.html`、`./app.js`、`./styles.css` 必须存在
- `build.py` 会把 `frontend/` 下**所有文件**递归打进 `webui.bz2`；因此新增 `frontend/js/*.js`、`frontend/css/*.css` 等**不改变包内路径契约**
- 后端新增模块只要位于 `backend/network_locator/*.py`，会被 `copytree` 自动打包
- `data/` 目录已在包内创建且 systemd 可写，是 V2 后端持久化的首选落点（`APP_DATA=/usr/local/network-locator/data`）
- 不允许引入系统依赖或 pip 包（`control` 明确不依赖 `iproute2`/`iputils-ping`，运行时靠 `shutil.which` 探测）

---

## 3. 后端功能盘点

### 3.1 模块职责

- `core.py`：网卡/网段发现、MAC 规范化、邻居解析、主机探测、匹配、去重、`ScanManager` 任务状态机。
- `server.py`：路由前缀剥离（支持 `/v2/proxy/<app>`）、JSON 编解码、CORS/CSRF、接口锁、Unix socket 服务与信号退出。
- `network-locator-service`：仅调用 `server.main()`。

### 3.2 网卡与网段发现（`discover_networks`, `core.py:282-390`）

执行顺序：

1. `ip -j -4 route show default` 取默认路由，按 `metric` 升序。
2. `ip -j -4 addr show` 取每个网卡的 `inet` 地址（`local` + `prefixlen`）。
3. `ip -j link show` 取网卡 MAC 地址。
4. 按默认路由的 `dev` 逐项处理：
   - 跳过虚拟网卡：`docker/veth/virbr/vmnet/tailscale/tun/tap/wg/zt/cni/flannel/podman/lxc/kube/dummy/lo`（前缀匹配）。
   - 只保留 `is_scannable_local_address` 的地址（排除 `0.0.0.0`、回环、链路本地、组播）。
   - `ipaddress.ip_network(local_ip/prefixlen, strict=False)` 计算真实网络号与广播地址。
   - 主机数超过 `SCAN_MAX_HOSTS`（默认 1022）则跳过并告警。
   - 同一 `(interface, network)` 去重。
5. 输出 `NetworkTarget`：`interface, alias, local_ip, prefix_length, gateway, network, broadcast, scan_range, host_count, local_source, local_mac`，并附加稳定 `network_id = "<interface>|<scan_range>"`。

限制与语义：

- **只发现“有默认网关”的接口**。没有默认路由的物理网卡不会出现在扫描列表。
- 一个接口有多个 IPv4 地址会生成多个 `NetworkTarget`。
- 虚拟网卡过滤是前缀黑名单，非白名单；新虚拟化前缀可能漏过滤。

### 3.3 扫描实现（`scan_hosts`, `core.py:521-587`）

1. 由 `local_ip/prefix_length` 重建网段，`network_host_count` 计算主机数（/30 及更小特殊处理）。
2. 按 `SCAN_CONCURRENCY`（默认 64，上限 128）分批。
3. 每批先 `prime_neighbor_cache`：用 `source_ip` 绑定的 UDP socket 向每台主机 9 端口发送空报文，促使内核发 ARP。
4. 若找到 `ping` 命令：线程池并发执行 `ping -n -c 1 -W <秒> -I <interface> <ip>`，仅记录成功/失败（RTT 不保存）。
5. 每批结束回调 `progress(completed)`；`cancel_event` 可在批间或 futures 完成间中断，抛 `ScanCancelled`。
6. 扫描后 `time.sleep(0.15)`，再读 `ip -j -4 neigh show dev <interface>`，只保留状态为 `REACHABLE/STALE/DELAY/PROBE` 且有 `lladdr` 的 IPv4 记录。

关键点：

- **ping 是布尔探测，不采集延迟、丢包、TTL。** 网络分析页需要的延迟/丢包统计目前没有数据源。
- 邻居表只是“最近有通信”的主机，**不等于全量在线扫描**；没有 TCP SYN/ARP 广播扫描。
- 虚拟网卡、跨 VLAN/跨路由设备不可达（README 已声明）。
- `probe_network_devices`（设备总表）复用同一 `scan_hosts`，每个 `scan_range` 只扫一次（`_sweep_groups`）。
- 扫描在后台线程运行，**不依赖页面生命周期**；页面关闭/刷新后任务继续，重新打开可轮询状态。

### 3.4 匹配、去重、状态（`core.py:590-807`）

- MAC 规范化：接受 `AA-BB` → `AA-BB`（大写、短横分隔）；后缀接受 `AA-BB`/`AA:BB`/`AABB`，最多 8 个。
- `match_neighbor_records_multi`：邻居 MAC 去分隔符后 `endswith(suffix)`，返回 `matched_suffixes` 列表。
- `match_local_target_multi`：本机网卡 MAC 命中时返回 `state: LOCAL`。
- 去重键：`(scan_range, ip, mac)`；同键合并 `matched_suffixes`，状态按优先级 `LOCAL(5) > REACHABLE(4) > DELAY(3) > PROBE(2) > STALE(1)` 保留最优。
- 结果排序：`(interface, IPv4 数值, mac)`。

**没有的语义**：`OFFLINE`、`UNKNOWN`、`last_seen`、设备身份、MAC 冲突处理、随机 MAC 识别。

### 3.5 扫描任务状态机（`ScanManager`, `core.py:810-1059`）

状态：`idle → discovering → scanning → completed | stopped | error`。

- 同一时间只允许一个任务；重复 `start` 返回 `False`。
- `matches_request(suffixes, network_ids)` 判断“是否同一请求”，供 409 冲突时区分“已在跑同一任务”与“另一个不同任务”。
- `stop()` 置 `stopping` 并触发取消事件；已完成批次结果保留。
- `status()` 返回深拷贝快照：进度、当前接口/网段、结果、告警、错误。
- 无“暂停/恢复”；只有停止 + 前端持续搜索自动重开（最多 10 轮）。
- 无任务历史；`job_id` 仅用于前端轮次计数。

### 3.6 HTTP API 清单（`server.py`）

| 方法 | 路径（代理后） | 作用 | 备注 |
|---|---|---|---|
| GET/HEAD | `/`、`/info` | 健康信息 + capabilities | `health_payload` |
| GET/HEAD | `/health` | 健康检查 | `app/version/python/max_hosts` |
| GET/HEAD | `/networks` | 发现网段 | 每次实时执行 `ip` |
| GET/HEAD | `/devices` | 邻居表设备清单 | 不主动探测 |
| POST | `/devices/scan` | 主动探测 + 邻居清单 | 45s 前端超时；与扫描互斥 |
| POST | `/scan/start` | 启动 MAC 后缀扫描 | body: `suffixes[]` / 兼容 `suffix`、`network_ids[]` |
| GET/HEAD | `/scan/status` | 轮询任务状态与结果 | 前端 450ms 轮询 |
| POST | `/scan/stop` | 停止任务 | 幂等 |

共同行为：

- 路径剥离支持 `/v2/proxy/network-locator`、`/network-locator/...`、`/api/...`。
- CORS 回显 `Origin`，允许 credentials；OPTIONS 预检。
- CSRF：前端从 cookie `X-Csrf-Token` 取 token 放入 `X-Csrf-Token` 头。
- 请求体上限 8KB；非法 JSON/超限返回 400/413；未捕获异常 500。
- `device_scan_lock` 保证“设备总表扫描”与“MAC 扫描”互斥。

### 3.7 配置与限制

| 配置 | 默认 | 来源 |
|---|---|---|
| `SCAN_MAX_HOSTS` | 1022 | `network-locator.env` |
| `SCAN_PING_TIMEOUT_MS` | 1000 | 同上 |
| `SCAN_CONCURRENCY` | 64 | 同上（代码上限 128） |
| 单次最大后缀数 | 8 | `MAX_SCAN_SUFFIXES` |
| 单次最大网段数 | 64 | `MAX_NETWORK_SELECTION` |
| `network_id` 最大长度 | 256 | `MAX_NETWORK_ID_LENGTH` |
| 请求体上限 | 8KB | `MAX_BODY_BYTES` |

### 3.8 持久化现状

- 后端**零持久化**：不写 JSON、不建库、不保存扫描历史。
- `APP_DATA=/usr/local/network-locator/data` 已配置、目录已创建、systemd 已授权写入，但代码从未使用。
- 所有“记住”都靠浏览器 localStorage（见 4.3）。

---

## 4. 前端功能盘点

### 4.1 页面结构

单页 `index.html`：

```text
window-titlebar  (品牌 + 后端状态徽标)
app-shell
├─ sidebar (304px, 可拖动 280–560)
│  ├─ MAC 后缀定位（1–8 个输入、开始/停止、进度、状态）
│  ├─ 活动网段（多选、全选、刷新、告警）
│  └─ footer（服务版本、上次扫描时间）
├─ workspace
│  ├─ 我的设备（最多 8 条收藏，收藏面板，可折叠）
│  ├─ 设备总表 / 匹配结果（筛选、排序、多选、复制、导出）
│  └─ footer（选择摘要、扫描元信息）
└─ 模态框（收藏详情/编辑、确认对话框）、tooltip、toast
```

### 4.2 前端状态模型（`app.js:61-104`）

`state` 是唯一全局状态对象（约 45 个字段），可分为：

- 网络：`networks, selectedNetworkIds, networkSelectionTouched, networkCacheRestoredAt, networkVerifiedAt, networkVerifying`
- 设备/结果：`devices, results, tableMode("devices"|"results"), tableSignature, tableQuery, tableSortKey/Direction`
- 扫描：`running, stopping, scanStatus, continuous, noMatchRounds, searchRound, lastCountedJobId, searchExhausted, searchFinished, roundInterrupted, searchGeneration, totalHosts, probedHosts, jobId`
- 目标：`activeSuffix, normalizedSuffix, activeSuffixes, normalizedSuffixes, targets[]`（每个 target 有 `display/normalized/rounds/foundCount/status`）
- 收藏：`savedMacs[], savedPanelCollapsed`
- 选择：`selectedMac, selectedIp, selectedKey`
- 服务：`retryDelay, lastRequestErrorKind`

### 4.3 localStorage 持久化

| Key | 内容 | 上限/策略 |
|---|---|---|
| `networkLocator.savedMacs.v1` | 收藏 MAC 后缀 + 备注 + 最近 IP/完整 MAC/网卡/网段/时间 | 8 条；备注 100 字；写入 250ms 防抖 |
| `networkLocator.networkCache.v1` | 最近网段 + 告警 | 无 TTL；启动先展示再校验 |
| `networkLocator.deviceCache.v1` | 最近设备清单 | 1000 条；要求网段签名与所选网段一致 |
| `networkLocator.networkSelection.v1` | 用户手动选择的网段 | 仅 `touched=true` 时恢复 |
| `networkLocator.searchIntent.v1` | 持续搜索目标、轮次、最近 50 条结果 | 搜索结束后删除 |
| `networkLocator.layout.sidebarWidth.v1` | 侧栏宽度 | 280–560 |
| `networkLocator.layout.scanPaneHeight.v1` | 扫描区高度 | 280–560 |
| 父窗口 `themeMode` | TOS 桌面主题 | `index.html` 内联脚本读取，失败回退系统偏好 |

数据丢失条件：清除站点数据、隐私模式、换浏览器/设备、localStorage 被禁用（会 toast 提示）。同一浏览器多人共用会看到彼此收藏（已在 `docs/REQUIREMENTS_SAVED_MACS.md` 声明）。

### 4.4 现有功能清单（V2 必须保留或迁移）

**扫描与网段**

- 自动识别活动物理网段、默认全选、多网段勾选、全选、刷新。
- 所选网段跨刷新/持续搜索周期保留，并同时作用于 MAC 匹配与设备总表。
- 虚拟网卡跳过与告警展示。
- 进度条、百分比、当前接口/网段、已探测/总数。
- 停止扫描；持续搜索自动继续；最多 10 轮；服务中断自动重试（1.1s 起指数退避至 15s）。
- 页面刷新/重新打开后恢复搜索意图并继续轮询。

**MAC 定位**

- 1–8 个后缀输入，格式 `AA-BB`/`AA:BB`/`AABB`，大小写不敏感，保留用户输入大小写。
- 重复后缀拒绝；空行失焦自动收起；行内错误提示与 `aria-invalid`。
- 多后缀同扫、结果行标注匹配后缀、目标汇总 chip、每目标独立 10 轮预算。

**设备总表 / 匹配结果**

- 启动与刷新时主动探测全表；设备缓存恢复；`LOCAL` 本机设备。
- 按 IP/MAC/网卡/网段/状态（含 `本机 local`）筛选；空格分词 AND；MAC 片段支持 `-`/`:`。
- 每列排序：IPv4 数值、网段 CIDR、自然文本；升/降序。
- 行选择、多选复选框（界面只保留单选语义）、复制 IP/MAC、双击复制 MAC、Enter 复制。
- IP 可点击在新标签打开 `http://IP/`。
- 空状态、加载、错误、完成、停止、等待等状态文案。
- 网段 chips、结果计数、筛选后计数。

**收藏（我的设备）**

- 最多 8 条；备注 100 字；重复拦截；编辑/删除/用于搜索。
- 最近 IP/完整 MAC/网卡/网段/最后发现时间自动更新（扫描或刷新设备后）。
- 在线/近期/离线/未知派生状态；同后缀多设备全部列出并标“N 台”。
- 跨标签页同步（`storage` 事件）；关闭页面前 flush 写入。
- 损坏数据防御性清洗、ID 冲突修复。

**导出/复制/界面**

- CSV 导出当前可见行（筛选 + 排序后）；UTF-8 BOM；公式注入防护；文件名带时间戳。
- 复制选中 IP/MAC、复制行内 IP/MAC、toast 反馈。
- 浅色/深色主题切换（仅当前会话；启动读取 TOS 主题）。
- 侧栏宽度/扫描区高度拖动、双击恢复、键盘调整、窗口缩放响应式（`≤820px`/`≤980px`/`≤680px` 工作区窄布局）。
- tooltip、焦点陷阱、`aria-*`、`prefers-reduced-motion`。

### 4.5 CSV 导出细节（`csv.js`）

- 默认列：`网卡, 扫描范围, IP 地址, MAC 地址, 状态`；`LOCAL` 映射为“本机”。
- 单元格转义：逗号/引号/换行加引号；以 `= + @` 或非数字 `-` 开头时前置 `'`，防止 Excel 公式执行。
- 行分隔 `\r\n`，默认带 BOM；日期戳 `YYYYMMDD-HHmmss`。
- 只导出当前可见行，不含收藏、历史、列配置。

### 4.6 主题、布局与可访问性

- 主题：`html[data-theme="light|dark"]`；页面启动时从父窗口 localStorage 读取，否则 `prefers-color-scheme`。
- 主题切换**不写回 localStorage**，刷新后回到 TOS/系统主题。
- 布局：`app-shell` 网格；`--sidebar-width`、`--scan-pane-height` 由 JS 写入根变量并持久化。
- 可访问性：焦点陷阱、`aria-live`、`aria-sort`、`role="progressbar"`、键盘可调整分隔条、减少动画媒体查询。

### 4.7 页面/功能调用关系

当前没有页面路由，调用关系如下：

```text
DOMContentLoaded → boot()
  ├─ applyTheme / initializePanelLayout / bindEvents / bindTooltips
  ├─ readSavedMacs / bindSavedDeviceEvents / renderSavedDevices
  ├─ restoreSearchIntent
  ├─ restoreNetworkCache → restoreDeviceCache
  ├─ restoreNetworkSelection
  ├─ checkBackend → refreshApiRoot → GET /health
  ├─ verifyCachedNetworks → GET /networks
  ├─ refreshDevices → POST /devices/scan
  └─ GET /scan/status → renderScanStatus → scheduleScanPoll

点击“开始扫描” → startScan()
  → POST /scan/start
  → pollScanStatus (450ms) → GET /scan/status
  → renderScanStatus → renderResults/renderTargetSummary
  → completed 且 continuous → registerContinuousRound → persistSearchIntent
  → scheduleContinuousRestart → resumeContinuousSearch → startScan({continuousCycle:true})

点击“刷新 IP / 设备总表” → refreshDevices → POST /devices/scan
  → mergeSavedMacLastSeen → persistDeviceCache → renderDevices → renderSavedDevices

点击“导出 CSV” → exportVisibleCsv → visibleTableRows → LanMacCsv.buildCsv
```

---

## 5. 测试与基线

| 测试 | 命令 | 现状 |
|---|---|---|
| 后端单元/契约 | `python3 -m unittest discover -s backend/tests -v` | 54 项通过（WSL Python 3.12） |
| 前端 CSV/搜索/收藏 | `node --test tests/*.test.js` | 30 项通过 |
| JS 语法 | `node --check frontend/app.js`、`csv.js` | 通过 |
| 打包契约 | 内含于后端 `test_package_contract.py` | 通过 |

> 以上为 HEAD `c43b2ae` 的基线结果。工作区当前未提交的 V2 WIP（新增 store/oui、core.py 探测扩展、i18n、V2 壳层）尚未纳入这组数字，不能视为已验收。

测试空白（V2 需补）：

- 扫描中断、重复扫描、IP 变化、设备去重、MAC 冲突、在线/离线判定。
- 多网卡/多网段真实环境（现多为 mock runner）。
- CSV 导出内容快照（仅测构造器）。
- 持久化迁移、历史记录、设置 API。
- 窗口缩放的视觉回归（无自动化）。

---

## 6. V2 数据模型对照与缺口

| V2 模型 | 现状 | 缺口 |
|---|---|---|
| `Device` | 无；每次扫描生成临时字典 | 需要稳定 `device_id`、首次/最后发现、在线状态、用户名称/备注/收藏 |
| `DeviceAddress` | 临时行 `{ip, mac, interface, scan_range, state}` | 需要按设备累积地址历史、IP 变化、首次/最后出现、来源扫描 |
| `NetworkInterface` | `NetworkTarget` 部分字段 | 需要独立接口模型、所有接口（不只默认路由）、别名、虚拟标记、状态 |
| `NetworkSegment` | `NetworkTarget.scan_range` | 需要独立网段模型、所属接口、主机数、最近扫描 |
| `ScanTask` | `ScanManager` 单例状态 | 需要任务表、类型（匹配/设备/自定义）、范围、起止时间、结果计数、状态、错误 |
| `ScanResult` | `results[]` | 需要持久化到任务、设备关联、新增/离线/IP 变化统计 |
| `DeviceEvent` | 无 | 需要发现/上线/下线/IP 变化/手动编辑事件 |

V2 要求的“不能以 IP 作为唯一标识”目前**完全不满足**：现有去重键包含 IP，IP 一变就是新行。

---

## 7. 重构影响分析

### 7.1 可直接复用的资产

- **扫描核心**：`discover_networks`、`scan_hosts`、`read_neighbors`、`match_*`、`ScanManager` 的线程/取消/轮询模型。
- **真实网段计算**：`ipaddress` 严格计算网络号/广播地址/主机数，已有超限保护。
- **安全约束**：参数化命令、MAC/网段校验、请求体上限、CSRF/CORS、无 shell。
- **CSV 构造器**：转义与公式注入防护可直接升级为多列/多表导出。
- **收藏数据清洗**：`sanitizeSavedMac`、ID 冲突修复、跨标签同步、防抖写入思路可迁移到新模型。
- **UI 原子件**：状态 chip、tooltip、确认框、焦点陷阱、进度条、空/错/加载状态、resizer 交互。
- **主题变量体系**：`html[data-theme]` + CSS 变量；V2 可替换为设计 token，但需清理多层覆盖。

### 7.2 必须新增的后端能力（不改变既有 API）

建议新增独立模块（`backend/network_locator/store.py`、`inventory.py`、`history.py`、`analysis.py`），沿用同一 `server.py` 路由分发：

1. **持久化层**：在 `APP_DATA` 下用 `sqlite3`（标准库）或“JSON + 原子 rename”。推荐 SQLite：事务、索引、256MB 限制下足够。
2. **设备身份与档案**：`devices`、`device_addresses`、`device_events`；匹配优先级建议“手动绑定 > 完整 MAC > 最近 IP + 网段 > 新建设备”。
3. **设备 CRUD**：改名、备注、收藏、批量操作；扫描结果只更新地址/状态，不覆盖用户字段。
4. **在线/离线判定**：明确规则并持久化 `last_seen`（例如 `REACHABLE/LOCAL` 在线；`DELAY/STALE/PROBE` 近期；超过 N 次扫描未出现离线；从未出现未知）。
5. **扫描任务与历史**：任务类型、范围、开始/结束、发现/新增/离线/IP 变化计数；结果快照可导出。
6. **MAC 查询**：完整 MAC / 前缀 / 后缀；格式自动识别；关联设备档案。**厂商识别需要离线 OUI 数据**，不能联网查询；若无内置数据，必须明确显示“未知厂商”，不得编造。
7. **网络分析**：接口信息、IP/掩码/网关/DNS（`/etc/resolv.conf` 或 `resolvectl`，需探测可用性）、网段信息、设备分布、网关连通性检测（复用 ping 布尔结果）、指定 IP ping 延迟/丢包（需扩展 `scan_hosts` 或新增探测函数，采集 RTT/丢包率）。
8. **设置**：扫描超时/并发/默认网卡/自动扫描策略/CSV 配置/主题；持久化到 `data/settings.json`；后端启动时读取，运行时经 API 更新（注意 `MemoryMax=256M`）。
9. **自定义范围扫描**：需新增“用户输入 CIDR”校验（仅私有 IPv4、主机数上限、可选网卡），并与现有 `network_ids` 选择并存。

### 7.3 必须重写的前端部分

- **应用框架**：左导航（210–230px）+ 顶部工具栏（56–64px）+ 主内容 + 右侧详情抽屉（400–460px）。
- **页面路由**：7 个视图（Dashboard/Discovery/Inventory/MAC Lookup/Analysis/History/Settings），建议 hash 路由或轻量视图切换，保持单入口 `index.html`（打包契约要求）。
- **设计系统**：统一 token（主色 `#2563EB`、背景 `#F5F7FA`、表行 44–48px、按钮 34–38px）、统一按钮/输入/卡片/表格/弹窗/空状态。
- **数据层**：从 `state` 巨型对象拆分为 API client + 视图 store；保留现有扫描轮询与持续搜索行为。
- **详情抽屉**：设备档案、地址历史、事件、编辑名称/备注/收藏。
- **表格能力**：批量选择、分页/虚拟滚动（大量设备）、列配置（CSV）、快速复制。
- **设置页**：主题持久化、扫描默认参数、CSV 列配置、存储位置展示。
- **现有单页功能迁移**：MAC 后缀定位、多后缀、设备总表、收藏、导出、复制、resizer、tooltip 均需在新框架中以新组件复现，**不得删除**。

建议拆分（保持原文件作为入口，避免打包契约风险）：

```text
frontend/
  index.html          # 保留入口与 __APP_VERSION__
  styles.css          # 保留入口，可 @import 设计系统
  app.js              # 保留入口，可改为加载模块
  js/api.js
  js/store.js
  js/router.js
  js/views/dashboard.js
  js/views/discovery.js
  js/views/inventory.js
  js/views/mac-lookup.js
  js/views/analysis.js
  js/views/history.js
  js/views/settings.js
  js/components/*.js
  css/tokens.css
  css/layout.css
  css/components.css
```

注意：当前无打包器，新增模块需用 `<script>` 顺序加载或原生 ES module（TOS WebView 需验证 `type="module"` 支持；保守方案是 IIFE 命名空间 + 顺序脚本）。

### 7.4 数据迁移方案

1. **收藏 MAC**：`networkLocator.savedMacs.v1` → 后端设备档案的“手动维护条目”。迁移时保留 `display/normalized/note/lastSeen*`，生成 `device_id`；用户备注/名称/收藏标记原样保留。
2. **设备缓存**：`networkLocator.deviceCache.v1` 可作为首次启动的“历史设备”种子，但必须标记来源为“缓存”，避免与真实扫描混淆。
3. **网段选择/布局/搜索意图**：继续留在 localStorage（纯 UI 偏好），或迁移到设置表；建议布局留本地、扫描策略入后端设置。
4. **版本化**：新存储加 `schema_version`；启动时执行幂等迁移；不得删除旧 key，直到迁移成功并可回退。
5. **失败降级**：后端存储不可写时，前端继续以 localStorage 运行并明确提示“历史/档案不会持久化”，扫描功能不受影响。

### 7.5 风险登记

| ID | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | 前端单文件 4932 行 + CSS 5 个 `:root`、17 个深色覆盖、2 个后期整体覆盖块 | 改一处样式易被后置规则覆盖；重构回归面大 | 先建立 token 与样式分层；逐段迁移并截图对比；删除覆盖前先确认无引用 |
| R2 | 后端无持久化、无设备身份 | V2 设备档案/历史/事件全部依赖新增层 | 先做 store + 迁移，再接 UI；保留旧 API 输出结构兼容 |
| R3 | 扫描能力仅“默认路由网卡 + ICMP + neigh” | 无法满足“全部接口/自定义范围/延迟丢包” | 扩展发现与探测接口；无能力项在 UI 明示“不可用”，不造假 |
| R4 | 在线/离线语义未定义 | 设备状态、历史统计、仪表盘口径不一致 | 先定规则并写成测试；后端计算、前端只展示 |
| R5 | API 路径/代理/CSRF 契约 | 改错会导致 TOS iframe 全白 | 保留 `/v2/proxy/<app>` 前缀处理与 `X-Csrf-Token`；新增端点而非改旧端点 |
| R6 | systemd 256MB / 75% CPU、45s 超时、8KB body | 大量设备/历史/扫描并发易超限 | 分页/索引/流式；设置上限；避免全量常驻内存 |
| R7 | Python 3.10 下限、仅标准库 | 使用新语法/第三方库会在目标机失败 | 只用 3.10 兼容语法与标准库；CI 用 3.12 + 本地 3.10 检查 |
| R8 | 包内路径/app id/socket/用户固定 | 改任一即破坏安装与审核 | 加契约测试守护；新增文件只放约定目录 |
| R9 | localStorage 迁移与共享浏览器 | 收藏可能属于错误用户/丢失 | 迁移幂等 + 后端按用户隔离（若平台提供身份）；失败降级提示 |
| R10 | 扫描任务与页面生命周期解耦 | 新框架若把任务放页面内会回归 | 保持后端 `ScanManager` 为唯一任务源；前端只轮询 |
| R11 | 预览/假数据混入生产 | 违反“不得用假数据冒充真实扫描” | 预览服务仅 `tools/`；生产 API 不返回合成数据；UI 预览用独立开关并明确标注 |
| R12 | CSV 公式注入/编码 | 导出安全问题 | 保留 `escapeCell` 规则并加测试；新增列同样走转义 |

### 7.6 打包契约守护清单（每次提交前）

- [ ] `config.ini` 的 `id/system_id/package/application_type/type/path/version` 未变。
- [ ] `DEBIAN/control` 版本与 `VERSION`、`config.ini`、`backend/__init__.py` 一致。
- [ ] systemd unit 仍为 `networklocator-system.service`，`User=network-locator`，无 `Group=`，无 `PrivateTmp=true`。
- [ ] socket 仍为 `/var/api/network-locator.sock`。
- [ ] `webui.bz2` 仍含 `./index.html`、`./app.js`、`./styles.css`（可新增文件，不能删入口）。
- [ ] `frontend/index.html` 仍用 `__APP_VERSION__` 占位。
- [ ] 后端仍只依赖标准库与 `python3 (>=3.10), systemd`。
- [ ] 运行后端 54 项、前端 30 项测试；新增功能补测试。
- [ ] `python3 build.py --platform x86_64/aarch64` 可构建并校验。

### 7.7 分阶段影响（对应任务书八步）

| 阶段 | 主要改动 | 回归风险 | 必测 |
|---|---|---|---|
| 1 分析/计划 | 本文档 | 无 | 基线测试 |
| 2 设计系统/主框架 | 新 HTML 骨架、token、左导航/工具栏/抽屉壳 | 高（现有单页被替换） | 页面切换、缩放、浅/深色、现有扫描入口可达 |
| 3 总览/设备管理 | 新 API + 视图 + 设备表 | 高（数据模型） | 去重、筛选排序、复制、CSV |
| 4 详情抽屉/数据模型 | store、迁移、编辑/收藏/历史 | 高（持久化） | 刷新保留、IP 变化、备注不被覆盖 |
| 5 网络扫描重构 | 发现/探测扩展、暂停/恢复/停止、自定义范围 | 高（核心能力） | 多网卡、多网段、中断、重复扫描、真实结果 |
| 6 MAC 定位 | 完整/前缀/后缀、批量、关联档案 | 中 | 格式识别、批量、厂商未知处理 |
| 7 网络分析/历史 | 延迟丢包、网关连通、任务历史 | 中 | 统计口径、大量历史加载 |
| 8 设置/高级 | 设置 API、主题持久化、CSV 配置 | 中 | 设置生效/重启保留、降级 |

---

## 8. 已知问题清单（重构前基线）

| ID | 问题 | 影响 |
|---|---|---|
| K1 | 后端零持久化，`APP_DATA` 未使用 | 设备档案/历史无法跨浏览器、跨设备保留 |
| K2 | 无 `device_id`，去重键含 IP | IP 变化生成新行，无法追踪设备 |
| K3 | 在线/离线/未知无明确判定 | 状态标签口径不统一 |
| K4 | 仅支持 MAC 后四位 | 不支持完整 MAC/前缀/厂商查询 |
| K5 | 仅发现默认路由网卡；无自定义范围 | 部分物理网段不可扫描 |
| K6 | 无暂停/恢复；仅停止 + 持续重试 | 不满足 V2 扫描控制要求 |
| K7 | 无扫描历史/任务列表/事件 | 无法回溯 |
| K8 | 无设置页；主题切换不持久化 | 刷新后主题丢失 |
| K9 | 设备无用户名称/备注/收藏（仅 MAC 后缀收藏） | 设备管理能力不足 |
| K10 | 无 OUI/厂商库 | 厂商识别缺失 |
| K11 | ping 仅布尔，无 RTT/丢包 | 网络分析无数据源 |
| K12 | 单页无导航；侧栏 304px | 不符合 V2 七页/210–230px 导航规范 |
| K13 | CSS 多层覆盖（5 个 `:root`、17 个深色块、2 个整体覆盖层） | 样式回归风险高 |
| K14 | 表格无分页/虚拟滚动；设备缓存 1000 | 大量设备可能卡顿 |
| K15 | 收藏上限 8、localStorage 共享 | 多用户/多设备体验受限 |
| K16 | 前端文案硬编码中文 | 无多语言（`network-locator.lang` 仅应用商店元数据） |
| K17 | 无 MAC 随机化/虚拟网卡/MAC 冲突处理 | 设备身份误判风险 |
| K18 | `≤820px` 时隐藏徽标、标题栏 `padding-right` 降为 18px | 820×720 实测品牌右边界 100px、徽标 `display:none`、无横向溢出；系统按钮区没有自绘文案，未复现遮挡（真机仍建议抽测） |

---

## 9. 建议实施路线

1. **冻结基线**：任务 A 合并/发布；保存截图与测试结果（已完成，见 0.1）。
2. **先做后端“地基层”**（不碰 UI）：store（SQLite/JSON）+ schema 版本 + 迁移 + 设备身份 + 事件 + 任务历史；保留旧 API 输出。
3. **再做前端“壳”**：token/设计系统 + 左导航/工具栏/抽屉 + 路由；先以只读方式接入现有 API，确保现有扫描/MAC 定位/设备总表全部可用。
4. **设备总览/设备管理**：接入新 store；补改名/备注/收藏/批量/抽屉。
5. **扫描重构**：扩展接口发现与探测，补暂停/恢复/自定义范围；每步用真实 NAS 验证。
6. **MAC 定位**：完整/前缀/后缀 + 档案关联；厂商无数据时明确“未知”。
7. **网络分析/历史**：延迟丢包采集、网关连通、任务历史。
8. **设置**：参数、主题、CSV、存储位置、关于；最后做打包与审核回归。

每一阶段结束必须：`node --check`、前端 30 项、后端 54 项、`build.py` 双架构构建、实机/预览截图、打包契约清单。

> **并发提醒**：工作区已出现未提交的阶段 2/3 WIP（见 0.2）。在主人确认前，不应继续扩展或合并这些改动；先做代码评审、测试与截图，再决定保留或回退，避免两个方向同时改同一批文件。

---

## 10. 待主人确认的决策点

1. **持久化介质**：SQLite（推荐，事务/索引）还是 JSON 文件（更易人工检查）？
2. **设备身份规则**：完整 MAC 优先 + 手动绑定兜底，是否接受随机 MAC 会新建档案？
3. **在线/离线阈值**：连续多少次扫描未出现判离线？`STALE/DELAY` 算在线还是“近期”？
4. **厂商库**：是否内置离线 OUI 子集？若无，界面统一显示“未知厂商”是否可接受？
5. **自定义范围**：是否允许任意私有 CIDR？是否限制必须属于本机接口网段？
6. **暂停/恢复**：需要真正暂停（保留进度）还是“停止后可续跑”即可？
7. **旧功能取舍**：现有“最多 8 个 MAC 后缀 + 10 轮持续搜索”是否原样保留为独立功能，还是合并进 V2 扫描策略？
8. **主题**：是否写回 TOS 桌面主题（父窗口）还是仅应用内持久化？
9. **多语言**：V2 是否仍只做中文？
10. **数据保留**：扫描历史保留条数/天数上限（受 256MB 内存与存储限制）。

---

## 附：关键证据索引

- 网段发现：`backend/network_locator/core.py:282-390`
- 主机探测：`core.py:472-587`
- 邻居匹配/去重：`core.py:590-807`
- 扫描状态机：`core.py:810-1059`
- API 路由：`server.py:191-362`
- socket/信号：`server.py:387-436`
- 前端状态：`frontend/app.js:61-104`
- localStorage keys：`app.js:5-25`
- 收藏逻辑：`app.js:179-353`、`app.js:4013-4447`
- 扫描轮询/持续搜索：`app.js:2643-3450`
- CSV：`frontend/csv.js:13-73`
- 打包布局：`build.py:378-458`、`docs/PROJECT_LAYOUT.md`
- 不可变契约测试：`backend/tests/test_package_contract.py`
- 任务 A 截图：`docs/screenshots/titlebar-1.3.8-light.png`、`docs/screenshots/titlebar-1.3.8-dark.png`
- 任务 A 实测：1180×720 下 titlebar `h=41`、`padding=0 168px 0 16px`、品牌 `x=16`、徽标右边界 `1012`、品牌/图标/徽标 `centerY=20`
- 基线副本：`git archive HEAD`（`c43b2ae`）导出的干净目录；截图与 54 + 30 测试均在该副本上完成
