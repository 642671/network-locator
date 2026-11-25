# Network Locator V2 启动、测试与打包

> 版本：1.4.0  
> App ID / 包名：`network-locator`  
> 架构：`x86_64`（amd64）、`aarch64`（arm64）  
> 包内路径、systemd unit、socket、运行用户保持不变

## 1. 环境要求

- Python 3.10+（后端只使用标准库，无第三方运行时依赖）
- Node.js 20+（仅前端测试）
- TOS 7.0+ NAS（真实扫描、Deb 安装与审核）
- Linux 下可用 `ip` 与 `ping` 命令
- 本地预览不需要 NAS

## 2. 本地预览

```bash
cd apps/tos7
python3 tools/preview_server.py --port 4178
```

打开 `http://127.0.0.1:4178/`。预览服务器提供示例设备和扫描结果，
所有响应带 `"sample": true`，并在界面显示“预览模式”提示；它不会进入 Deb。

## 3. 直接运行真实后端

生产环境通过 TOS 平台代理访问 Unix socket。本地联调可以直接启动：

```bash
cd apps/tos7
APP_DATA=/tmp/network-locator-data PYTHONPATH=backend python3 -m network_locator.server
```

默认 socket：`/var/api/network-locator.sock`。非 root 本地联调时可通过
测试代码或临时目录覆盖 socket 路径，不要修改包内 systemd unit。

健康检查：

```bash
curl --unix-socket /var/api/network-locator.sock http://localhost/health
```

## 4. 测试

```bash
# 后端 72 项
python3 -m unittest discover -s apps/tos7/backend/tests -p 'test_*.py'

# 前端 34 项
node --test apps/tos7/tests/frontend_csv.test.js   apps/tos7/tests/frontend_saved_macs.test.js   apps/tos7/tests/frontend_search_state.test.js   apps/tos7/tests/frontend_v2_data.test.js

# 语法
node --check apps/tos7/frontend/app.js
node --check apps/tos7/frontend/v2-pages.js
python3 -m compileall -q apps/tos7/backend
```

## 5. 构建 Deb

```bash
cd apps/tos7
python3 build.py --platform x86_64
python3 build.py --platform aarch64
```

输出：

- `apps/tos7/dist/network-locator_1.4.0_x86_64.deb`
- `apps/tos7/dist/network-locator_1.4.0_x86_64.deb.sha256`
- `apps/tos7/dist/network-locator_1.4.0_aarch64.deb`
- `apps/tos7/dist/network-locator_1.4.0_aarch64.deb.sha256`

构建脚本会校验：

- `VERSION`、`config.ini`、`DEBIAN/control`、后端 `__version__` 一致。
- 14 种语言的 `name/auth/descript` 完整。
- app id、`system_id`、包名、iframe 路径、socket、systemd unit 不变。
- 包内文件、Deb 字节确定性、SHA256。

## 6. TOS 安装

```bash
sudo dpkg -i network-locator_1.4.0_x86_64.deb
systemctl status networklocator-system.service
curl --unix-socket /var/api/network-locator.sock http://localhost/health
```

固定契约（不要修改）：

| 项目 | 值 |
| --- | --- |
| App ID / package | `network-locator` |
| systemd unit | `networklocator-system.service` |
| Socket | `/var/api/network-locator.sock` |
| 运行用户 | `network-locator` |
| 包根目录 | `/usr/local/network-locator/` |
| 数据目录 | `/usr/local/network-locator/data/` |
| 日志目录 | `/usr/local/network-locator/logs/` |

## 7. 数据位置与备份

- SQLite：`/usr/local/network-locator/data/network-locator.db`（WAL 模式）。
- 旧版 localStorage 数据保留在浏览器中，不被删除。
- 卸载前先在“设备管理”或“设置”导出 CSV；`remove`/`purge` 会清理应用数据。

## 8. 发布前检查

1. 确认版本四处一致：`VERSION`、`config.ini`、`DEBIAN/control`、
   `backend/network_locator/__init__.py`。
2. 确认 `network-locator.lang` 14 段 `release_note` 均以新版本号开头。
3. 跑完 72 + 34 项测试。
4. 构建双架构，核对 `dpkg-deb --info`、`--contents` 与 SHA256。
5. 在测试 NAS 安装，检查真实扫描、暂停/恢复、CSV、历史和主题。
6. 不要动审核设备、不要回写审核工单；未经所有者确认不要 commit/tag/push。
