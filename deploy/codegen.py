#!/usr/bin/env python3
"""
多方块代码生成器 - 检测到水平跨格模型时, 生成完整 Block 类。

生成内容:
- LAYER/POS state 属性
- 中心格判定 isCenter()
- getStateForPlacement 检查空间
- setPlacedBy + tick 填充辅助格
- affectNeighborsAfterRemoval 拆除联动
- getRenderShape 辅助格隐形
- 按格子切割的碰撞箱

参照项目 WaterWheelBlock / ClotheslineBlock 最佳实践。
"""
import os
import math
import sys

# 通用配置 (从项目自动侦测 mod_id/package; 任何 mod 项目可用)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'common'))
import config as _cfg


def _pkg(suffix, override=None):
    """主包名 + 子包后缀; override 显式指定时用它"""
    if override:
        return override
    base = _cfg.get_package() or 'com.example.mod'
    return f'{base}.{suffix}'


def split_cells(bounds):
    """把模型按格子切割, 返回 {(cx,cy): [box]}。
    bounds: [x0,y0,z0,x1,y1,z1]"""
    x0, y0, z0, x1, y1, z1 = bounds
    cells = {}
    cx0 = int(math.floor(x0 / 16))
    cx1 = int(math.floor((x1 - 0.001) / 16))
    cy0 = int(math.floor(y0 / 16))
    cy1 = int(math.floor((y1 - 0.001) / 16))
    for cx in range(cx0, cx1 + 1):
        for cy in range(cy0, cy1 + 1):
            cells[(cx, cy)] = (cx, cy)
    return cells, (cx0, cy0), (cx1, cy1)


def generate_multiblock_class(class_name, analysis, package=None):
    package = package or _pkg('block')
    """生成多方块 Block 类 Java 代码"""
    bounds = analysis['bounds']
    cells, (cx0, cy0), (cx1, cy1) = split_cells(bounds)
    cells_x = analysis['cells'][0]
    cells_y = analysis['cells'][1]

    # 中心格: 模型原点所在格 (x=0~16, y=0~16 的格子)
    center_cx = 0  # 放置位置对应的格 (x:0~16)
    center_cy = 0

    return f'''package {package};

import com.mojang.serialization.MapCodec;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.util.RandomSource;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.world.level.BlockGetter;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.HorizontalDirectionalBlock;
import net.minecraft.world.level.block.RenderShape;
import net.minecraft.world.level.block.Rotation;
import net.minecraft.world.level.block.state.BlockBehaviour;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.StateDefinition;
import net.minecraft.world.level.block.state.properties.IntegerProperty;
import net.minecraft.world.phys.shapes.CollisionContext;
import net.minecraft.world.phys.shapes.Shapes;
import net.minecraft.world.phys.shapes.VoxelShape;
import org.jspecify.annotations.Nullable;

/**
 * {class_name} - 多方块 ({cells_x}格宽×{cells_y}格高), 由 deploy 工具自动生成。
 * 中心格渲染完整模型, 其余格隐形带碰撞箱。破坏任意一格拆除整个结构。
 */
public class {class_name} extends HorizontalDirectionalBlock {{
    public static final MapCodec<{class_name}> CODEC = simpleCodec({class_name}::new);
    public static final IntegerProperty LAYER = IntegerProperty.create("layer", 0, {cells_y - 1});
    public static final IntegerProperty POS = IntegerProperty.create("pos", 0, {cells_x - 1});

    // TODO: 用 tools/collision 生成每格碰撞箱后替换
    private static final VoxelShape SHAPE = box(0, 0, 0, 16, 16, 16);

    public {class_name}(BlockBehaviour.Properties properties) {{
        super(properties);
        this.registerDefaultState(this.stateDefinition.any()
                .setValue(FACING, Direction.NORTH)
                .setValue(LAYER, {center_cy})
                .setValue(POS, {center_cx}));
    }}

    @Override
    protected MapCodec<? extends HorizontalDirectionalBlock> codec() {{ return CODEC; }}

    @Override
    protected void createBlockStateDefinition(StateDefinition.Builder<Block, BlockState> builder) {{
        builder.add(FACING, LAYER, POS);
    }}

    @Override
    protected RenderShape getRenderShape(BlockState state) {{
        return isCenter(state) ? RenderShape.MODEL : RenderShape.INVISIBLE;
    }}

    private boolean isCenter(BlockState state) {{
        return state.getValue(LAYER) == {center_cy} && state.getValue(POS) == {center_cx};
    }}

    private static int[] rotateOffset(int dx, int dz, Direction facing) {{
        return switch (facing) {{
            case EAST -> new int[]{{-dz, dx}};
            case SOUTH -> new int[]{{-dx, -dz}};
            case WEST -> new int[]{{dz, -dx}};
            default -> new int[]{{dx, dz}};
        }};
    }}

    @Override
    public BlockState getStateForPlacement(BlockPlaceContext context) {{
        Direction facing = context.getHorizontalDirection().getOpposite();
        BlockPos pos = context.getClickedPos();
        Level level = context.getLevel();
        for (int dy = 0; dy < {cells_y}; dy++) {{
            for (int dx = {cx0}; dx <= {cx1}; dx++) {{
                int[] r = rotateOffset(dx, 0, facing);
                if (!level.getBlockState(pos.offset(r[0], dy, r[1])).canBeReplaced(context)) return null;
            }}
        }}
        return this.defaultBlockState().setValue(FACING, facing);
    }}

    @Override
    public void setPlacedBy(Level level, BlockPos pos, BlockState state, @Nullable LivingEntity placer, ItemStack stack) {{
        super.setPlacedBy(level, pos, state, placer, stack);
        if (level.isClientSide() || !isCenter(state)) return;
        level.scheduleTick(pos, this, 1);
    }}

    @Override
    protected void tick(BlockState state, ServerLevel level, BlockPos pos, RandomSource random) {{
        if (!isCenter(state)) return;
        Direction facing = state.getValue(FACING);
        for (int dy = 0; dy < {cells_y}; dy++) {{
            for (int dx = {cx0}; dx <= {cx1}; dx++) {{
                if (dx == {center_cx} && dy == {center_cy}) continue;
                int[] r = rotateOffset(dx, 0, facing);
                BlockPos p = pos.offset(r[0], dy, r[1]);
                if (level.getBlockState(p).canBeReplaced()) {{
                    level.setBlock(p, state.setValue(LAYER, dy).setValue(POS, dx - {cx0}), 18);
                }}
            }}
        }}
    }}

    @Override
    protected VoxelShape getShape(BlockState state, BlockGetter level, BlockPos pos, CollisionContext ctx) {{
        Rotation rot = switch (state.getValue(FACING)) {{
            case EAST -> Rotation.CLOCKWISE_90;
            case SOUTH -> Rotation.CLOCKWISE_180;
            case WEST -> Rotation.COUNTERCLOCKWISE_90;
            default -> Rotation.NONE;
        }};
        return rot == Rotation.NONE ? SHAPE : Shapes.rotate(SHAPE, rot.rotation());
    }}

    @Override
    protected VoxelShape getCollisionShape(BlockState state, BlockGetter level, BlockPos pos, CollisionContext ctx) {{
        return getShape(state, level, pos, ctx);
    }}

    @Override
    protected void affectNeighborsAfterRemoval(BlockState state, ServerLevel level, BlockPos pos, boolean movedByPiston) {{
        Direction facing = state.getValue(FACING);
        for (int dy = 0; dy < {cells_y}; dy++) {{
            for (int dx = {cx0}; dx <= {cx1}; dx++) {{
                int[] r = rotateOffset(dx, 0, facing);
                BlockPos p = pos.offset(r[0], dy, r[1]);
                if (!p.equals(pos) && level.getBlockState(p).is(this)) {{
                    level.destroyBlock(p, false);
                }}
            }}
        }}
        super.affectNeighborsAfterRemoval(state, level, pos, movedByPiston);
    }}
}}
'''


def generate_simple_class(class_name, analysis, package=None):
    package = package or _pkg('block')
    """生成单格方块 Block 类 (带 FACING 朝向 + 碰撞箱)"""
    has_facing = True  # 默认四朝向
    return f'''package {package};

import com.mojang.serialization.MapCodec;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.world.level.BlockGetter;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.HorizontalDirectionalBlock;
import net.minecraft.world.level.block.Rotation;
import net.minecraft.world.level.block.state.BlockBehaviour;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.StateDefinition;
import net.minecraft.world.level.block.state.properties.BlockStateProperties;
import net.minecraft.world.level.block.state.properties.EnumProperty;
import net.minecraft.world.phys.shapes.CollisionContext;
import net.minecraft.world.phys.shapes.Shapes;
import net.minecraft.world.phys.shapes.VoxelShape;

/**
 * {class_name} - 单格方块, 由 deploy 工具自动生成。
 * 四朝向放置, 碰撞箱随朝向旋转。
 */
public class {class_name} extends HorizontalDirectionalBlock {{
    public static final MapCodec<{class_name}> CODEC = simpleCodec({class_name}::new);
    public static final EnumProperty<Direction> FACING = BlockStateProperties.HORIZONTAL_FACING;

    // TODO: 用 tools/collision/run.py --facing 生成碰撞箱后替换
    private static final VoxelShape SHAPE_BASE = box(0, 0, 0, 16, 16, 16);

    private static Rotation rotationFor(Direction facing) {{
        return switch (facing) {{
            case EAST -> Rotation.CLOCKWISE_90;
            case SOUTH -> Rotation.CLOCKWISE_180;
            case WEST -> Rotation.COUNTERCLOCKWISE_90;
            default -> Rotation.NONE;
        }};
    }}

    public {class_name}(BlockBehaviour.Properties properties) {{
        super(properties);
        this.registerDefaultState(this.stateDefinition.any().setValue(FACING, Direction.NORTH));
    }}

    @Override
    protected MapCodec<? extends HorizontalDirectionalBlock> codec() {{ return CODEC; }}

    @Override
    protected void createBlockStateDefinition(StateDefinition.Builder<Block, BlockState> builder) {{
        builder.add(FACING);
    }}

    @Override
    public BlockState getStateForPlacement(BlockPlaceContext context) {{
        return this.defaultBlockState().setValue(FACING, context.getHorizontalDirection().getOpposite());
    }}

    @Override
    protected VoxelShape getShape(BlockState state, BlockGetter level, BlockPos pos, CollisionContext ctx) {{
        Rotation rot = rotationFor(state.getValue(FACING));
        return rot == Rotation.NONE ? SHAPE_BASE : Shapes.rotate(SHAPE_BASE, rot.rotation());
    }}

    @Override
    protected VoxelShape getCollisionShape(BlockState state, BlockGetter level, BlockPos pos, CollisionContext ctx) {{
        return getShape(state, level, pos, ctx);
    }}
}}
'''


def generate(analysis, class_name):
    """根据分析结果选择代码生成器"""
    if analysis['kind'] == 'multiblock':
        return generate_multiblock_class(class_name, analysis)
    else:
        return generate_simple_class(class_name, analysis)


# ============================================================================
# 实体类代码生成 (独轮推车经验沉淀) — 版本适配说明:
#   本模板的 API 绑定 MC 26.1 (NeoForge 26.1.2)。
#   跨版本时只需替换 [版本适配] 标记段的 API 名称, 物理思路/结构不变。
#   已验证的 26.1 API: EntityRenderState/SubmitNodeCollector/ItemModelResolver/
#   EntityReference/isLocalClientAuthoritative/ChestMenu.sixRows/ValueOutput
# ============================================================================

def generate_entity_class(class_name, entity_id, package=None, mod_id=None):
    package = package or _pkg('entity')
    mod_id = mod_id or (_cfg.get_mod_id() or 'example_mod')
    """生成"拉车实体 + 容器"骨架 (位置绑定纯函数 + 客户端权威 + 54格容器)。
    class_name: 实体类名 (如 WheelbarrowEntity)
    entity_id: 注册 id (如 wheelbarrow)
    基于独轮推车最终验证的物理方案, 见 LESSONS.md 2026-08-22 条目。
    """
    return f'''package {package};

import {mod_id}.registry.ModItems;
import net.minecraft.network.syncher.EntityDataAccessor;
import net.minecraft.network.syncher.EntityDataSerializers;
import net.minecraft.network.syncher.SynchedEntityData;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.tags.DamageTypeTags;
import net.minecraft.util.Mth;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.damagesource.DamageSource;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.EntityReference;
import net.minecraft.world.entity.EntityType;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.MoverType;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.gamerules.GameRules;
import net.minecraft.world.level.storage.ValueInput;
import net.minecraft.world.level.storage.ValueOutput;
import net.minecraft.world.phys.Vec3;
import org.jspecify.annotations.Nullable;

import java.util.Optional;

/**
 * [{class_name}] - 可拉/可推/可骑乘 + 容器。
 * 物理方案 (验证于独轮推车): 位置绑定纯函数 + 客户端权威, 平滑不抖。
 *
 * [版本适配] 26.1: EntityReference/ValueOutput 序列化。跨版本时替换这些 import。
 * 物理思路 (跨版本通用): 车位置 = 玩家位置 + 固定偏移 (纯函数, 无累积误差);
 * 客户端权威 (isLocalClientAuthoritative) 让本地玩家拉车时客户端忽略位置包。
 */
public class {class_name} extends Entity implements net.minecraft.world.entity.vehicle.ContainerEntity {{
    private static final EntityDataAccessor<Optional<EntityReference<LivingEntity>>> DATA_PULLER =
            SynchedEntityData.defineId({class_name}.class, EntityDataSerializers.OPTIONAL_LIVING_ENTITY_REFERENCE);
    private static final EntityDataAccessor<Integer> DATA_WHEEL_ROTATION =
            SynchedEntityData.defineId({class_name}.class, EntityDataSerializers.INT);
    private static final int CONTAINER_SIZE = 54;

    /** [参数] 车与玩家中心的期望间距 (格) */
    private static final double PULL_BACK = 0.95D;

    private float wheelRotation;
    private net.minecraft.core.NonNullList<ItemStack> itemStacks =
            net.minecraft.core.NonNullList.withSize(CONTAINER_SIZE, ItemStack.EMPTY);
    private net.minecraft.resources.ResourceKey<net.minecraft.world.level.storage.loot.LootTable> lootTable;
    private long lootTableSeed;

    public {class_name}(EntityType<?> type, Level level) {{
        super(type, level);
        this.blocksBuilding = true;
    }}

    /**
     * [版本适配] 客户端权威: 本地玩家拉车时客户端自算位置(忽略位置包)。
     * 思路跨版本通用 (vanilla 船/马机制)。26.1 用 isLocalClientAuthoritative。
     */
    @Override
    public boolean isLocalClientAuthoritative() {{
        if (super.isLocalClientAuthoritative()) return true;
        if (!this.level().isClientSide()) return false;
        LivingEntity puller = this.getPuller();
        if (puller == null) return false;
        return puller.getId() == net.minecraft.client.Minecraft.getInstance().player.getId();
    }}

    // ===== 牵引者 =====

    public boolean hasPuller() {{
        return this.entityData.get(DATA_PULLER).isPresent();
    }}

    @Nullable
    public LivingEntity getPuller() {{
        return this.entityData.get(DATA_PULLER)
                .map(ref -> EntityReference.getLivingEntity(ref, this.level()))
                .orElse(null);
    }}

    public void setPuller(LivingEntity puller) {{
        this.entityData.set(DATA_PULLER, Optional.of(EntityReference.of(puller)));
    }}

    public void clearPuller() {{
        this.entityData.set(DATA_PULLER, Optional.<EntityReference<LivingEntity>>empty());
    }}

    /**
     * 牵引跟随 — 位置绑定纯函数 (物理思路跨版本通用):
     * X/Z 保持车→玩家当前方向固定距离, 朝向由实际向量算, Y 跟随玩家高度。
     */
    private void pulledTick() {{
        LivingEntity puller = this.getPuller();
        if (puller == null) return;
        double dx = puller.getX() - this.getX();
        double dz = puller.getZ() - this.getZ();
        double horiz = Math.sqrt(dx * dx + dz * dz);
        if (horiz > 1.0E-4) {{
            double targetX = puller.getX() - dx / horiz * PULL_BACK;
            double targetZ = puller.getZ() - dz / horiz * PULL_BACK;
            this.setPos(targetX, puller.getY(), targetZ);
            // 车头(+Z)朝玩家: getYaw(-atan2) + 180
            this.setYRot(Mth.wrapDegrees((float) Math.toDegrees(-Mth.atan2(dx, dz))) + 180.0F);
        }}
        this.setXRot(0.0F);
        this.setDeltaMovement(0.0D, this.getDeltaMovement().y, 0.0D);
    }}

    /** [版本适配] 轮子方向: 局部+Z世界方向 = (sin(yaw), -cos(yaw)), 26.1 渲染序列 YP(180-yaw)。 */
    private void updateWheelRotation() {{
        double dx = this.getX() - this.xOld;
        double dz = this.getZ() - this.zOld;
        float yawRad = (float) Math.toRadians(this.getYRot());
        double localZx = Math.sin(yawRad);
        double localZz = -Math.cos(yawRad);
        double forward = dx * localZx + dz * localZz;
        if (Math.abs(forward) > 1.0E-4) {{
            this.wheelRotation += (float) (forward * (360.0f / (8.0f * (float) Math.PI / 16.0f)));
            if (this.wheelRotation >= 360.0f) this.wheelRotation -= 360.0f;
            if (this.wheelRotation < 0) this.wheelRotation += 360.0f;
            this.entityData.set(DATA_WHEEL_ROTATION, (int) this.wheelRotation);
        }}
    }}

    public float getWheelRotation(float partialTick) {{
        return this.entityData.get(DATA_WHEEL_ROTATION);
    }}

    @Override
    public void tick() {{
        boolean pulled = this.hasPuller();
        LivingEntity puller = this.getPuller();
        if (pulled && (puller == null || !puller.isAlive() || puller.getVehicle() == this)) {{
            this.clearPuller();
            pulled = false;
        }}
        if (pulled && puller.isCrouching()) {{
            this.clearPuller();
            pulled = false;
        }}
        if (pulled) {{
            if (!this.isNoGravity()) {{
                double gravity = this.isInWater() ? 0 : -0.04;
                this.setDeltaMovement(this.getDeltaMovement().add(0, gravity, 0));
            }}
            this.pulledTick();
            this.move(MoverType.SELF, this.getDeltaMovement());
            if (!this.level().isClientSide()) {{
                this.updateWheelRotation();
            }}
            super.tick();
            this.pushNearby();
            return;
        }}
        // 无牵引: 常规物理
        if (!this.isNoGravity()) {{
            double gravity = this.isInWater() ? 0 : -0.04;
            this.setDeltaMovement(this.getDeltaMovement().add(0, gravity, 0));
        }}
        this.move(MoverType.SELF, this.getDeltaMovement());
        if (!this.level().isClientSide() && this.onGround()) {{
            this.updateWheelRotation();
        }}
        if (this.onGround()) {{
            this.setDeltaMovement(this.getDeltaMovement().multiply(0.6, 1.0, 0.6));
        }} else {{
            this.setDeltaMovement(this.getDeltaMovement().multiply(0.98, 1.0, 0.98));
        }}
        Vec3 mv = this.getDeltaMovement();
        if (Math.abs(mv.x) < 0.003) this.setDeltaMovement(0, mv.y, mv.z);
        if (Math.abs(mv.z) < 0.003) this.setDeltaMovement(mv.x, mv.y, 0);
        if (this.onGround()) this.fallDistance = 0;
        if (!this.level().isClientSide()) {{
            this.entityData.set(DATA_WHEEL_ROTATION, (int) this.wheelRotation);
        }}
        super.tick();
        this.pushNearby();
    }}

    private void pushNearby() {{
        if (this.level().isClientSide()) return;
        for (Entity entity : this.level().getEntities(this,
                this.getBoundingBox().inflate(0.2f, -0.01f, 0.2f),
                net.minecraft.world.entity.EntitySelector.pushableBy(this))) {{
            if (entity.hasPassenger(this)) continue;
            boolean canAutoRide = !(this.getControllingPassenger() instanceof Player);
            if (canAutoRide && this.isCargoEmpty()
                    && this.getPassengers().size() < this.getMaxPassengers()
                    && !entity.isPassenger()
                    && entity instanceof LivingEntity
                    && !entity.is(net.minecraft.tags.EntityTypeTags.CANNOT_BE_PUSHED_ONTO_BOATS)) {{
                if (this.hasEnoughSpaceFor(entity)) {{ entity.startRiding(this); continue; }}
            }}
            this.push(entity);
        }}
    }}

    public boolean hasEnoughSpaceFor(Entity passenger) {{
        return passenger.getBbWidth() < this.getBbWidth();
    }}

    protected int getMaxPassengers() {{ return 1; }}

    /** 存储/骑乘互斥: 无乘客且容器空 */
    public boolean isCargoEmpty() {{
        return this.getPassengers().isEmpty() && this.isChestVehicleEmpty();
    }}

    @Override
    public InteractionResult interact(Player player, InteractionHand hand, Vec3 location) {{
        if (player.isSecondaryUseActive()) {{
            if (!this.level().isClientSide()) return this.interactWithContainerVehicle(player);
            return InteractionResult.SUCCESS;
        }}
        if (this.level().isClientSide()) return InteractionResult.SUCCESS;
        LivingEntity puller = this.getPuller();
        if (puller == null) {{
            if (player.distanceToSqr(this) > 4.0 * 4.0) return InteractionResult.PASS;
            this.setPuller(player);
            return InteractionResult.CONSUME;
        }}
        if (this.isCargoEmpty()) {{
            return player.startRiding(this) ? InteractionResult.CONSUME : InteractionResult.PASS;
        }}
        return InteractionResult.PASS;
    }}

    // ===== 容器 (ContainerEntity 默认方法已含存取/倒出) =====

    @Override
    public int getContainerSize() {{ return CONTAINER_SIZE; }}

    @Override
    public net.minecraft.core.NonNullList<ItemStack> getItemStacks() {{ return this.itemStacks; }}

    @Override
    public void clearItemStacks() {{ this.itemStacks.clear(); }}

    @Override
    public net.minecraft.resources.ResourceKey<net.minecraft.world.level.storage.loot.LootTable> getContainerLootTable() {{ return this.lootTable; }}

    @Override
    public void setContainerLootTable(net.minecraft.resources.ResourceKey<net.minecraft.world.level.storage.loot.LootTable> lootTable) {{ this.lootTable = lootTable; }}

    @Override
    public long getContainerLootTableSeed() {{ return this.lootTableSeed; }}

    @Override
    public void setContainerLootTableSeed(long seed) {{ this.lootTableSeed = seed; }}

    @Override
    public ItemStack getItem(int slot) {{ return this.getChestVehicleItem(slot); }}

    @Override
    public void setItem(int slot, ItemStack stack) {{ this.setChestVehicleItem(slot, stack); }}

    @Override
    public ItemStack removeItem(int slot, int amount) {{ return this.removeChestVehicleItem(slot, amount); }}

    @Override
    public ItemStack removeItemNoUpdate(int slot) {{ return this.removeChestVehicleItemNoUpdate(slot); }}

    @Override
    public void clearContent() {{ this.clearItemStacks(); }}

    @Override
    public boolean stillValid(Player player) {{ return this.isChestVehicleStillValid(player); }}

    /** [版本适配] 54格菜单 = 原版大箱子 (ChestMenu.sixRows), 无需自定义 Screen */
    @Override
    public net.minecraft.world.inventory.AbstractContainerMenu createMenu(
            int containerId, net.minecraft.world.entity.player.Inventory playerInventory, Player player) {{
        return net.minecraft.world.inventory.ChestMenu.sixRows(containerId, playerInventory, this);
    }}

    @Override
    public net.minecraft.network.chat.Component getDisplayName() {{ return this.getName(); }}

    // ===== 破坏/存档 =====

    @Override
    public boolean hurtClient(DamageSource source) {{ return true; }}

    @Override
    public boolean hurtServer(ServerLevel level, DamageSource source, float amount) {{
        if (this.isRemoved()) return false;
        if (source.is(DamageTypeTags.IS_EXPLOSION)) {{
            this.chestVehicleDestroyed(source, level, this);
            this.discard();
            return true;
        }}
        if (!source.isCreativePlayer() && level.getGameRules().get(GameRules.ENTITY_DROPS)) {{
            this.chestVehicleDestroyed(source, level, this);
            this.spawnAtLocation(level, new ItemStack(ModItems.{entity_id.upper()}.get()));
        }}
        this.discard();
        return true;
    }}

    @Override
    protected void readAdditionalSaveData(ValueInput input) {{
        this.wheelRotation = input.getFloatOr("WheelRot", 0f);
        this.entityData.set(DATA_WHEEL_ROTATION, (int) this.wheelRotation);
        @SuppressWarnings("unchecked")
        Optional<EntityReference<LivingEntity>> puller =
                Optional.ofNullable((EntityReference<LivingEntity>) (EntityReference<?>) EntityReference.read(input, "Puller"));
        this.entityData.set(DATA_PULLER, puller);
        this.readChestVehicleSaveData(input);
    }}

    @Override
    protected void addAdditionalSaveData(ValueOutput output) {{
        output.putFloat("WheelRot", wheelRotation);
        this.entityData.get(DATA_PULLER).ifPresent(ref -> EntityReference.store(ref, output, "Puller"));
        this.addChestVehicleSaveData(output);
    }}

    @Override
    public ItemStack getPickResult() {{
        return new ItemStack(ModItems.{entity_id.upper()}.get());
    }}
}}
'''


def generate_entity_renderer_class(class_name, entity_class_name, body_item, wheel_item,
                                  package=None, mod_id=None):
    package = package or _pkg('client.renderer')
    mod_id = mod_id or (_cfg.get_mod_id() or 'example_mod')
    """生成实体渲染器骨架 (ItemModelResolver 标准管线 + 轮子分离)。
    [版本适配] 26.1: ItemModelResolver/ItemStackRenderState/SubmitNodeCollector。
    渲染思路跨版本通用: 车体/轮子分别走 ItemModelResolver, 轮子绕质心旋转。
    """
    return f'''package {package};

import com.mojang.blaze3d.vertex.PoseStack;
import com.mojang.math.Axis;
import {mod_id}.entity.{entity_class_name};
import {mod_id}.registry.ModItems;
import net.minecraft.client.renderer.SubmitNodeCollector;
import net.minecraft.client.renderer.entity.EntityRenderer;
import net.minecraft.client.renderer.entity.EntityRendererProvider;
import net.minecraft.client.renderer.item.ItemModelResolver;
import net.minecraft.client.renderer.state.level.CameraRenderState;
import net.minecraft.client.renderer.texture.OverlayTexture;
import net.minecraft.world.item.ItemDisplayContext;
import net.minecraft.world.item.ItemStack;

/**
 * [{class_name}] 实体渲染器: 车体 + 独立轮子 (ItemModelResolver 标准管线)。
 * [版本适配] 26.1: EntityRenderState + submit。跨版本替换 submit/extractRenderState 签名。
 * 轮子质心枢轴: 3D 轴旋转的枢轴取 质心-0.5 (抵消 ItemTransform.apply 的 -0.5 平移)。
 */
public class {class_name} extends EntityRenderer<{entity_class_name}, {entity_class_name[:-6] + "RenderState"}> {{
    private final ItemModelResolver itemModelResolver;
    // 轮子质心(模型旋转后, 块坐标)减 0.5 = 枢轴
    private static final float WHEEL_PIVOT_X = 0.0F;
    private static final float WHEEL_PIVOT_Y = -0.286F;
    private static final float WHEEL_PIVOT_Z = -0.714F;

    public {class_name}(EntityRendererProvider.Context context) {{
        super(context);
        this.itemModelResolver = context.getItemModelResolver();
    }}

    @Override
    public {entity_class_name[:-6] + "RenderState"} createRenderState() {{
        return new {entity_class_name[:-6] + "RenderState"}();
    }}

    @Override
    public void extractRenderState({entity_class_name} entity, {entity_class_name[:-6] + "RenderState"} state, float partialTick) {{
        super.extractRenderState(entity, state, partialTick);
        state.yRot = entity.getYRot();
        state.wheelRot = entity.getWheelRotation(partialTick);
        state.body.clear();
        state.wheel.clear();
        // 不能在此处 new ItemStack on 构造器: 组件未绑定会导致黑屏。extractRenderState 是安全点。
        ItemStack bodyStack = new ItemStack(ModItems.{body_item.upper()}.get());
        ItemStack wheelStack = new ItemStack(ModItems.{wheel_item.upper()}.get());
        itemModelResolver.updateForNonLiving(state.body, bodyStack, ItemDisplayContext.NONE, entity);
        itemModelResolver.updateForNonLiving(state.wheel, wheelStack, ItemDisplayContext.NONE, entity);
    }}

    @Override
    public void submit({entity_class_name[:-6] + "RenderState"} state, PoseStack poseStack,
                       SubmitNodeCollector collector, CameraRenderState camera) {{
        super.submit(state, poseStack, collector, camera);
        poseStack.pushPose();
        poseStack.mulPose(Axis.YP.rotationDegrees(180.0F - state.yRot));
        poseStack.translate(0.0F, 0.5F, 0.0F);  // 抵消 ItemTransform -0.5 下陷
        state.body.submit(poseStack, collector, state.lightCoords, OverlayTexture.NO_OVERLAY, state.outlineColor);
        // 轮子绕质心绕 X 轴旋转
        poseStack.pushPose();
        poseStack.translate(WHEEL_PIVOT_X, WHEEL_PIVOT_Y, WHEEL_PIVOT_Z);
        poseStack.mulPose(Axis.XP.rotationDegrees(state.wheelRot));
        poseStack.translate(-WHEEL_PIVOT_X, -WHEEL_PIVOT_Y, -WHEEL_PIVOT_Z);
        state.wheel.submit(poseStack, collector, state.lightCoords, OverlayTexture.NO_OVERLAY, state.outlineColor);
        poseStack.popPose();
        poseStack.popPose();
    }}
}}
'''


def generate_entity_render_state_class(class_name, entity_class_name,
                                       package=None):
    package = package or _pkg('client.renderer')
    """生成实体 RenderState 骨架。"""
    return f'''package {package};

import net.minecraft.client.renderer.entity.state.EntityRenderState;
import net.minecraft.client.renderer.item.ItemStackRenderState;

public class {class_name} extends EntityRenderState {{
    public float yRot;
    public float wheelRot;
    public final ItemStackRenderState body = new ItemStackRenderState();
    public final ItemStackRenderState wheel = new ItemStackRenderState();
}}
'''
