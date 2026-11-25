# Network Locator V2 第 6 步报告：MAC 定位

> 日期：2026-11-25  
> 分支：`v2/step-2-shell`（第 5 步提交 `4707552`；第 6 步提交在本分支）  
> 版本：`1.4.0`  
> 预览端口：`4185`（常规样例）、`4186`（`--bulk 120`，分页）  
> 截图：`docs/screenshots/step6/`（15 张）

## 结论

**通过（有条件）**。MAC 定位已按 V2 规范重做：完整 MAC、OUI 前缀、4 位后缀、
包含片段与厂商名查询，格式自动识别与严格校验，批量查询，内置离线 OUI
（205 个前缀）厂商识别与未知厂商明确报错，随机 MAC / 虚拟网卡标记，
结果联动设备档案与历史地址，50 条分页，空 / 加载 / 错误态，中英 × 明暗
与响应式均已本地验证。真机 TOS 回归未执行，仍是发布前阻塞项。

| 检查项 | 结果 |
| --- | --- |
| 完整 MAC 查询 | 通过 |
| OUI 前缀 / 4 位后缀 / 包含片段 | 通过 |
| 厂商名查询（内置离线 OUI） | 通过（`Apple`；未收录厂商明确报错，不猜测） |
| 自动格式识别与非法格式校验 | 通过（`AA:BB:GG` → 400，前端给出修正提示） |
| 批量查询 | 通过（每行独立结果；超过 100 行在提交前拦截） |
| 随机 MAC / 虚拟网卡标记 | 通过（本地管理位置位、VMware 等虚拟厂商） |
| 结果关联设备档案 / 历史地址 | 通过（历史 MAC 仍指向同一 `device_id`，可打开详情抽屉） |
| 每页 50 条分页 | 通过（121 条后缀匹配分 3 页，页码与总数正确） |
| 空 / 加载 / 错误态 | 通过 |
| 中文 / 英文 × 明 / 暗 | 通过（源码级 i18n 审计 0 缺失） |
| 响应式 1180 / 900 / 760 / 620 | 通过 |
| 后端 / 前端测试 | 通过（91 / 91、42 / 42） |
| 构建 x86_64 / aarch64 | 通过（SHA 见下） |
| 打包契约 | 未改动 |
| 真机 TOS 安装 / 7 页 / 扫描 / 卸载回归 | **未执行（发布前阻塞项）** |

## 1. 实现范围

后端：

- `oui.parse_query(value, mode)`：支持 `auto` / `full` / `prefix` / `suffix` /
  `any` / `vendor` 六种模式；自动识别 12 位完整 MAC、6 位 OUI、4 位后缀，
  非法字符与长度给出可本地化的明确错误。
- `VIRTUAL_VENDORS` 与 `vendor_from_query` / `prefixes_for_name`：厂商名
  查询走内置离线 OUI；未知厂商返回“未收录该厂商”，不伪造结果。
- `store.lookup_mac(query, mode, limit, offset)`：按设备聚合，
  匹配当前与历史 `device_addresses`；返回去重后的 `matched_macs` /
  `matched_addresses`、`mac_type`、`random_mac`、`virtual_adapter`、
  状态原因与 `total` / `limit` / `offset` / `has_more`。
- `GET /v2/mac/lookup` 单条查询；同一路由 `POST` 批量查询（最多 100 行），
  单行失败只标记该行 `error`，不影响其他行。实时扫描结果只在第 0 页叠加，
  并以 `status_reason_code: live_not_persisted` 明确“尚未入库”。
- `classify_query` 保留为兼容包装；5 位十六进制片段不再被静默当成 `any`，
  自动模式返回非法，显式 `any` 模式仍支持片段查询。

前端：

- MAC 定位页：输入模式说明、自动格式识别与 `aria-invalid` 校验提示、
  批量开关与逐行提示、厂商前缀说明、错误横幅、加载态、空态。
- 结果按设备展示，名称链接到设备详情抽屉；标记“已关联设备档案”、
  “随机 MAC”、“虚拟网卡”；单条查询与批量分组各自支持 50 条分页。
- 新增 `state.mac` 与 `NetworkLocatorData.API.macLookup` 批量封装；
  所有新增文案进入 `i18n.js`，英文模式不夹中文。
- 旧“我的设备”保存的 MAC 后缀与备注继续在 MAC 定位页读写同一
  `localStorage` 键，不影响既有数据。

## 2. 真实后端验证（Unix socket）

环境：`APP_DATA=/tmp/nl-step6`、`APP_SOCKET_PATH=/tmp/nl-step6.sock`，
预置 124 台设备（含 VMware 虚拟网卡与随机 MAC 样例）。

| 场景 | 结果 |
| --- | --- |
| 厂商 `Apple` | `total=1`，返回对应设备与 OUI 前缀 |
| 4 位后缀 | `total=121`；`offset=100` 第 21 页 `has_more=false` |
| 非法 `AA:BB:GG` | 400，“MAC 只能包含 0-9、A-F 以及 - : . 分隔符” |
| 随机 MAC | `random_mac=true`、`mac_type=local` |
| 厂商 `VMware` | `virtual_adapter=true` |
| 批量 `[Apple, Acme, 1B2C]` | Apple 正常、Acme 返回未收录厂商、1B2C 正常 |
| 历史 MAC / IP | 仍命中同一 `device_id`，设备档案为当前地址 |

## 3. 自检中发现并修复的问题

1. **英文模式 API 错误夹中文**：真实后端返回“未收录该厂商”等中文详情，
   英文界面显示为 “Request was not accepted: 未收录该厂商…”。
   在 `app.js apiFailure()` 中统一经 `translateMessage` 本地化。
2. **i18n 缺键**：源码审计发现自定义范围与扫描暂停相关 13 个键缺失，
   已补齐；复跑审计为 **OK（0 missing）**。
3. **超过 50 条无法翻页**：原实现只取前 50 条。改为设备级分页，
   单条与批量分组均显示页码、范围与总数。
4. **5 位十六进制被误判为片段查询**：自动模式改为明确报错，
   避免用户以为做了完整 MAC 查询。

## 4. 测试与构建

```bash
python3 -m unittest discover -s apps/tos7/backend/tests -p 'test_*.py'   # 91 / 91
node --test apps/tos7/tests/*.test.js                                  # 42 / 42
node --check frontend/{app,csv,i18n,v2-data,v2-shell,v2-pages}.js      # 通过
python3 -m compileall -q backend tools                                 # 通过
python3 build.py --platform x86_64                                     # Verification: OK
python3 build.py --platform aarch64                                    # Verification: OK
```

产物：

- `apps/tos7/dist/network-locator_1.4.0_x86_64.deb`（129510 B）
  SHA256 `469cae7dee33a1b8de529ff018081a3821f98c70c9d9e124f08a655dbed9e9b0`
- `apps/tos7/dist/network-locator_1.4.0_aarch64.deb`（129508 B）
  SHA256 `fa3238c18f3e22bc034f1b70caef55efb5fd82be1ed612cd18277cbd02807aad`

新增测试：

- 完整 / 前缀 / 后缀查询、厂商名与随机 / 虚拟标记、非法格式校验。
- 120 台设备分页与 `total` / `has_more` 计数。
- 历史地址 MAC 命中仍关联同一 `device_id`。
- 批量逐行错误、重复行忽略，以及 GET 路由的分页字段。

## 5. 截图

目录 `docs/screenshots/step6/`：

- 空闲：`zh-light-idle.png`
- 厂商结果：`zh-light-results-vendor.png`、`zh-dark-results-vendor.png`、
  `en-light-results-vendor.png`、`en-dark-results-vendor.png`
- 分页（`--bulk 120`）：`zh-light-pagination-page1.png`（1–50 / 120）、
  `zh-light-pagination-page2.png`（51–100 / 120）
- 批量：`en-light-batch.png`
- 非法格式：`en-light-invalid.png`（`AA:BB:GG`）
- 错误：`en-light-error.png`（未收录厂商 `Acme`）
- 空态：`en-light-empty.png`
- 加载：`en-light-loading.png`（延迟响应）
- 响应式：`en-light-900.png`、`en-light-760.png`、`en-light-620.png`

说明：预览数据带 `sample: true`，仅用于界面验证，不进入 Deb；
第 3 页（101–120 / 120）未单独截图，页码逻辑与第 2 页一致。

## 6. 打包契约

未改动：App ID / package `network-locator`、systemd unit
`networklocator-system`、socket `/var/api/network-locator.sock`、运行用户
`network-locator`、包内路径、默认窗口 1180×720、`build.py` 打包规则。
`dpkg-deb -f` 复核：`Package: network-locator`、`Version: 1.4.0`、
`Depends: python3 (>= 3.10), systemd`；包内 `lib/network_locator/`、
`webui.bz2`、`config.ini`、`init.d/networklocator-system.service`、
`data/`、`logs/` 均在原路径。

## 7. 未完成项 / 已知边界

1. **真机 TOS 回归未执行（发布前阻塞）**：需在 TOS 7 真机安装 Deb、
   确认服务 active、从 TOS 入口打开、走完 7 页、扫描真实网段、卸载。
   按要求未触碰审核设备 189/190，等待机器窗口。
2. **OUI 为离线子集（205 个前缀）**：未收录前缀显示“未知厂商”，
   不猜测型号；这一边界与已知问题清单一致。
3. **批量上限 100 行 / 次**：界面在提交前拦截并提示，超出需分批查询。
4. **实时扫描结果不入库**：仅在未分页的第一页叠加，并标注
   `live_not_persisted`；持久化仍依赖设备清单扫描。
5. **未单独截取 tooltip / 焦点态**：校验与可访问性属性已实现并有源码测试，
   本轮截图只覆盖视觉主路径。
6. 1081px 英文深色下设备表约 4px 内部横向滚动为既有已知边界，
   按要求本轮不处理。
7. 本阶段未打 Release、未提交审核；1.3.8 仍在审核中
   （x86_64 `b1ed1dfb-be80-4517-9f72-6021c9acd5d4`、
   aarch64 `9a55f662-b54a-4877-86a3-b4e97c7781c8`，均 `status=0`）。
