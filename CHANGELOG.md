# 变更记录

按仓库版本记录；mod 工程侧的改动记在 mod 仓库。

## v1.0.1 — 2026-11-25

**补回被误删的碰撞层**

- `collision/`（10 个 .py）与 `common/`（1 个 .py）回到仓库。v1.0.0 把它们当成死代码删掉，依据是
  "97 个脚本零 import"——而真实调用写的是 `sys.path.insert(.../collision)` 之后的
  `from run import deploy_collision`，模块名是文件不是目录，按目录名 grep 永远搜不到。
  代价是 mod 的 `processResources` 直接 `ModuleNotFoundError`。
- 重写 `run.deploy_collision` / `measure_collision` / `run.clip_cubes_to_bounds`，新增
  `generate.merge_exact_union_boxes`、`parse_model.filter_collision_cubes`、`audit_java_shapes.read_shape`
  （解析 `Shapes.or`/`Box.box`/`Shapes.box`/`.move()`/算术参数/常量递归）。
- 测量口径统一为**两侧都体素化、两侧都裁到 0..16 格**：倾斜件按真实薄片计，而不是它的大外接盒。
  判据是工具自己的候选必须能被自己的审计判绿——AABB 口径下候选自己都有 0.2–0.4% 的漏。
- `deploy/collision_profiles/recent_outdoor.json` 的 air/miss 上限按新口径重新标定，每条都写了
  重测日期与理由（telescope 600→800 / miss 0.1→1.0、a_frame 1.6→110）。
- 删除 `deploy/export_blockbench_assets.py`：它 import 的 `mcp_client` 早在 `tmp/` 清理时消失，
  现代替路径是 `mcpfabric/bb_mcp.mjs export_model`。

**新的门**

- `gate-imports`（`deploy/test_python_imports.py`）：读 AST 还原每条 import，指向空气就红。
  命令表 59→**60 条**，门 22→**23 个**。
- `deploy/test_entryway_models.py` 的 air 上限 35→220，理由写进断言旁：两像素板材的包络盒
  天然回吐 2.6 倍体积，35 是旧口径下的数字。

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
