# Windows 与 WSL 开发说明

本项目的主工作树在 WSL，不在 Windows 盘符目录。

## 目录对应关系

WSL Linux 路径：

    /home/user/meeting-agent-platform

Windows 资源管理器可访问的 UNC 路径：

    \\wsl.localhost\Ubuntu-24.04-sglang\home\user\meeting-agent-platform

在 Windows VS Code 中推荐使用 Remote - WSL 打开 Linux 目录。不要把
F:\\crypt_omg 当作本项目的主工作树；它是 Windows 侧的其他工作区，不能替代
上面的 WSL checkout，也不要把两个目录之间手工复制当作同步方式。

## 用 VS Code 开发

1. 安装 VS Code 的 Remote - WSL 扩展。
2. 在 VS Code 中执行 WSL: Connect to WSL。
3. 选择发行版 Ubuntu-24.04-sglang。
4. 使用 File: Open Folder 打开：

       /home/user/meeting-agent-platform

5. 在 VS Code 的集成终端确认：

       pwd
       # /home/user/meeting-agent-platform

也可以从 WSL 终端打开：

    cd /home/user/meeting-agent-platform
    code .

此方式让编辑器运行在 Windows，代码、Python 和测试运行在 WSL，项目只有一份。

## 运行当前会议记忆基线

进入核心模块：

    cd /home/user/meeting-agent-platform/04-meeting-memory/baseline

运行完整离线测试：

    python3 -m unittest discover -s . -p 'test_*.py' -v

使用新的模块化编排入口（默认）：

    python3 run_fixture.py --implementation modular

回归旧的 MemoryStore 路径：

    python3 run_fixture.py --implementation legacy

输出评测报告：

    python3 run_fixture.py \\
      --implementation modular \\
      --output /tmp/fixture-modular.json

默认流程完全离线，不需要 API Key、模型下载、PostgreSQL 或 Docker。

运行研究版常驻 HTTP 服务（外部系统提交 TranscriptBundle 并查询）：

    cd /home/user/meeting-agent-platform/04-meeting-memory
    python3 api_server.py --host 127.0.0.1 --port 8090 --db ./data/meeting-memory.sqlite3

接口契约、curl 示例、租户参数、重启行为和动态十场 Fixture 验收见
`../API_USAGE.md`。

## Windows 原生运行与 WSL 运行的区别

当前 baseline 只使用 Python 标准库，理论上可以复制到 Windows checkout
后用 py -3.11 运行。但这不是本项目的主开发方式，会产生两份代码并可能导致
Fixture、Git 和依赖状态不一致。

推荐始终在 Remote-WSL 终端运行：

    python3 -m unittest discover -s . -p 'test_*.py' -v

后续接入 PostgreSQL、pgvector、MinIO、Temporal 或本地模型时，统一使用
WSL2/Docker 的服务环境；Windows 原生 Python 只作为兼容性检查，不作为生产
运行环境。

## 当前验证边界

已经验证：

- 10 场固定会议、60 个 Transcript 片段、18 个 Claim。
- 单会议 Artifact、跨会议检索、当前/历史状态、证据引用、no-answer 和租户过滤。
- MeetingMemoryService 的 Extractor、Repository、Retriever、Answerer、LLMProvider
  注入边界。
- modular 与 legacy runner 的输出计数和指标一致。
- 当前模块完整回归测试全部通过（36 tests，包含 HTTP 异步/幂等/租户/重启测试）。
- 离线评测指标：no-answer accuracy 1.0、平均会议召回 0.9236、平均证据召回
  0.9167。

尚未在这个基线中验证：

- 真实 SaaS LLM 质量、费用和网络重试。
- PostgreSQL/pgvector 持久化、并发和数据库级租户 RLS。
- MinIO 音频播放链路、生产 Go API、Docker Compose 和生产部署；当前提供的是
  Python 标准库研究版 HTTP API，不等同于生产服务。
- 真实 ASR 输出的噪声、说话人漂移和时间戳误差。

因此 WSL/Windows 说明只解决开发入口；核心项目的生产依赖仍需按后续模块
逐项替换和评测。
