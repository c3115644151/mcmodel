# 模型实装踩坑清单 & 工具化记录

> **工作流原则**：每次部署模型遇到的 bug，先判断是否可工具化检测/修复；能工具化的立即加进 `validate_model.py` 或 `run.py`，不能工具化的记录在本文件的「待办」里。目标是「可验证的一键实装」，不重复踩坑。

## 已工具化（工具会自动检测/修复）

| 问题 | 根因 | 检测/修复 | 触发场景 |
|------|------|-----------|----------|
| `Cannot compute translucency out of bounds` | `.bbmodel` resolution 非 16 / 导出 JSON 带 `texture_size` + 大 UV，MC 26.1 处理有 bug | `validate_model.py`: `BBMODEL_RESOLUTION_NONSTANDARD` / `TEXTURE_SIZE_NONSTANDARD`，`--fix` 自动去 texture_size + UV 缩放到 0~16 | BlockBench 导出 32×32 纹理模型 |
| 破坏粒子乱码 | `textures.particle` 指向自定义纹理，atlas UV 错位 | `CUSTOM_PARTICLE_TEXTURE`，`--fix` 改 `oak_planks`/`oak_log` | 所有 BlockBench 导出模型 |
| 物品图标是平面视图 | `display.gui` 无 rotation | `MISSING_GUI_DISPLAY` / `GUI_NO_ROTATION`，`--fix` 加 `[30,225,0]` | 所有物品图标 |
| MC 无法加载模型 | 缺 `parent` | `MISSING_PARENT`，`--fix` 设 `minecraft:block/block` | 导出 JSON |
| 元素坐标越界 | cube from/to 超出 [-16,32] | `COORD_OUT_OF_BOUNDS` | 多格/异常模型 |
| 旋转角非法 | angle 非 22.5 倍数（MC element rotation 限制） | `INVALID_ROTATION_ANGLE`，`--fix` 归整到最近 22.5 | 带旋转元素 |
| UV 越界 | 某面 UV 超出纹理尺寸 | `UV_OUT_OF_BOUNDS` | 所有模型 |
| 方向变体手写旋转 | FACING + 碰撞箱旋转代码反复手写易错 | `run.py --facing` 自动生成 `FACING`/`rotationFor`/`getShape` 旋转完整模板 | 所有有朝向的方块 |
| 多变体共用最大碰撞箱 | 多层模型（如 6 变体木柴捆）各层几何差异大却共用最大 AABB，低变体悬空 | `validate_model.py --variants N` 检测体积差异 >30% 提示分层 | 分层/变体方块 |
| 斜向元素碰撞箱盖不住 | 绕轴旋转的元素(如±22.5°斜木条)用未旋转 AABB 盖不住斜向伸出的角；沿y分段对绕Y旋转的长条无效 | `generate.py` 的 `compress_adaptive` 对旋转 cube 直接用旋转后 8 角点外接 AABB 单 box 覆盖，牺牲空气率换完整覆盖；低 box 优先 | 所有带 element rotation 的模型 |
| 物品图标过大 | 跨格模型(尺寸>16)的 display.gui.scale 用默认/过大值, 物品栏显示不全 | `validate_model.py` 的 `GUI_SCALE_TOO_LARGE` 检测 span>16 且 scale>0.5, `--fix` 自动缩到 0.32 | 多方块模型(水车/晾衣架等) |

## 尚未工具化（每次手动注意）

这些问题目前工具无法自动检测，部署时手动检查：

1. **破坏掉落数量**：分层方块（雪层/蛋糕/木柴捆）需根据 state 掉落 N+1 个物品。需在方块类 override `playerWillDestroy` 或用 loot function。验证器只看模型，不知道掉落逻辑。
2. **交互逻辑正确性**：右键叠层/取回/投入的逻辑（手持物品检测、shift 区分、创造模式不消耗）需手动写和测。
3. **旧存档 BE 兼容**：移除/重命名 BlockEntity 后，旧存档的块实体会报 `Unknown registry key`。开发期新建世界即可；发布版需保留兼容或提供迁移。
4. **方向不对称模型的旋转视觉**：碰撞箱用 `Shapes.rotate` 正确旋转，但模型本身是否视觉对称、旋转后是否穿模需肉眼确认。
5. **blockstate 覆盖完整**：24/32 个 state 组合是否都写全（漏一个就 Missing model）。可考虑未来加脚本校验 blockstate JSON 的 variant 完整性。
6. **多方块结构拆除联动**：多方块（水车/晾衣架 3×N）破坏一格时必须 override `affectNeighborsAfterRemoval`，遍历拆除其余同类型格（`destroyBlock(p,false)` 不掉物品），否则残留渲染/碰撞。参照 `WaterWheelBlock`/`ClotheslineBlock`。中心格判定要与默认 state 一致（LAYER/POS）。

## 一键实装检查清单（部署新方块时跑一遍）

```bash
# 新工具(推荐): 零参数智能入口, 自动分析类型+验证+生成Block类
python tools/deploy/cli.py <model.json> [--name ClassName]

# 或分步:
# 1. 从 BlockBench 导出/转换模型后，验证单个模型
python tools/collision/validate_model.py <model.json> --fix

# 2. 生成碰撞箱（有朝向加 --facing，多变体加 --variants 检查）
python tools/collision/run.py <model.json> --facing
python tools/collision/validate_model.py <model_0.json> --variants 6

# 3. 编译 + 跑 GameTest 确认无回归
./gradlew build

# 4. 进游戏肉眼确认：图标 3D、放置朝向、碰撞箱贴合、破坏粒子、掉落
```

## 待反思的坑（未来遇到新 bug 记到这里）

| 日期 | 模型 | bug | 是否工具化 | 备注 |
|------|------|-----|-----------|------|
| 2026-08-08 | 储水木桶 | 水量存 BE 字段导致渲染不同步 | 否（改架构为方块状态） | 可变量优先存方块状态属性，别存 BE 字段后手动同步 |
| 2026-08-08 | 储水木桶 | BER 注册在 GAME 总线收不到 MOD 事件 | 否 | 文档化事件总线区分 |
| 2026-08-14 | 木柴捆 | texture_size+大UV 导致 translucency 越界 | 是 | 见上表 |
| 2026-08-14 | 木柴捆 | 6 变体共用最大碰撞箱 | 是 | `--variants` 检测 |
| 2026-08-14 | 木柴捆 | 斜向木柴用未旋转 AABB 盖不住 | 是 | `compress_adaptive` 旋转 cube 用外接盒 |
| 2026-08-14 | 木柴捆 | 方向变体+碰撞箱旋转反复手写 | 是 | `--facing` 生成模板 |
