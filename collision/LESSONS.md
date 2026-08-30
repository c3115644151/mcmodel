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
| **动态部件拆分** | 轮子等可动部件需独立模型(供渲染器旋转), 变体需去部件(避免重叠) | **新工具** `tools/deploy/split_model.py`: `--auto-wheel` 自动检测轮子(同心嵌套小cube), `--wheel-hint N,M` 精确指定, 生成 `_wheel`/`_no_wheel` | 实体类模型(独轮推车/马车) |
| **拉车实体骨架** | "位置绑定纯函数+客户端权威"+54格容器+轮子方向公式 反复手写 | **新扩展** `tools/deploy/cli.py --entity`: 生成 Entity+Renderer+RenderState 三骨架 (26.1 API, 标注跨版本适配点) | 实体类模型 |

## 实体类模型经验（2026-08-22 推车沉淀）

**为什么实体类比方块难工具化**：
- 方块实装是**静态**问题（UV/坐标/父模板），工具可检测
- 实体类含**运行时动态**（渲染同步/物理手感/牵引发散），无法静态检测，只能沉淀"已验证的方案骨架"

**已验证的可复用骨架**（直接抄, 别重造）:
- 渲染: ItemModelResolver 管线 + 轮子分离 + 枢轴=质心-0.5
- 物理: 位置绑定纯函数 + 客户端权威(isLocalClientAuthoritative)
- 容器: ContainerEntity 接口 + ChestMenu.sixRows(免自定义Screen)
- 轮子方向: 局部+Z世界=(sin(yaw), -cos(yaw))

**跨版本提醒**: 上述骨架 API 绑定 MC 26.1。跨版本时替换 `[版本适配]` 标记段, 物理思路/结构不变。

## 尚未工具化（每次手动注意）

这些问题目前工具无法自动检测，部署时手动检查：

1. **破坏掉落数量**：分层方块（雪层/蛋糕/木柴捆）需根据 state 掉落 N+1 个物品。需在方块类 override `playerWillDestroy` 或用 loot function。验证器只看模型，不知道掉落逻辑。
2. **交互逻辑正确性**：右键叠层/取回/投入的逻辑（手持物品检测、shift 区分、创造模式不消耗）需手动写和测。
3. **旧存档 BE 兼容**：移除/重命名 BlockEntity 后，旧存档的块实体会报 `Unknown registry key`。开发期新建世界即可；发布版需保留兼容或提供迁移。
4. **方向不对称模型的旋转视觉**：碰撞箱用 `Shapes.rotate` 正确旋转，但模型本身是否视觉对称、旋转后是否穿模需肉眼确认。
5. **blockstate 覆盖完整**：24/32 个 state 组合是否都写全（漏一个就 Missing model）。可考虑未来加脚本校验 blockstate JSON 的 variant 完整性。
6. **多方块结构拆除联动**：多方块（水车/晾衣架 3×N）破坏一格时必须 override `affectNeighborsAfterRemoval`，遍历拆除其余同类型格（`destroyBlock(p,false)` 不掉物品），否则残留渲染/碰撞。参照 `WaterWheelBlock`/`ClotheslineBlock`。中心格判定要与默认 state 一致（LAYER/POS）。

## 一键实装检查清单（部署新方块时跑一遍）

> **完整实装的定义**：工具层运行时所提示的一切都正确且标准部署进游戏。
> 以下每一步都是强制项——工具能自动化的绝不手写，工具提示的必须全部落实。

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

**强制项（工具提示必须全落实，否则不算完整实装）**：
1. **方向变体**：模型视觉不对称（旗/把手偏侧/非对称元素）→ 必须 `extends HorizontalDirectionalBlock`
   + blockstate facing 4 方向 `y` 映射（标准：north→0, east→90, south→180, west→270，参照 spinning_wheel.json）
   + 碰撞箱 `rotationFor` + `Shapes.rotate` 随 FACING 旋转
2. **碰撞箱贴合**：getShape/getCollisionShape 用元素几何（工具 run.py 生成），不能固定长方形硬编码
3. **变体状态**：blockstate 完整覆盖 N 状态 × facing 组合（漏一个 = Missing model）
4. **工具产物即标准**：`run.py --facing`/`cli.py` 输出的代码就是项目标准写法，直接采用不手改映射

## 待反思的坑（未来遇到新 bug 记到这里）

| 日期 | 模型 | bug | 是否工具化 | 备注 |
|------|------|-----|-----------|------|
| 2026-08-08 | 储水木桶 | 水量存 BE 字段导致渲染不同步 | 否（改架构为方块状态） | 可变量优先存方块状态属性，别存 BE 字段后手动同步 |
| 2026-08-08 | 储水木桶 | BER 注册在 GAME 总线收不到 MOD 事件 | 否 | 文档化事件总线区分 |
| 2026-08-14 | 木柴捆 | texture_size+大UV 导致 translucency 越界 | 是 | 见上表 |
| 2026-08-14 | 木柴捆 | 6 变体共用最大碰撞箱 | 是 | `--variants` 检测 |
| 2026-08-14 | 木柴捆 | 斜向木柴用未旋转 AABB 盖不住 | 是 | `compress_adaptive` 旋转 cube 用外接盒 |
| 2026-08-29 | 蜂箱 | 蜜蜂不认巢 = POI 缺失, 非 tag | 是(API) | 蜜蜂找巢走 `PoiManager.getInRange(PoiTypes.BEEHIVE)`, 不认 BlockTags; 自定义蜂箱须 `ExtendPoiTypesEvent.addBlockToPoi(PoiTypes.BEEHIVE, block)` 注册全部 blockstate |
| 2026-08-29 | 蜂箱 | 碰撞箱"粗糙"= 旋转元素走外接 AABB | 是(工具) | `compress_adaptive` 旧版对 ±22.5° 斜檐用外接盒(空气大); 新增 `segment_rotated()` 沿最优轴分段阶梯, 薄元素(<3单位)兜底外接盒, 默认即分段并主碰撞 |
| 2026-08-29 | 工具链 | `--max-air` 崩溃 | 是 | `scan_options` 未解包 `compress_adaptive` 新返回的 `(main, rotated)` 元组 → `_box_vol` 收到 tuple 崩溃; 需求模式须 `skip_rotated_decor=False` 评估分段空气率 |
| 2026-08-14 | 木柴捆 | 方向变体+碰撞箱旋转反复手写 | 是 | `--facing` 生成模板 |
| 2026-08-22 | 独轮推车 | 负尺寸元素转正+UV镜像(误当bug) | 是(教训) | **负尺寸是合法特性**，WaterBarrel 也有且正常；转正反而破坏。见 [[wheelbarrow-rendering-lesson]] |
| 2026-08-22 | 独轮推车 | ItemStack 在渲染器构造器 new (组件未绑定) | 是(教训) | 渲染器构造期不能 new ItemStack/ModItems.get()，须延迟到 extractRenderState，否则黑屏 |
| 2026-08-22 | 独轮推车 | ItemTransform 末尾 translate(-0.5) 致枢轴偏 | 是(教训) | 渲染轮子绕质心旋转时，枢轴取 `质心-0.5` 抵消 ItemTransform 的 -0.5 平移 |
| 2026-08-22 | 独轮推车 | 丰收变体渲染两个轮子重叠 | 是(工具) | full 模型含轮子 elem；需 `full_no_wheel` 去轮子再叠独立动轮。`split_model.py --wheel-hint` |
| 2026-08-22 | 独轮推车 | 轮子转动方向南北反(遗留) | 是(公式) | 投影公式局部+Z世界方向 = `(sin(yaw), -cos(yaw))` 不是 `(sin, +cos)`；`YP(180-yaw)` 后 cos 取负。已验证四朝向 |
| 2026-08-22 | 独轮推车 | 拉车"跟随/紧贴/物理"手感往返失败 | 是(教训) | **位置绑定纯函数+客户端权威**是平滑正解；物理直觉不能建模物理；须完整复刻成熟mod。见 [[wheelbarrow-pull-mechanic-lesson]] |
| 2026-08-23 | 信箱 | BB face UV 语义是 [u1,v1,u2,v2] 非 [x,y,w,h] | 是(工具) | 手写转换把 [0,38,7,40] 当 x,y,w,h 导致 y+h=78 越界；实为 u1..v2 四坐标。`bb_deploy.py` 只做元数据+y-shift，不碰 UV |
| 2026-08-23 | 信箱 | BB 原生导出自带 texture_size+16空间UV | 是(工具) | MC 26.1 对 texture_size>16 有 bug；去 texture_size 但 **UV 已是 16 空间不要缩放**（validate --fix 会误缩 → 双重缩放） |
| 2026-08-23 | 信箱 | BB 网格 y=0 视口底部 vs MC 模型 y=0 地面 | 是(工具) | BB 建模样板悬空需 `--y-shift -N` 让柱底落地；歪/浮空是坐标系问题非模型问题 |
| 2026-08-23 | 信箱 | 嵌套元素(内壳)导致闪烁 | 是(教训) | 三重嵌套 cube 内部面重叠闪烁；若内壳非必要(实心方块)删除 elem |
| 2026-08-23 | 信箱 | scheduleTick 清晨窗口内排1tick → 每清晨必触发 | 是(教训) | 窗口内反复掷骰(2000次)≈必中；应**始终排"下个清晨0点"**每个清晨只掷骰一次 |
| 2026-08-23 | 信箱 | getDefaultClockTime 与 /time set 同轴 | 是(参考) | MC 26.1 时间 API: `getDefaultClockTime%24000`，0=上午6点(清晨)，10000=下午；GameTest `helper.setTime()` 验证 |
| 2026-08-23 | 信箱 | Jade @WailaPlugin 注解注册 | 是(工具) | `@WailaPlugin(modid)` + `IBlockComponentProvider` + `getUid()`；编译需 `compileOnly ":Jade:"` |

