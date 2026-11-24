# 变更记录

按仓库版本记录；mod 工程侧的改动记在 mod 仓库。

## v1.0.0 — 2026-11-25

工具独立成仓的第一个正式版本。

**能力**

- 命令表 59 条，四个阶段：source 5 / build 25 / gate 22 / observe 7。
  `python -m mcmodel list` 是唯一文档，`deploy/test_command_registry.py` 保证它描述的是磁盘现状。
- 22 个门，每条对应一次真实踩过的事故：分片模型漏声明 `RenderShape.MODEL` 会整块消失、
  模型 alpha 不声明会被涂成实心、跨格 uv 被镜像、生成器不重跑导致门报出已经修好的错。
- `gate` 默认先重跑 19 条批处理生成器，再跑需要的门。

**独立成仓**

- 从 mod 仓库 `git subtree split` 出来，mod 侧改为 submodule 引用；
  旧一代 JS 工具与 `collision/`、`common/` 一并移除（97 个脚本零 import），历史留在 `legacy` 分支。
- `deploy/audit_model_uv_sources.py` 的源路径改为相对自身文件，独立 clone 与 mod 内两种布局都成立。

**门面**

- `README.md`：定位、三条支柱、命令全表、安装、六十秒上手、已知边界、长远方向、许可。
- `LICENSE`（MIT）、`.github/workflows/gates.yml`（push 跑不依赖 mod 工程的静态门）、
  仓库 description 与 topics、release v1.0.0。
