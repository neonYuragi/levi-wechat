# WSL2 本地开发

本流程使用工作区中的 TypeScript、Rust 源码和 Docker 工具脚本。CLI 在 WSL2 中运行；微信客户端和 Rust 服务在本地构建的容器中运行。宿主机上的 Cargo 用于检查、测试和生成类型，容器内使用 Dockerfile 指定的 Rust 构建器编译运行时二进制。

## 1. 环境与依赖

将仓库放在 WSL 的 Linux 文件系统中，例如 `~/github/agent-wechat`。以下命令均在仓库根目录执行。

- Docker Desktop 使用 WSL2 后端，并在 **Settings → Resources → WSL Integration** 中启用当前发行版。
- Linux 版 Node.js **>= 24.16**，pnpm **9.15.4**，版本以根目录 `package.json` 为准。
- Rust **1.93.x**，与当前 `docker/Dockerfile`、`scripts/dev-deploy.sh` 中的构建器一致。
- 本地编译依赖：

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  build-essential pkg-config libssl-dev cmake clang perl \
  sqlite3 curl ca-certificates git unzip xz-utils fonts-dejavu-core
```

尚未安装 Rust 时，使用官方 rustup 安装器：

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs -o /tmp/rustup-init.sh
sh /tmp/rustup-init.sh -y --profile minimal \
  --default-toolchain 1.93.0 --component rustfmt,clippy
. "$HOME/.cargo/env"
cargo install cargo-watch --version 8.5.3 --locked
```

`cargo-watch` 用于 `pnpm dev:check` 和 `pnpm dev:watch`。可选编辑器组件为 VS Code 的 `rust-lang.rust-analyzer`、`vadimcn.vscode-lldb`，以及 `rustup component add rust-src`。

检查当前终端：

```bash
node --version
pnpm --version
rustc --version
cargo --version
cargo watch --version
docker info --format '{{.ServerVersion}} {{.OSType}} {{.Architecture}}'
docker buildx version
```

Docker 应显示 Linux 引擎。Docker Desktop 首次将用户加入 `docker` 组后，需要从 Windows 重新打开 WSL 会话；已有 VS Code 服务下的新终端可能仍继承旧组权限。可从现有终端执行 `wsl.exe -d <发行版名称>` 开启新会话，然后重新进入仓库。

如果报 `permission denied ... unix:///var/run/docker.sock`，对比 `id -nG` 与 `getent group docker`：账号已列在 `docker` 组、但当前进程的组列表没有 `docker`，说明该会话尚未刷新组权限。可以在仓库根目录通过新 WSL 会话执行构建：

```bash
# 将 Ubuntu-26.04 替换为自己的发行版名称
wsl.exe -d Ubuntu-26.04 --cd "$PWD" -- bash -lc \
  'docker info && pnpm build:image:amd64 --debug'
```

仓库的 `devbox.json` 配置含 Colima socket，WSL2 使用 Docker Desktop 时无需进入该环境。若已有 `DOCKER_HOST` 指向 Colima，应先移除当前终端中的该设置。

## 2. 安装工作区依赖并构建 CLI

```bash
pnpm install --frozen-lockfile

# 开发 CLI / Rust 服务时，先构建共享包和 CLI
pnpm --filter @agent-wechat/cli... build
pnpm cli --help
```

当前 CLI 源码入口是 `packages/cli/src/cli.ts`，`pnpm cli` 运行其构建结果 `packages/cli/dist/cli.js`。根目录 `src/cli.ts` 不属于这条构建流程。CLI 构建会注入版本号并处理模块依赖，日常使用构建后的入口。

需要构建所有工作区包时执行 `pnpm build`。

## 3. 从本地源码构建开发镜像

```bash
# 缓存当前架构的微信 Linux 安装包
pnpm download:wechat 
dpkg-deb --field docker/wechat.deb Package Version Architecture

# WSL2 x86_64：构建包含 gdbserver 的开发镜像
pnpm build:image:amd64 --debug

# ARM64 主机对应使用：
# pnpm build:image:arm64 --debug
```

`build:image:amd64` 将本地 `packages/agent-server-rust/` 的源码、清单和迁移文件准备到构建上下文，由 `docker/Dockerfile` 编译，生成 **`agent-wechat:amd64`**。ARM64 对应生成 `agent-wechat:arm64`。

首次构建会下载 Rust、Ubuntu 基础镜像、系统依赖和 Cargo 依赖。项目服务二进制由本地源码构建。去掉 `--debug` 可构建 release 镜像。

先执行 `download:wechat`，确保 `docker/wechat.deb` 已存在；该文件由 `.gitignore` 排除，无需提交。

## 4. 启动并验证开发容器

```bash
pnpm dev
pnpm cli status
curl --fail http://localhost:6174/health
```

`pnpm dev` 使用本地架构对应的 `agent-wechat:*` 镜像，容器名为 `agent-wechat`。它会重建同名容器，并复用 `agent-wechat-data`、`agent-wechat-wechat-home` 数据卷；执行前确认同名容器就是自己的开发环境。

首次启动会在 `~/.config/agent-wechat/token` 创建访问令牌，并以只读方式挂载到容器。`docker/tools/` 挂载为容器的 `/opt/tools`，便于修改工具脚本。API 与浏览器 VNC 入口使用端口 **6174**，调试端口为 **1234**。VNC 保持仓库默认的只读模式。

登录并执行只读查询：

```bash
pnpm cli auth login
pnpm cli auth status
pnpm cli chats list
```

使用独立测试账号验证行为修改。发送消息前确认目的聊天；本流程不自动发送测试消息。

`wx up` / `pnpm cli up` 会选择发布镜像；仓库现有 `docker-compose.yml` 也配置了发布镜像。本地源码开发使用上面的 `build:image:*` 与 `pnpm dev` 流程。

## 5. 日常修改

### Rust 服务

```bash
# WSL 中快速检查；也可以使用 pnpm dev:check 持续检查
cargo check --locked --manifest-path packages/agent-server-rust/Cargo.toml

# 在 Docker 构建器中编译本地源码，更新指定开发容器
pnpm dev:deploy --container agent-wechat

# 或持续监听源码，自动编译、更新开发容器
pnpm dev:watch --container agent-wechat
```

部署脚本默认构建 debug 二进制，重启容器内的服务进程，保留微信进程和数据卷。第一次编译较慢；后续使用命名卷缓存 Cargo 注册表和编译产物。`dev:watch` 会部署代码，因此只对已确认的开发容器使用。

用于容器运行的二进制应通过上述 Docker 构建器生成。WSL Ubuntu 与镜像 Ubuntu 的系统库版本可能不同，宿主机 `target/debug` 二进制不一定能在运行时镜像中执行。

修改导出的 Rust 请求/响应类型后：

```bash
pnpm generate-types
pnpm --filter @agent-wechat/cli... build
```

检查 `packages/shared/src/types/generated/` 的变更，并随对应 Rust 类型一起提交。

### CLI / 共享 TypeScript 代码

```bash
pnpm --filter @agent-wechat/cli... build
pnpm cli --help
pnpm cli status
```

也可以在单独终端运行 `pnpm build:watch` 持续构建工作区。已经配置为指向本地构建结果的 `wx` 命令同样使用更新后的代码。

### 容器工具或镜像配置

修改 `docker/tools/` 后，开发容器通过挂载读取这些脚本。修改 Dockerfile、系统依赖或 entrypoint 后，需要重新构建镜像，再用 `pnpm dev` 重建开发容器。

## 6. 测试与调试

```bash
pnpm build
pnpm typecheck
pnpm --filter @agent-wechat/cli test
pnpm --filter @agent-wechat/agent-wechat test
pnpm --filter @agent-wechat/wechaty-puppet test
cargo test --locked --manifest-path packages/agent-server-rust/Cargo.toml
```

单元测试不能证明实际微信 UI 行为。涉及选聊、发送、录音等修改时，另在本地构建的镜像和测试账号上验证实际客户端行为。

Rust 远程调试需要 debug 镜像和已安装的 CodeLLDB 扩展。先运行 `pnpm dev:deploy --container agent-wechat`，使 `.vscode/launch.json` 所需的 `target/debug-remote/agent-server` 符号文件存在，再检查服务 PID：

```bash
docker exec agent-wechat pgrep -a -x agent-server
# 将 <PID> 替换为上一步查到的服务 PID
docker exec -u root -d agent-wechat gdbserver --attach 0.0.0.0:1234 <PID>
```

随后在 VS Code 中启动已有的 **Attach to Container (Rust)** 配置。

## 7. 日志、停止与恢复

```bash
docker logs --tail 100 -f agent-wechat
docker stop agent-wechat
docker start agent-wechat
pnpm cli status
```

普通停止/启动复用当前开发容器；需要应用新镜像时才执行 `pnpm dev` 重建。保留数据卷及备份，日常开发无需删除数据卷。

提交前检查 `git diff`，排除令牌、账号数据、构建产物和本地网络配置。用户可见的功能或包变更应按 `AGENTS.md` 添加 changeset。
