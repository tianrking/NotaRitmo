# 部署与迁移

## WSL开发

当前开发机项目路径：

```text
/home/user/meeting-agent-platform
```

服务器或新开发机使用仓库名作为目录：

```bash
git clone https://github.com/tianrking/NotaRitmo.git
cd NotaRitmo
```

项目使用独立 Compose 名称、网络、数据卷和端口，不停止现有 ASR、LiteLLM、
Grafana、Prometheus 或 Loki。

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
docker compose logs -f api worker
make test
make lint
make smoke
```

需要图谱时：

```bash
docker compose --profile graph up -d
```

## 数据位置

PostgreSQL 和 Neo4j 数据卷应留在 Linux ext4。大量原始音频应迁往独立 ext4 数据盘、
NAS 或 S3，不应无限增长在当前 D 盘 WSL VHDX 中。

## 迁移到Linux服务器

1. 推送 Git 提交和应用镜像。
2. 在服务器复制 `.env.example` 并写入真实密钥。
3. 使用 `pg_dump`/`pg_restore` 迁移 PostgreSQL。
4. 使用 `mc mirror` 迁移 MinIO。
5. Graphiti 图谱可重建；如保留则使用 Neo4j dump/restore。
6. 运行 `alembic upgrade head`。
7. 只向公网开放反向代理后的 Meeting API。
8. 完成导入、检索、音频跳转、删除传播和权限冒烟测试。

不要复制运行中的 PostgreSQL 数据目录，也不要把密钥写入镜像或 Git。

## 生产化差异

开发Compose使用 Temporal auto-setup。正式生产应将 PostgreSQL、对象存储和
Temporal持久化独立管理，并为API/Worker设置资源限制、备份、TLS、审计和告警。
