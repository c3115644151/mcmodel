# mcmodel — Minecraft 模型实装工具

把 Blockbench 工程翻译成方块资源。

工具不生产"看起来差不多"的模型。它生产两样东西：可被构建失败拦住的**不变量**，和可被人复核的**证据**。
产物（blockstates / models / textures / icons / loot / lang）只是这两者的副产品。

```
python -m mcmodel list          # 这个工具能做什么（按管线阶段分组）
python -m mcmodel doctor        # 环境是否足以跑起来
python -m mcmodel gate          # 先整批重建资源，再跑所有门
python -m mcmodel gate --no-build   # 只跑门（资源已是最新时）
python -m mcmodel run <name> -- <args>   # 跑单个命令
```

在 `tools/` 目录下运行，或用项目 venv 的解释器（门需要 Pillow）。

**60 条命令**：source 5 / build 25 / gate 23 / observe 7。`list` 里的表是权威，本文只解释为什么这样分层。

## 安装

mcmodel 不是一个能独立运行的 CLI。生成器要往 `src/main/resources/assets/<mod_id>/` 写资源，
门要读同一棵树，`jar` 与 `processResources` 跑的是 mod 工程的 Gradle 任务 —— 所以它**与一个
Minecraft mod 工程同仓**，标准接法是 submodule：

```bash
git clone --recursive https://github.com/c3115644151/pastoral-home.git
cd pastoral-home/tools
python -m mcmodel doctor
```

依赖三项，缺哪项 `doctor` 会直接报出来，不用猜：

| 依赖 | 用在哪 | 缺了会怎样 |
|---|---|---|
| Python 3.10+ 与 Pillow | 全部生成器与门 | 什么都跑不了 |
| JDK 25 + 工程里的 Gradle wrapper | `gradle:` 开头的命令（`jar`、`process-resources`） | 只有这类命令失败 |
| Node 22+ | 仅 observe 阶段（`mcpfabric/`） | 只能做静态侧，不能进游戏看 |

已存在的工程换成：

```bash
git submodule add https://github.com/c3115644151/mcmodel.git tools
git submodule update --init --recursive
```

## 六十秒上手

```bash
python -m mcmodel list                      # 60 条命令，四个阶段
python -m mcmodel gate --no-build           # 23 个门全跑，不重跑生成器
python -m mcmodel gate --no-build gate-particle   # 单跑一条门，秒级
python -m mcmodel build prepare-piano       # 只重生成一个模型的资源
python -m mcmodel shot --out build/x.png --scene scene.js --reload
```

`gate` 不带 `--no-build` 时会先重跑 19 条批处理生成器，再跑需要的门。这不是顺手做的：
"门读到了上一轮的旧产物，于是报出了一个已经修好的错"是本工具最常见的假阳性来源。

## 为什么要这个工具

Blockbench 的视口与 Minecraft 的方块渲染管线**不等价**，而且差异是静默的：

| 差异 | 后果 |
|---|---|
| 模型的 uv 空间固定 0..16，美术贴图尺寸任意 | 缩放算错，一面读成整张图或读进空白区 |
| 视口做 alpha 混合，游戏走 `ALPHA_CUTOUT 0.5` 硬裁 | 纸灯变实心砖，或变奶油砖 |
| 视口剔除近侧壳面，方块模型不按顶点序剔除 | 源里看得见的内芯，游戏里永远看不见 |
| 一个模型的所有 quad 共用一个 render type | **元素顺序就是绘制顺序**，写反了芯被壳盖住 |
| 模型与 atlas 只在启动时烘焙 | 改完模型看截图，看到的是加载遮罩 |
| 1 格 = 16 px | 4 px 的物件天然读作"小块"，与贴图精度无关 |

这六条每一条都真的让我做错一次，其中两条各错了两次。人的眼睛在小图上也不可靠——同一张 1200 px 的图里，
我把并排的两个立方体读成一个、把光照压暗的橙读成"大片米黄"。所以工具的第一职责不是生成，是**把看不见的错变成数字**。

## 三条支柱

### 1. translate — 把源文件变成资源

从 `.bbmodel` 直接生成，不手改 JSON。多格结构切成 per-cell 模型（缝平面上的面会被裁掉，所以"sliced"必须
自己声明 `RenderShape.MODEL`，否则整块隐形）。GUI 图标、item model、loot、tags、lang 同批产出。

```
python -m mcmodel import-bbmodel <source.bbmodel> <block_id>
python -m mcmodel split-cells <model.json> <out_dir> --columns 3
python -m mcmodel gen-icons <model.json>
```

### 2. gate — 把渲染语义陷阱变成断言

每个门对应一次真实失败，不是"以防万一"：

| 门 | 它挡住的那次事故 |
|---|---|
| `gate-render-semantics` | 不透明壳包住命名内芯（灯芯永远看不见）；半透明壳被排在内芯之前（奶油砖）；写了 `render_type` 却没生效 |
| `gate-slices` | 分片方块没声明 `RenderShape.MODEL`，整块隐形 |
| `gate-party-lights` | uv 缩放错、贴图只采到顶上几行、alpha 与源不一致 |
| `gate-piano-keys` | 键宽/缝隙/黑键比例漂移 0.02 px 后，键盘图案被剪切 |
| `gate-lang` | 新增方块漏了 zh_cn，游戏里显示 `block.mod.x` |
| `gate-collision` | 碰撞表与模型脱钩（改了模型忘记重算 Shapes） |
| `gate-imports` | `collision/`、`common/` 被"grep 到没人用"为由删除，而真正 import 它们的是 `from run import …` 这种经 `sys.path` 注入的写法 |

```
python -m mcmodel gate                 # 全部：先跑 19 条批处理 build 命令，再跑 23 个门
python -m mcmodel gate gate-lang       # 单个：只跑它声明的 requires，不重建整个项目
python -m mcmodel gate --no-build      # 全部门，跳过重建
```

全量跑为什么先重建：每个生成器都会重写 src 里的模型，而 `norm-light` / `norm-particles`
只清理它在 src 里看到的东西。先跑门后跑生成器，门检查的是生成器还没覆盖的旧文件——
它会在正确的断言上给出错误的结论。这条链与 `build.gradle` 的 `processResources` 依赖一致。

### 3. observe — 让"看一眼"这件事可信

这是最容易骗人的一层。截图有三个陷阱：改模型不会自动重载（模型在启动时烘焙）；重载后的 25 秒内抓到的是
加载遮罩；机位不对时画面里根本没有主体。

```
python -m mcmodel shot --out build/shots/x.png --scene build/scene.js --reload
python -m mcmodel sweep --file <generator.py> --param SHELL_ALPHA --values 100,140,180 \
    --generator '<generator.py>|--mirror' --scene build/scene.js --crop x0,y0,x1,y1 --out sheet.png
python -m mcmodel compare --source build/blockbench_source_previews/x.png --live build/shots/y.png \
    --crop x0,y0,x1,y1 --out cmp.png
```

`shot` 会等 unpaused 世界、可选重载、等渲染线程完成、量测帧的色分布，判定为遮罩就重拍并最终拒绝交付。
`sweep` 每档都重建+摆场+重载+截图，结束后恢复源文件——不会把树留在最后一个试过的值上。
`compare` 是交付前的必做一步：源视口与实机并排，附两边各自的色分布。

**离线渲染不是判据**。`preview-model` 不做 mip、不剔除背面，uv 采样也与游戏不同；它只回答"几何对不对"。

## 命令全表

`python -m mcmodel list` 输出权威列表。阶段含义：

- **source** — 读美术文件，确立构建可以依赖的事实（解析、uv 审计、源视口、贴图解码）
- **build** — 生成资源（导入、切片、烘焙、图标、归一化）
- **gate** — 断言不变量；坏构建必须在这里失败
- **observe** — 看运行中的游戏，并让这次"看"可信

## 目录

```
tools/
  mcmodel/            ← 本工具：命令表 + 分发器（不重复实现逻辑）
    registry.py       命令表，一个命令一行，说明它属于哪一阶段
    cli.py            python -m mcmodel
  deploy/             ← 具体实现脚本（98 个 .py + 3 个 .ps1），其中 60 个入口登记在命令表里
    model_sources/    美术源 .bbmodel
    IMPLEMENTATION_CONTRACT.md   实装契约：一个模型完成前必须逐条判定的跨学科决策
  collision/          ← 碰撞体层（10 个 .py）：把模型体素化、拟合、压缩成 VoxelShape
  common/             ← 共用常量（1 个 .py）
  mcpfabric/          ← 与运行中的客户端通信（截图、方块、脚本）
  mcpmod/             ← 备用桥：只在需要 UI 输入（JEI overlay、自绘界面）时才用
```

脚本不按阶段搬目录：它们被 `build.gradle` 的 50 处直接引用、被文档与彼此 import，改名即断链而收益为零。
分层的载体是 `registry.py` 与这份索引，不是文件夹。

没有登记在表里的脚本不是"待整理"，而是三种已知状态：生成器的私有实现（被上面某个命令 import）、
只跑一次的调查脚本、以及死路线留下的实现。判断一个脚本属于哪种，看 `build.gradle` 有没有引用它、
有没有别的脚本 import 它——两者皆无的不该再被调用。

## 一个模型从源文件到验收

1. `source-view` 截源视口（Blockbench 开着也能截），存 `build/blockbench_source_previews/<name>.png`
2. `inspect` 读出 cubes / 每面 uv / resolution / 贴图尺寸；`uv-audit` 确认缩放可推导
3. 写生成器（从 `.bbmodel` 生成，带 `--mirror`）
4. 写这个模型的"源差异门"：逐面 uv 与源相等、alpha=255 的 texel 逐字节相等、包围盒一致、变体数一致
5. `mcmodel gate <name>` + `processResources validateModels`
6. 写摆场脚本，`shot --scene` 拍一张，确认主体在画面里
7. 需要人裁定的常量用 `sweep` 一次扫完
8. `compare` 并排交付，请人裁定观感

判据分三层，不能跳：**数据层**（静态断言）→ **渲染语义层**（必须在游戏里看真实帧）→ **观感层**（只有人能定）。
数据层全绿而人说"不一致"时，问题一定在 2 或 3，**不要回去调 1**。

## 已知边界（工具修不了，动手前要先对齐）

- 源 uv 每面是一个纯色 tile 时，游戏只能给出纯色面；视口的层次来自 alpha 堆叠与光照。要更细必须美术重画。
- 1 格 = 16 px 决定小型物件的观感，与"贴图更粗"无关。
- Blockbench 视口剔除近侧壳面，MC 不按顶点序剔除；"看得见内芯"只能靠 alpha 或真正开孔。

## 长远方向

- **声明式模型规格**：用一份 spec 描述多格、变体、动画帧、碰撞策略，替代为每个模型手写一个生成器。
- **gate kit 抽包**：每条门写成对任意 MC mod 项目可复用的断言，而不是绑定本项目路径。
- **观测层扩展到 BER / 实体 / 自定义渲染类型**：目前只覆盖方块模型与 GUI 图标。
- **源视口基准库**：每个模型保存源视口与差异账本，回归时自动比对，不再靠人复看。
- **CI 集成**：`mcmodel gate` 作为预提交门；观察层需要客户端，留在手动阶段。

## 历史

早期路线是"一键实装"（`deploy/cli.py` + `analyzer.py` + `codegen.py`：分析模型 → 生成 Block/Entity 骨架 → 输出清单）。
它正确识别了"模型实装包含哪些学科"，但把产出定位成**代码**而不是**证据**，与现在的生成器+门路线冲突，已删除；
需要时从 git 历史取回。它留下的最有价值的产物是 `IMPLEMENTATION_CONTRACT.md`，现在是实装前的必读清单。
旧一代的 JS 工具已删除，旧实现留在仓库的 `legacy` 分支。

`collision/` 与 `common/` 一度也被这样删掉，理由是"97 个脚本里没有任何一行 import 它们"。
那个理由是错的，代价是构建链断了半个月才被发现：脚本先把目录塞进 `sys.path`，再写
`from run import deploy_collision`——模块名是**文件**，不是目录，所以按目录名 grep 永远搜不到。
现在 `gate-imports` 读 AST 而不是 grep：它按解释器的解析顺序还原每条 import，任何指向空气的
import 都会让门变红。教训留在这里，因为下次"确认没人用"还会有人想到 grep。

## 许可

MIT，见 [LICENSE](LICENSE)。
