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


def generate_multiblock_class(class_name, analysis, package='com.pastoralhome.block'):
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


def generate_simple_class(class_name, analysis, package='com.pastoralhome.block'):
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
