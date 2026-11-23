# Changelog

## 1.3.5 - 2026-11-23

### 新增

- 设备总表和我的设备表格新增「网段」列，显示每条设备记录所属的 CIDR 网段，
  悬停可看到接口名；表头可点击按网段排序，筛选框也支持按网段或接口过滤。

### 修复

- 默认窗口改为 1040×760，默认打开时工作区约 730px，完整显示 IP、MAC、网段、
  状态和逐行操作列，无需横向滚动。
- 「我的设备」为空时的「添加第一个」按钮悬浮背景过窄，现补足内边距。
- 移除窗口左上角误显示的六个拖拽点。该标识原计划放在右下角，但
  `calc(var(--window-frame) + 7px)` 把无单位的 `0` 与长度相加导致整条声明无效，
  元素退回到静态位置，因此出现在左上角。右下角 20×20 的安全角仍然保留。

### 验证

- 后端单元测试与前端 Node 测试。
- 双架构 Deb 构建，核对版本、包内路径与 SHA256。

## 1.3.4 - 2026-11-23

### 整改

- 按 TerraMaster 审核意见补充包内隐私政策，并把 `config.ini` 的 `help` 指向公开的 `docs/PRIVACY.md`。
- 卸载（remove 与 purge）时清理本应用目录、Unix socket、systemd unit 以及服务用户，不删除 `/var/api` 或用户数据盘。
- `Depends` 仅保留 TOS 上更稳妥的 `python3 (>= 3.10), systemd`，不再声明可能在应用中心在线安装时无法满足的 `iproute2` / `iputils-ping`。扫描仍使用系统已有的 `ip` 与 `ping`。
- `postinst` 增加 `adduser` 回退、用 Python 解压 `webui.bz2` 的备选路径，并将服务就绪等待延长到 45 秒，降低应用中心安装后服务未就绪的风险。

### 验证

- 后端单元测试与包契约测试。
- 连续构建两次，`x86_64` 与 `aarch64` 的 `.deb` 字节分别保持一致，并核对 `dpkg-deb --info/--contents` 与 SHA256。


## 1.3.3 - 2026-11-22

### 修复

- 修复 1.3.2 在默认窗口宽度下，「复制 IP / 复制 MAC / 导出 CSV」与筛选框重叠的问题。
- 默认窗口改为 860×720，宽度贴近 TOS 应用中心。
- 在较窄的默认宽度下，标题区按钮在标题内换行，不再压住筛选框。

### 验证

- 后端单元测试按新的默认宽度、紧凑断点和防重叠样式更新并通过，前端 Node 测试一并通过。
- 双架构 Deb 连续构建两次，校验版本、包内路径和 SHA256。


## 1.3.2 - 2026-11-22

### 修复

- 去掉浅色主题内侧灰蓝内框，应用内容贴到窗口边缘，贴近 TOS 内置应用。
- 浅色背景改为纯白，不再使用灰蓝渐变。
- 默认窗口宽度从 1120 调整为 1040，高度仍为 720。

### 验证

- 后端单元测试按新内框、底色和窗口宽度更新并通过，前端 Node 测试一并通过。
- 双架构 Deb 连续构建两次，校验版本、包内路径和 SHA256。


## 1.3.1 - 2026-11-22

### 修复

- 表头改为不透明实底，滚动时第一行数据不再透过表头显示。
- 在应用内侧增加内框，让 18px 圆角卡片在左侧等边缘可见，但不改变 TOS 右上角按钮位置。
- 将「MAC 后缀定位」「我的设备」「设备总表」等粗体标题再次缩小为 14px / 12px，字重 650。

### 验证

- 后端单元测试增加表头不透明、内框和标题栏位置断言，并与前端 Node 测试一并通过。
- 双架构 Deb 连续构建两次，校验版本、包内路径和 SHA256。


## 1.3.0 - 2026-11-22

### 变更

- 界面改为白色磨砂玻璃与蓝色主按钮，去掉青绿主题。
- 去掉 MAC 后缀输入行后的删除按钮，空的多余输入行在失焦后自动收起。
- 设备总表和我的设备中，点击 IP 在新标签页打开该地址。
- 点击 MAC 地址即可复制，并给出已复制反馈。
- 操作列的「复制 IP」「复制 MAC」与表头「操作」居中对齐。
- 窗口右下角增加拖拽放大标识。

### 验证

- 后端单元测试与前端 Node 测试按新界面契约更新并通过。
- 双架构 Deb 连续构建两次，校验版本、包内路径和 SHA256。


## 1.2.1 - 2026-11-21

### 修复

- 采用绿色主题和更简洁的分区布局。
- 「我的设备」与「设备总表」拆分为两个独立分区，设备总表标题紧贴其列表。
- 设备总表改为勾选、IP 地址、MAC 地址、状态、操作列，支持行内复制 IP 和 MAC。
- 筛选栏显示当前网段 chips，状态统一显示为可达、延迟、本机、陈旧等中文标签。
- 面板名称统一为「我的设备」。
- 所有 tooltip 默认横向显示，靠近视口右侧时不再被压缩成竖排文字。
- 刷新「我的设备」时在列表顶部显示一条带扫光的「正在刷新当前 IP…」加载行，
  按钮同步显示「刷新中…」，去掉重复文案和独立进度线，完成后给出提示。
- 更新应用图标为地球、定位标记和扫描角标组合，标题栏和 favicon 同步。
- 修复左右拖拽变窄后标题和数量逐字换行、头部操作挤压的问题。
- 收窄侧边栏与工作区之间的拖拽边框，MAC、状态、操作列内容居中。

## 1.2.0 - 2026-11-21

### 新增

- 新增「我的设备」面板：默认展示用户保存的 MAC 后缀与当前 IP，最多保存 8 条。
- 每条保存项支持用途说明、当前 IP、在线状态、最后发现时间；设备总表刷新后自动更新 IP。
- 点击 IP 复制；旁边的打开图标在新标签页打开 `http://IP/`。
- 同一 4 位后缀命中多台设备时全部列出并提示后缀碰撞；缓存完整 MAC 用于优先匹配。
- 点击保存项打开只读详情，点「编辑」才进入编辑弹窗；支持删除和「用于搜索」。
- 保存项与用途说明在刷新、关闭浏览器和应用升级后保留。

### 保留

- 原有 MAC 搜索、持续搜索、设备总表、筛选排序、CSV 导出保持不变；没有保存记录的用户仍按原方式使用。

### 验证

- 新增 Node 测试覆盖保存项清洗、去重、8 条上限、备注长度、后缀匹配、多台命中、完整 MAC 消歧和最近发现字段。
- 后端包契约测试增加保存键、面板元素、备注长度和纯文本渲染断言。

## 1.1.0 - 2026-11-21

### 变更

- 应用命名为网络定位（Network Locator），使用全新应用标识 `network-locator`。
- 包名、systemd unit、Unix socket、运行用户和包内安装路径全部切换为
  `network-locator` / `networklocator-system` / `/var/api/network-locator.sock`
  / `/usr/local/network-locator/`；TOS 将其视为新应用，而不是旧版升级。
- 前端本地存储键由 `lanMacFinder.*` 迁移为 `networkLocator.*`，避免与旧应用共存时
  互相读取搜索状态、网段选择和缓存。
- 14 种语言的名称与更新说明同步为新身份；功能行为与 1.0.017 一致。

### 验证

- 后端单元测试与前端 Node 测试按新身份更新并通过。
- 双架构 Deb 构建通过包契约校验；包内路径、unit、socket、用户和版本均为新值。

## 1.0.017 - 2026-11-06

### 修复

- 移除“MAC 后四位”标签行的吸顶与半透明底色，添加按钮改为独立的实心小按钮，
  不再与标签行共用一条横贯面板的色带。
- 结果表头改为不透明背景，表格滚动时行内容不再透过表头与首行重叠；
  深色主题同样保持不透明。

### 验证

- 包契约测试锁定标签行不再 sticky、不再带背景，表头必须使用 `--surface-solid`
  不透明背景。
- 通过完整后端单元测试、Node.js 前端测试和 JavaScript 语法检查；并在
  1120×720、1280×900、800×720 下验证标签行无背景、输入框宽度恒定、表头不透明。

## 1.0.016 - 2026-11-06

### 优化

- “添加一个 MAC”按钮固定在“MAC 后四位”标签同一行，位于输入框列表上方；
  输入框增减时按钮位置不再移动。
- 标签行在输入框较多时固定在面板顶部，滚动列表时添加按钮始终可见。

### 修复

- 输入框数量跨过滚动阈值时，输入框宽度不再因滚动条出现或消失而缩小、变大。
  列表始终预留滚动条空间，并补偿相应内边距以保持原有宽度。

### 验证

- 包契约测试确认添加按钮位于输入框列表之前、标签行使用 sticky、列表预留滚动条空间。
- 通过完整后端单元测试、Node.js 前端测试和 JavaScript 语法检查；并在
  1120×720、1280×900 和 800×720 下验证 1/3/8 个输入框时宽度恒定。

## 1.0.015 - 2026-11-06

### 优化

- 新增 MAC 输入框的移除叉号移入输入框内部右侧，不再占用输入框外的空间。
  样式与首个输入框的清除按钮统一：透明背景、悬停淡红提示、按下反馈和禁用态。
- 多行输入框改为由布局自然保持等宽，移除首行为对齐而额外预留的 42px 空间。

### 验证

- 包契约测试改为校验移除按钮位于输入框内部，并确认旧的占位规则已移除。
- 通过完整后端单元测试、Node.js 前端测试、JavaScript 语法检查和无头浏览器布局验证。

## 1.0.014 - 2026-11-06

### 新增

- 重新打开应用时先恢复上次的网段信息和设备总表，再在后台快速校验。网段未变化
  时立即完成加载；出现新网段时自动追加到列表并提示，失效网段会被移除。
- 网段校验失败或服务暂时不可用时保留上次网段，不再清空界面。
- 持续搜索恢复时会复用 5 秒内刚校验过的网段结果，减少重复读取。

### 修复

- 多个 MAC 输入框现在与首个输入框等宽；只有一行时仍保持整行宽度。
- 停止搜索后不再显示“已查 0 / 10 轮”。未完成当前轮时显示“第 N / 10 轮未完成”，
  尚未开始过轮次时显示“未开始查找”。

### 验证

- 增加网段/设备缓存签名、顺序无关比较和停止状态文案的前端回归测试，
  并补充缓存键、校验状态和等宽布局的包契约测试。
- 通过完整后端单元测试、Node.js 前端测试和 JavaScript 语法检查。

## 1.0.013 - 2026-11-06

### 修复

- 持续搜索不再一直停在“第 1 / 10 轮”且无法结束。旧逻辑在任一轮找到设备后重置
  未命中计数，导致已找到的结果不断触发下一轮；现在每个搜索目标独立累计轮次，
  已找到的目标立即结束，只有仍未找到的目标继续使用各自的 10 轮预算，全部目标
  解析完成后停止轮询。
- 网段发现改为直接计算主机数量，不再为大前缀网段展开完整地址列表；同时跳过
  未指定、回环、链路本地和组播地址，避免扫描任务在异常网段上长时间卡住。

### 新增

- 支持同时搜索多个 MAC 后缀。界面默认只有一个输入框，可点击“添加一个 MAC”
  逐个增加，最多 8 个，重复后缀会被拒绝，新增的每一行都可单独移除。
- 一次扫描同时匹配所有目标，匹配结果新增“匹配后缀”列，并显示每个目标的
  查找状态和目标汇总。搜索结束后会分别报告每个 MAC 找到的设备数量，或明确
  提示该 MAC 在 10 轮后仍未找到。

### 验证

- 增加多目标轮次独立累计、全部目标完成后停止、结果合并去重、多后缀匹配和
  大网段主机计数的后端与前端回归测试。
- 通过完整后端单元测试、Node.js 前端测试和 JavaScript 语法检查。

## 1.0.012 - 2026-11-05

### 新增

- 持续搜索改为最多执行 10 轮：连续 10 轮没有匹配结果后自动停止轮询，并在状态区、
  结果为空提示和消息条中明确显示“轮询查找结束，最终没有找到”，不再无限重试。
  找到结果时轮次计数归零；轮次进度会随搜索意图一起保存，刷新页面后继续累计。
- 设备总表和匹配结果中的 IP 地址现在可点击，直接在新标签页打开 `http://<IP>/`
  访问该设备；IP 链接使用独立焦点样式，不影响整行选择、双击复制 MAC 和回车复制。

### 验证

- 增加 10 轮上限、重复任务去重、命中后归零以及 IPv4 跳转地址校验的前端单元测试。
- 通过完整后端单元测试、Node.js 前端测试和 JavaScript 语法检查。

## 1.0.011 - 2026-11-04

### 修复

- 同一广播域由多块物理或 OVS 网卡重复暴露时，设备总表和匹配结果现在按“扫描网段、IP、MAC”合并为一条；合并时优先保留 `LOCAL`、`REACHABLE`、`DELAY`、`PROBE`、`STALE` 中状态更强的一条，并继续保留各接口自身不同的 `LOCAL` 地址。
- 对相同扫描网段只执行一次主机探测，进度和总主机数按实际唯一网段计算，避免多个接口重复扫完整网段导致耗时和结果成倍增加。
- 同步全部 14 种语言的应用商店发布说明到当前版本，并增加发布说明版本契约测试，避免升级后仍展示旧版本说明。

### 验证

- 增加同网段多接口去重、状态优先级、单次探测和不同网段隔离的回归测试。
- 通过完整后端单元测试与前端 Node.js 测试。

## 1.0.010 - 2026-11-03

### 新增

- 设备总表和 MAC 匹配结果新增即时筛选，可按 IP、MAC、网卡、扫描网段或状态
  检索；多个关键词以空格分隔时要求全部命中，MAC 查询兼容 `-` 和 `:` 分隔符。
- 表头支持按网卡、扫描范围、IP、MAC 和状态升序或降序排序；IP 与扫描网段按
  数值顺序排序，而不是按字符串顺序排序。
- 表格工具栏显示筛选后的设备数与总数；筛选无结果时提供明确空状态和“清除筛选”
  入口。
- CSV 导出改为导出当前筛选和排序后的可见记录，与界面上看到的内容保持一致。

### 修复

- 筛选或排序时保留仍可见的选中设备；筛选后不可见的选中项会安全清除，避免
  继续复制旧记录。
- 表格工具栏和空状态纳入现有 TOS 明暗主题、窄窗口与键盘操作布局。
- 发布说明版本号同步到当前版本，修正 `1.0.009` 发布时仍显示 `1.0.008` 的问题。

## 1.0.009 - 2026-11-03

### 新增

- 多网段环境默认全选所有活动物理网段，并可在“活动网段”列表中只勾选一个或
  多个网段执行扫描。
- 网段选择同时作用于 MAC 后缀扫描和设备总表探测，并会随页面刷新和持续搜索
  自动恢复。
- `/scan/start` 与 `/devices/scan` 新增可选 `network_ids` 参数；未传时保持
  旧版全网段行为，空选择会被拒绝，失效网段不会回退为全网段扫描。

### 修复

- 修复多网段环境下无法限定扫描范围、后台可能同时探测不需要网段的问题。
- 在扫描运行期间锁定网段选择，避免界面选择与后台任务范围不一致。
- 同名 MAC 后缀正在扫描但请求范围不同时返回 409，避免误报为已加入当前任务。

## 1.0.008 - 2026-10-30

- Add CSV export for the current device overview or MAC match table, with a
  stable column order, UTF-8 BOM for Excel, `Ctrl+E`, and disabled state when
  there is nothing to export.
- Escape commas, quotes, and line breaks and neutralize spreadsheet formula
  injection without altering numeric values.
- Share the CSV implementation with the Windows build and add Node.js unit
  tests for default columns, escaping, formulas, and filenames.
- Follow the explicit result-count and export workflow common to LAN scanners
  such as Angry IP Scanner while keeping all data on the NAS.


## 1.0.007 - 2026-10-24

- Actively probe every scannable host when loading or refreshing the device
  overview instead of showing only the NAS's partially populated neighbor
  cache.
- Return the complete probed device inventory through a dedicated endpoint,
  including the NAS's own physical interface.
- Serialize inventory scans with suffix searches and disable conflicting
  controls while the inventory scan is running.
- Use a longer timeout for full-network inventory scans while retaining the
  shorter timeout used by interactive search requests.

## 1.0.006 - 2026-10-24

- Keep incomplete MAC input neutral while the field is focused, while still
  rejecting more than four digits or more than five characters with a
  separator immediately.
- Move the complete `AA-BB / AA:BB / AABB` format guidance into the input
  placeholder and expose validation state through `aria-invalid`.
- Make both application boundaries draggable by mouse, touch, and keyboard,
  with minimum sidebar, workspace, scan-panel, and network-panel sizes.
- Turn a submitted non-empty suffix into a persistent continuous search that
  refreshes networks, keeps the latest match while the next cycle runs, shows
  the no-match state when a completed cycle returns no devices, retries after
  NAS or API interruptions, and resumes after a WebUI reload.
- Add request timeouts, backoff for recoverable service failures, and explicit
  stop, clear, login-required, and scan-conflict handling.

## 1.0.005 - 2026-10-22

- Give the packaged SVG icon a version-derived modification time so TOS
  navigation cache-busts the URL instead of showing an older icon.
- Strengthen the liquid-glass visual system with richer background gradients,
  lower-opacity blurred surfaces, specular borders, and translucent controls.
- Keep the improved glass treatment readable in both TOS light and dark themes.

## 1.0.004 - 2026-10-22

- Move the theme control out of the TOS host title-bar hit area so clicking it
  always toggles the application theme.
- Initialize the application theme from the TOS `themeMode` value so the host
  window controls and application colors use the same light or dark baseline.
- Add a Copy IP action for the selected device row.
- Reserve space for the bottom-right resize handle so device counts no longer
  overlap it.
- Make the application icon fill its SVG viewBox so navigation and App Center
  render it at the same visual size as system icons.

## 1.0.003 - 2026-10-22

- Reserve a wider host-control safe area in the title bar so TOS minimize,
  maximize, and close controls no longer overlap application actions.
- Make the bottom resize-safe corner transparent and remove the footer's
  right-side spacing so status data sits against the workspace edge.
- Clearing the MAC input or pressing the search-reset action now immediately
  restores the unfiltered device overview.
- Preserve the user's original suffix casing in scan status messages while
  continuing to normalize only the matching value.
- Include each physical interface's own MAC in the device overview and scan
  results with a distinct `LOCAL` state, fixing searches for the NAS's own MAC.

## 1.0.002 - 2026-10-22

- Preserve the exact case typed by the user while keeping MAC suffix matching
  case-insensitive.
- Show the current neighbor table as the default device overview on the right;
  after a search, show only matching devices and provide a back-to-overview
  action.
- Remove the outer content gaps and card-like margins so the sidebar, workspace,
  results table, and footer sit flush against the host edges.
- Replace the navigation icon with a simpler magnifier/network glyph and remove
  the small plus badge that became unreadable at navigation-bar size.

## 1.0.001 - 2026-10-21

- First TOS 7 release.
- Discover routed physical IPv4 interfaces and construct bounded scan ranges.
- Run host probing in a background scan job without blocking the WebUI.
- Read Linux neighbor records and match the normalized last four MAC characters.
- Add stop, refresh, result selection, double-click copy, and keyboard copy.
- Add a liquid-glass WebUI with custom tooltips, light/dark themes, responsive
  sizing, and a TOS-compatible resize-safe corner.
- Ship deterministic x86_64 and aarch64 Deb packages, checksums, tests, and
  GitHub Actions packaging.
