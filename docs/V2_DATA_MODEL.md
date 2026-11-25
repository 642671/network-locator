# Network Locator V2 数据模型与迁移

> 适用版本：1.4.0  
> 存储实现：`apps/tos7/backend/network_locator/store.py`（SQLite，WAL）  
> 数据库位置：`$APP_DATA/network-locator.db`，打包环境中为
> `/usr/local/network-locator/data/network-locator.db`  
> 预览环境：`apps/tos7/backend/data/preview.sqlite`

## 1. 核心实体

| 实体 | 说明 | 实现 |
| --- | --- | --- |
| Device | 一台被管理的设备，使用稳定的 `device_id` | `devices` 表 |
| DeviceAddress | 设备在某个时间使用过的 IP / MAC / 接口 | `device_addresses` 表 |
| NetworkInterface | 当前 NAS 的物理 IPv4 接口 | 由 `ip -j addr/link/route` 实时发现，不持久化 |
| NetworkSegment | 接口 + CIDR 网段，例如 `eth0\|192.168.1.0/24` | 由接口地址和前缀实时计算，不持久化 |
| ScanTask | 一次 MAC 扫描或设备清单扫描 | `scan_tasks` 表 |
| ScanResult | 一次扫描发现的单条结果 | 任务结果 JSON 与地址变化记录 |
| DeviceEvent | 设备首次发现、IP 变化、离线、恢复在线等事件 | `device_events` 表 |

## 2. 身份规则（不能以 IP 作为唯一标识）

1. 每个设备创建时生成 UUID 形式的 `device_id`，此后永不改变。
2. 扫描结果先去重，再按以下顺序匹配已有设备：
   - **MAC 完全匹配**：最可靠，优先命中。
   - **IP + 接口在 7 天内出现过**：用于随机 MAC、换网卡或 MAC 暂时不可见的设备。
   - 两者都不命中时创建新设备。
3. IP 单独出现不构成身份依据。IP 换了只会新增一条 `device_addresses`
   记录并更新 `devices.ip_current`，不会新增设备。
4. 随机 MAC（第二字节最低两位为 `10`）会标记 `random_mac`，不会因为
   MAC 变化就必然新建档案。
5. 虚拟网卡、Docker、veth、VPN 接口不进入可扫描网段。MAC 冲突时保留
   已有 `device_id`，并在事件中记录地址变化，避免同一台设备被拆成多条。
6. 用户字段 `display_name`、`note`、`favorite` 只由显式 PATCH 修改。
   扫描、重扫、IP 变化都不会覆盖它们。

## 3. 在线、离线、未知

状态值为 `online`、`offline`、`unknown`，后端同时返回 `status_state`
（`LOCAL`、`REACHABLE`、`DELAY`、`STALE`、`PROBE`）和中文原因。

| 条件 | 结果 |
| --- | --- |
| 最近一次探测为 `LOCAL`（本机网卡）或 `REACHABLE` | `online` |
| 一次**完整清单扫描**没有发现该设备，且设备之前存在 | `offline` |
| 只在邻居表中看到 `DELAY`、`STALE`、`PROBE`，未被主动探测确认 | `unknown` |
| `online` 的最后确认时间超过 `stale_after_minutes`（默认 60 分钟） | `unknown` |
| 没有可确认数据 | `unknown` |

扫描失败、网络不可达、服务离线都不会被标记为成功；任务写入 `error`
或 `stopped`，不会把旧设备伪造成新发现。

## 4. 表结构（SCHEMA_VERSION = 1）

- `meta(key, value)`：结构版本等元数据。
- `devices`：`device_id` 主键，包含 `display_name`、`note`、`favorite`、
  `vendor`、`mac_current`、`ip_current`、`interface_current`、
  `network_current`、`status`、`status_state`、`random_mac`、
  `first_seen`、`last_seen`、`last_checked`、`seen_count`。
- `device_addresses`：`device_id`、`ip`、`mac`、`interface`、`network_id`、
  `first_seen`、`last_seen`，保留 IP 历史。
- `device_events`：设备事件、旧值、新值、时间。
- `scan_tasks`：任务类型、状态、起止时间、网段、自定义范围、后缀、
  发现数、新增数、离线数、IP 变化数、错误与告警。

## 5. 扫描任务与去重

- 任务由 `ScanManager` 在后台线程执行，不依赖页面生命周期；关闭或刷新
  WebUI 后任务继续，重新打开页面可继续轮询状态。
- 后台同一时刻只允许一个 MAC 扫描和一个清单扫描；`device_scan_lock`
  防止两个扫描互相踩踏。
- 同一网段在单次任务中只探测一次；结果按
  `(network_id, ip, mac)` 合并。
- 自定义范围与活动网段可以同时提交；当没有选择活动网段时，只扫描
  自定义范围（`custom_only`）。
- 扫描支持暂停、恢复、停止。暂停状态写入任务快照，恢复后继续未完成的
  主机探测；停止保留已经产生的结果。

## 6. 迁移方案

V1 的状态全部在浏览器 `localStorage`：

- 已保存的 MAC 后缀、备注、网络选择、面板尺寸、设备缓存。

V2 的处理方式：

1. **不删除、不覆盖旧 `localStorage`**。旧版“网络扫描”页面仍可读取这些
   数据，避免升级后用户丢记录。
2. V2 的设备档案从第一次真实设备清单扫描开始建立；扫描结果写入 SQLite。
3. V1 的 8 条 MAC 记录不会自动映射为 V2 设备，因为 MAC 后缀不是设备
   身份，且可能对应多台设备。用户可在“设备管理”中把对应设备设为收藏
   并填写备注。
4. 迁移不需要停机，不需要手工建表。SQLite 初始化是幂等的；已有数据库
   会按 `SCHEMA_VERSION` 检查，版本不匹配时应在发布前提供迁移脚本。
5. 卸载 Deb 会清理应用数据目录。需要保留设备档案时，先在“设置”或
   “设备管理”导出 CSV。

## 7. 导出

CSV 导出使用后端设置中的分隔符、表头开关和 UTF-8 BOM。设备导出包含
`device_id`、名称、IP、MAC、厂商、接口、网段、状态、首次/最近发现、
收藏、备注与地址历史计数；扫描历史导出包含任务范围、状态与变化统计。
