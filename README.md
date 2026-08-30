# MC-Mod 模型实装工具包

通用化工具集 — 适用于**任何** Minecraft Mod 项目（NeoForge/Fabric，客户端模型实装），
不绑定单一 mod。工具自动侦测目标项目的 `mod_id` / 主包名 / 资源路径。

## 使用前提

- 目标项目是 Gradle 项目（根目录含 `build.gradle` / `gradle.properties`）
- 有 `.bbmodel`（BlockBench 导出）或已导出的 `model.json`
- BlockBench 桌面版 + MCP 插件（用于原生导出；纯 JSON 实装无需）

## 快速开始

```bash
# 1. 从目标项目根目录运行（自动侦测 mod_id/package）
python tools/common/config.py       # 预览自动侦测结果

# 2. 验证 + 修复模型
python tools/collision/validate_model.py assets/<modid>/models/block/xxx.json --fix

# 3. 生成碰撞箱（有朝向 + --facing）
python tools/collision/run.py xxx.json --facing

# 4. 一键实装（验证 + 生成 Block 类 + 部署清单）
python tools/deploy/cli.py xxx.json

# 5. 实体类（轮子/车等动态模型）
python tools/deploy/cli.py wheelbarrow.json --entity --entity-id wheelbarrow

# 6. BlockBench 原生导出（零手写转换）
python tools/tmp/bb_export.py <out_model.json>   # 需 MCP 插件已加载
python tools/tmp/bb_deploy.py <native.json> <src_model.json> <mod_id> <tex_name> [--y-shift -10]
```

## 手动指定（无法自动侦测时）

```bash
# 环境变量
MC_MOD_ID=my_mod MC_MOD_PACKAGE=com.mymod python tools/deploy/cli.py xxx.json
# 或配置中心参数（见 tools/common/config.py resolve(overrides)）
```

## 工具职责表

| 工具 | 职责 | 触发 |
|------|------|------|
| `tools/common/config.py` | 自动侦测项目参数（mod_id/package/路径） | 被其他工具 import |
| `tools/collision/validate_model.py` | 模型静态验证（UV/粒子/图标/parent/NEEDS_FACING） | --fix 自动修复 |
| `tools/collision/run.py` | 碰撞箱生成（--facing 方向模板） | 有朝向时必跑 |
| `tools/deploy/cli.py` | 一键实装入口（验证+生成+清单） | 新方块 |
| `tools/deploy/codegen.py` | 代码生成（Block/Entity/Renderer/State） | cli.py 内部 |
| `tools/deploy/split_model.py` | 模型拆分（轮子/变体去部件） | --auto-wheel/--wheel-hint |
| `tools/deploy/bb_export.py` | BlockBench MCP 原生导出 | 新模型 |
| `tools/tmp/bb_deploy.py` | 原生→src 落位+校验 | export 后 |
| `tools/deploy/gui_measure.py` | **GUI 图标测量**（等轴测正交解析，scale 精确 ±2%，ty 起点需微调） | 物品图标大小/位置 |

## 通用化硬编码检查

工具内**禁止**写死 `com.xxx` / `modid` / 特定资源路径；
一律通过 `tools/common/config.py` 的 `get_mod_id()` / `get_package()` / `resolve()` 获取。
新增工具时遵守此规则。

## 验证模板（方向变体强制项）

详见 `tools/collision/LESSONS.md` —— 完整实装 = 工具箱提示全落实：
`NEEDS_FACING` 检测 → `HorizontalDirectionalBlock` + blockstate 4方向 y 映射
（north→0/east→90/south→180/west→270）+ 碰撞箱 `rotationFor`/`Shapes.rotate`。
