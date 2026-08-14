# MC Model Deploy Toolkit

> 从 BlockBench 模型到 Minecraft 方块的一键部署工具链 —— 自动检测类型、验证实装问题、生成代码与碰撞箱。

把 BlockBench 导出的模型扔进游戏，不应该再反复踩这些坑：
- ❌ UV 越界导致 `Cannot compute translucency out of bounds`，模型直接不渲染
- ❌ `textures.particle` 指向自定义纹理，破坏粒子变成乱码色块
- ❌ 物品栏图标是平面正视图而不是 3D 等轴测
- ❌ 多方块结构破坏一格后其余格残留、碰撞箱不跟着旋转
- ❌ 斜向元素的碰撞箱盖不住斜角、变体方块共用最大碰撞箱导致悬空穿模
- ❌ 每次手写 FACING、rotationFor、isCenter、tick 填充、拆除联动……

本工具把这些**踩过的坑全部自动化**：分析模型类型 → 验证问题 → 自动修复 → 生成 Block 类和碰撞箱 → 输出待办清单。

---

## 快速开始

### 零参数智能部署（推荐）

```bash
python deploy/cli.py path/to/model.json
```

一条命令自动完成：
1. **分析**模型是单格 / 多方块 / 多变体 / 含旋转
2. **验证** 9 类实装问题，自动修复可修复项
3. **生成**对应的 Block 类 Java 代码（多方块含中心判定/tick填充/拆除联动）
4. **输出**剩余手动步骤清单（注册、语言、loot 表等）

```
$ python deploy/cli.py clothesline.json
============================================================
模型: clothesline.json
类型: 多方块 3×2×1
包围盒: x[-9.7,25.7] y[0,32] z[6.3,9.7]
元素: 5, 旋转: 否, 变体: 1
待处理: 缺parent
============================================================

[验证]
  🔧 自动修复 3 项:
     ✓ 已设 parent: minecraft:block/block
     ✓ 已将 particle 改为 minecraft:block/oak_planks
     ✓ 已添加 display.gui 等轴测视角

[代码生成] ClotheslineBlock.java
  --- Java 代码 ---
  public class ClotheslineBlock extends HorizontalDirectionalBlock {
      public static final IntegerProperty LAYER = IntegerProperty.create("layer", 0, 1);
      public static final IntegerProperty POS = IntegerProperty.create("pos", 0, 2);
      ...
      // isCenter / getStateForPlacement / tick 填充 / affectNeighborsAfterRemoval 拆除联动

============================================================
部署清单 (还需手动完成):
  ☐ 注册方块: ModBlocks.CLOTHESLINE (...)
  ☐ 注册物品 / 创造标签 / 双语语言
  ☐ blockstate / item model / loot 表
  ☐ 碰撞箱: python tools/collision/run.py --facing 替换 SHAPES
============================================================
```

### 单独生成碰撞箱

```bash
python collision/run.py model.json --facing
```

自动检测单格/多格，斜向元素用旋转外接 AABB 单 box 覆盖，生成带四朝向旋转的 Java 代码。

---

## 工具架构

```
deploy/                  # 智能部署入口（推荐）
├── cli.py               # 零参数入口: 分析→验证→修复→生成→清单
├── analyzer.py          # 模型分类器（单格/多方块/多变体/旋转）
└── codegen.py           # 按类型生成 Block 类（简单/多方块模板）

collision/               # 碰撞箱与验证（cli 内部复用，也可单独用）
├── run.py               # 一键生成碰撞箱（--facing 生成旋转模板）
├── parse_model.py       # .bbmodel / model JSON 解析、旋转角点计算
├── generate.py          # 体素化合并、斜向元素外接盒
├── multiblock.py        # 跨格模型按格子切割
├── optimize.py          # 按 box 数/空气率约束选最优分段
├── validate_model.py    # 9 类实装问题检测 + 自动修复
├── visualize.py         # 三视图叠加验证
└── LESSONS.md           # 踩坑清单与工作流原则
```

### 设计原则

- **零参数智能默认**：analyzer 自动判断模型类型和最优参数，不需要记忆 `--seg-count`、`--res` 等。高级选项仍保留。
- **可插拔验证器**：每踩一个新坑，加一个检测函数到 `validate_model.py`，主流程不用改。
- **生成而非提示**：多方块的中心判定、tick 填充、拆除联动不只是警告，直接生成完整代码。
- **复用而非重写**：deploy 层调用 collision 层成熟的解析/生成逻辑。

---

## 自动检测的问题

| 问题 | 根因 | 自动修复 |
|------|------|---------|
| `translucency out of bounds` | texture_size 非 16 + 大 UV，MC 26.1 处理有 bug | ✅ 去 texture_size + UV 缩放 |
| 破坏粒子乱码 | `textures.particle` 指向自定义纹理 | ✅ 改为原版纹理 |
| 物品图标平面 | `display.gui` 无旋转 | ✅ 加等轴测视角 |
| 图标过大 | 跨格模型 scale 过大 | ✅ 缩到 0.32 |
| 非法旋转角 | angle 非 22.5 倍数 | ✅ 归整 |
| 缺 parent | 模型无法加载 | ✅ 补 `minecraft:block/block` |
| 斜向碰撞箱盖不住 | 未旋转 AABB 盖不住斜角 | ✅ 旋转外接盒 |
| 多变体共用最大碰撞箱 | 各层几何差异大却共用 AABB | ⚠️ 提示分层 |
| 多方块残留渲染 | 破坏一格不拆除其他格 | ✅ 生成拆除联动代码 |

---

## 多方块支持

当模型水平方向跨出 0~16（如 3 格宽的水车、晾衣架），工具自动识别为多方块并生成：

- `LAYER` / `POS` blockstate 属性
- `isCenter()` 中心格判定
- `getStateForPlacement` 空间检查
- `setPlacedBy` + `tick` 自动填充辅助格
- `getRenderShape` 辅助格 `INVISIBLE`
- `affectNeighborsAfterRemoval` 破坏任意一格拆除整个结构
- 按格子切割的碰撞箱占位

垂直方向超出 16（如高背椅、高木桶）是**单格高模型**，不算多方块——模型向上延伸但只占一个放置格。

---

## 要求

- Python 3.8+（仅标准库，无第三方依赖）
- 目标游戏：Minecraft 26.1+ / NeoForge（blockstate 与渲染 API）
- 模型来源：BlockBench 导出的 Java Block/Item JSON 或 `.bbmodel`

---

## 工作流原则

> 每次部署模型遇到 bug，先判断能否工具化检测/修复；能则立即加进工具并记录到 `collision/LESSONS.md`。

目标是**可验证的一键实装**——重复踩过的坑不应再需要人工记忆。

---

## License

MIT
