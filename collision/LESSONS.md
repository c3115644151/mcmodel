# 模型实装踩坑清单 & 工具化记录

> **工作流原则**：每次部署模型遇到的 bug，先判断是否可工具化检测/修复；能工具化的立即加进 `validate_model.py` 或 `run.py`，不能工具化的记录在本文件的「待办」里。目标是「可验证的一键实装」，不重复踩坑。
>
> **这份文件现在是半个历史**。「一键实装」入口 `tools/deploy/cli.py` 连同 `analyzer.py`、`codegen.py` 已删除（理由见 [../README.md](../README.md) 的「历史」一节），凡是提到它们的方法不再可执行；碰撞箱与模型校验部分（`validate_model.py`、`generate.py`、`optimize.py`、`run.py`）仍在 `mcmodel` 的 `gate-collision` 链上使用。保留下来的原因是下表每一条都对应一次真实失败。

## 已工具化（工具会自动检测/修复）

| 问题 | 根因 | 检测/修复 | 触发场景 |
|------|------|-----------|----------|
| `Cannot compute translucency out of bounds` | `.bbmodel` resolution 非 16 / 导出 JSON 带 `texture_size` + 大 UV，MC 26.1 处理有 bug | `validate_model.py`: `BBMODEL_RESOLUTION_NONSTANDARD` / `TEXTURE_SIZE_NONSTANDARD`，`--fix` 自动去 texture_size + UV 缩放到 0~16 | BlockBench 导出 32×32 纹理模型 |
| `face_shape_rows` 因缺少纹理 PNG 崩溃 | 导出的 JSON 已写入命名空间纹理引用，但资源文件还未落位，碰撞分析器尝试读取空图像 | `face_coverage.py` 在无图像时将几何面保守视为不透明，不假设镂空；模型落位后再用真实 PNG 复核 | 新模型先导出/分析、后复制纹理 |
| 破坏粒子乱码 | `textures.particle` 指向自定义纹理，atlas UV 错位 | `CUSTOM_PARTICLE_TEXTURE`，`--fix` 改 `oak_planks`/`oak_log` | 所有 BlockBench 导出模型 |
| 物品图标是平面视图 | `display.gui` 无 rotation | `MISSING_GUI_DISPLAY` / `GUI_NO_ROTATION`，`--fix` 加 `[30,225,0]` | 所有物品图标 |
| MC 无法加载模型 | 缺 `parent` | `MISSING_PARENT`，`--fix` 设 `minecraft:block/block` | 导出 JSON |
| 元素坐标越界 | cube from/to 超出 [-16,32] | `COORD_OUT_OF_BOUNDS` | 多格/异常模型 |
| 旋转角非法 | angle 非 22.5 倍数（MC element rotation 限制） | `INVALID_ROTATION_ANGLE`，`--fix` 归整到最近 22.5 | 带旋转元素 |
| UV 越界 | 某面 UV 超出纹理尺寸 | `UV_OUT_OF_BOUNDS` | 所有模型 |
| 方向变体手写旋转 | FACING + 碰撞箱旋转代码反复手写易错 | `run.py --facing` 自动生成 `FACING`/`rotationFor`/`getShape` 旋转完整模板 | 所有有朝向的方块 |
| 多变体共用最大碰撞箱 | 多层模型（如 6 变体木柴捆）各层几何差异大却共用最大 AABB，低变体悬空 | `validate_model.py --variants N` 检测体积差异 >30% 提示分层 | 分层/变体方块 |
| 斜向元素碰撞箱盖不住 | 绕轴旋转的元素(如±22.5°斜木条)用未旋转 AABB 盖不住斜向伸出的角；沿y分段对绕Y旋转的长条无效 | `generate.py` 的 `compress_adaptive` 对旋转 cube 直接用旋转后 8 角点外接 AABB 单 box 覆盖，牺牲空气率换完整覆盖；低 box 优先 | 所有带 element rotation 的模型 |
| 面壳/斜体被错误做成空心薄壁或完全漏碰 | UV 面缺失不代表玩家应穿过该元素；绕轴倾斜也不应消失在碰撞里 | 新默认对所有正体积元素使用单个完整几何 AABB（包括开口面壳和非90度旋转件）；允许斜体有空气误占。真正零厚度的纯渲染平面默认跳过，可显式 `--include-thin` 才加最小厚度；`--exclude-shells/--exclude-rotated` 是明确排除项 | 书堆斜放书、灯笼结构侧面、装饰模型开口壳 |
| 斜体摆件产生阶梯状碰撞轮廓 | 装饰件的所有斜板未必都该成为实体；多段 AABB 会形成明显轮廓线 | 用 `--include-indices` 只选承重/支撑元素，再用 `--single-envelope` 生成一个 AABB；例如画像碰撞只取后支架，不用图片斜板堆盒 | 画像、斜靠相框、桌面摆件 |
| 空气误占率与漏碰互相抵消 | 旧指标用 `(碰撞体积-模型体积)/模型体积`，错位碰撞可能被报告为 0%；扫描范围还漏掉了模型边界外的碰撞 | `optimize.py:calc_metrics` 按体素中心分别统计误占、漏碰、覆盖与精确率；`run.py` 和部署 CLI 都输出独立指标，评估分辨率按模型尺寸限幅 | 任何碰撞箱质量评估 |
| 碰撞轮廓出现双线/相邻重叠 box | 纹理感知体素压缩会留下包含、重叠或可合并的矩形盒，Shapes.or 逐盒保留轮廓 | `generate.merge_exact_union_boxes` 仅在并集仍是完整矩形时去除包含盒、合并面接/重叠盒；不会填充 L 形空气 | 茶壶、茶杯、薄壳装饰 |
| 物品图标过大 | 跨格模型(尺寸>16)的 display.gui.scale 用默认/过大值, 物品栏显示不全 | `validate_model.py` 的 `GUI_SCALE_TOO_LARGE` 检测 span>16 且 scale>0.5, `--fix` 自动缩到 0.32 | 多方块模型(水车/晾衣架等) |
| **动态部件拆分** | 轮子等可动部件需独立模型(供渲染器旋转), 变体需去部件(避免重叠) | **新工具** `tools/deploy/split_model.py`: `--auto-wheel` 自动检测轮子(同心嵌套小cube), `--wheel-hint N,M` 精确指定, 生成 `_wheel`/`_no_wheel` | 实体类模型(独轮推车/马车) |
| **拉车实体骨架** | "位置绑定纯函数+客户端权威"+54格容器+轮子方向公式 反复手写 | ~~**新扩展** `tools/deploy/cli.py --entity`: 生成 Entity+Renderer+RenderState 三骨架~~ 该入口已删除；骨架当时是逐手写的，需要时从 git 历史取回 | 实体类模型 |

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

## 多模型碰撞复核（2026-10-26）

- `audit_java_shapes.py` 现在支持 `--include-indices` / `--exclude-indices`，装饰模型可只审计实际承重件；`--model-y-range` 和 `--model-y-offset` 用于逐层核对多格模型。
- `run.py --single-block` 明确保留单个方块状态的超高碰撞形状；`--clip-bounds y:0:32` 可把故意埋入地面的模型脚点裁到地面后，再按 y=16 切成上下层。
- 裁剪旋转立方体时，必须同时清除解析时缓存的 `corners`；否则旧旋转包围盒会绕过裁剪，让下层形状伸进上层。
- `tools/deploy/collision_profiles/recent_outdoor.json` 给近期模型声明了碰撞构造范围：花盆只审计盆体，遮阳布保持无实体碰撞；其余模型把旋转 AABB 的空气误占与漏碰分开审计。`audit_recent_outdoor_collisions.py` 会把当前 Java 形状与标准工具输出逐项比较。
- 多个相关斜体部件如果逐个 AABB 会产生密集轮廓线，可用 `collision_groups` 把一个真实组件的元素合成一个 envelope；`preview_collision_profiles.py --candidate` 可预览分组结果。profile 必须记录该选择造成的空气误占率，不能把不相干部件合成一个满块。
- 斜杆的单 AABB 可能有较高空气误占，这是轴对齐 VoxelShape 对斜体的固有限制；当前标准优先保证完整覆盖、不做阶梯盒。审计阈值应按模型结构和使用方式在 profile 中显式记录，不能把装饰叶片计入花盆碰撞，也不能把“零漏碰”翻译为“完全贴合”。

## 待反思的坑（未来遇到新 bug 记到这里）

| 日期 | 模型 | bug | 是否工具化 | 备注 |
|------|------|-----|-----------|------|
| 2026-08-08 | 储水木桶 | 水量存 BE 字段导致渲染不同步 | 否（改架构为方块状态） | 可变量优先存方块状态属性，别存 BE 字段后手动同步 |
| 2026-08-08 | 储水木桶 | BER 注册在 GAME 总线收不到 MOD 事件 | 否 | 文档化事件总线区分 |
| 2026-08-14 | 木柴捆 | texture_size+大UV 导致 translucency 越界 | 是 | 见上表 |
| 2026-08-14 | 木柴捆 | 6 变体共用最大碰撞箱 | 是 | `--variants` 检测 |
| 2026-08-14 | 木柴捆 | 斜向木柴用未旋转 AABB 盖不住 | 是 | `compress_adaptive` 旋转 cube 用外接盒 |
| 2026-08-29 | 蜂箱 | 蜜蜂不认巢 = POI 缺失, 非 tag | 是(API) | 蜜蜂找巢走 `PoiManager.getInRange(PoiTypes.BEEHIVE)`, 不认 BlockTags; 自定义蜂箱须 `ExtendPoiTypesEvent.addBlockToPoi(PoiTypes.BEEHIVE, block)` 注册全部 blockstate |
| 2026-08-29 | 蜂箱 | 碰撞箱"粗糙"= 旋转元素走外接 AABB | 是(工具, 策略已更新) | 曾使用 `segment_rotated()` 阶梯近似；当前默认对正体积斜体使用单个旋转后 AABB，允许空气误占，保留元素边界而不做碎阶梯 |
| 2026-09-30 | 提灯 | 零厚度火焰面被补成实体碰撞 | 是(工具 + 方块) | 真正 `from==to` 平面默认视觉-only；正体积栏体/面壳走完整 AABB。提灯斜提环是零厚度平面，因此不碰撞；实心连接和灯罩侧部按其几何处理 |
| 2026-08-29 | 工具链 | `--max-air` 崩溃 | 是 | 旧分段方案曾在 `scan_options` 中把 `(main, rotated)` 当作 box 列表；当前标准方案以完整 AABB 为基准，不再扫描旋转分段 |
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
