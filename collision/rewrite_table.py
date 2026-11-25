# -*- coding: utf-8 -*-
"""重构 OakTableBlock：用工具生成的碰撞箱替换 8 套预旋转，改用运行时旋转。"""
import io
import os

BASE = 'c:/Users/32800/Desktop/家具mod'

# 读取工具生成的 shapes
with io.open(os.path.join(BASE, 'tools/collision/out/table_shapes.java'), encoding='utf-8') as f:
    shapes = f.read().strip()

# 移除 shapes 文件里的注释行（避免重复）
shape_lines = [l for l in shapes.split('\n') if not l.strip().startswith('//')]
shapes = '\n'.join(shape_lines)

content = """package com.pastoralhome.block;

import com.mojang.serialization.MapCodec;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.sounds.SoundEvents;
import net.minecraft.sounds.SoundSource;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.entity.player.Player;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.context.BlockPlaceContext;
import net.minecraft.world.level.BlockGetter;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.LevelAccessor;
import net.minecraft.util.RandomSource;
import net.minecraft.world.level.LevelReader;
import net.minecraft.world.level.ScheduledTickAccess;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.HorizontalDirectionalBlock;
import net.minecraft.world.level.block.RenderShape;
import net.minecraft.world.level.block.Rotation;
import net.minecraft.world.level.block.state.BlockBehaviour;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.StateDefinition;
import net.minecraft.world.level.block.state.properties.BlockStateProperties;
import net.minecraft.world.level.block.state.properties.BooleanProperty;
import net.minecraft.world.level.block.state.properties.ChestType;
import net.minecraft.world.level.block.state.properties.EnumProperty;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.shapes.CollisionContext;
import net.minecraft.world.phys.shapes.Shapes;
import net.minecraft.world.phys.shapes.VoxelShape;

import javax.annotation.Nullable;

/**
 * 橡木长桌 — 2 格宽方块，完全参考 Iron's Spellbooks 的 InscriptionTableBlock 实现。
 * <p>
 * 关键设计：
 * - LEFT 方块不渲染（getRenderShape 返回 INVISIBLE），RIGHT 正常渲染完整模型
 * - blockstate 只有 FACING，没有 PART 变体（双方块共享同一个模型 JSON）
 * - 模型 x 范围 [-16, 16] 覆盖两格，变换后的左右方块各渲染一次
 * - PART 用于碰撞箱判断
 * - 碰撞箱由 tools/collision 工具生成（北向基准 LEFT/RIGHT），方向变体用运行时旋转
 */
public class OakTableBlock extends HorizontalDirectionalBlock {

    public static final EnumProperty<ChestType> PART = BlockStateProperties.CHEST_TYPE;
    public static final BooleanProperty HAS_BLANKET = BooleanProperty.create("has_blanket");
    private static final MapCodec<OakTableBlock> CODEC = simpleCodec(OakTableBlock::new);

    // 碰撞箱由 tools/collision 工具从模型自动生成（北向基准 LEFT/RIGHT）
    // 方向变体: getShape 中按 FACING 运行时旋转, 与木桶/水车模式统一
""" + shapes + """

    public OakTableBlock(BlockBehaviour.Properties properties) {
        super(properties);
        this.registerDefaultState(this.stateDefinition.any()
                .setValue(FACING, Direction.NORTH)
                .setValue(PART, ChestType.RIGHT)
                .setValue(HAS_BLANKET, true));
    }

    @Override
    protected MapCodec<? extends HorizontalDirectionalBlock> codec() {
        return CODEC;
    }

    @Override
    protected void createBlockStateDefinition(StateDefinition.Builder<Block, BlockState> builder) {
        super.createBlockStateDefinition(builder);
        builder.add(FACING, PART, HAS_BLANKET);
    }

    @Override
    public RenderShape getRenderShape(BlockState state) {
        return state.getValue(PART) == ChestType.RIGHT ? RenderShape.MODEL : RenderShape.INVISIBLE;
    }

    @Nullable
    @Override
    public BlockState getStateForPlacement(BlockPlaceContext context) {
        Direction facing = context.getHorizontalDirection().getOpposite();
        BlockPos pos = context.getClickedPos();
        // LEFT 辅助方块在 FACING 的逆时针方向（与 setPlacedBy/getNeighbourDirection 一致）
        BlockPos leftPos = pos.relative(facing.getCounterClockWise());
        Level level = context.getLevel();
        if (level.getBlockState(leftPos).canBeReplaced(context) && level.getWorldBorder().isWithinBounds(leftPos)) {
            return this.defaultBlockState().setValue(FACING, facing);
        }
        return null;
    }

    @Override
    public void setPlacedBy(Level level, BlockPos pos, BlockState state, @Nullable LivingEntity placer, ItemStack stack) {
        super.setPlacedBy(level, pos, state, placer, stack);
        if (!level.isClientSide()) {
            // LEFT 方块在 counterClockWise 方向（模型向 -X 延伸）
            BlockPos leftPos = pos.relative(state.getValue(FACING).getCounterClockWise());
            level.setBlock(leftPos, state.setValue(PART, ChestType.LEFT), 3);
            level.setBlock(pos, state.setValue(PART, ChestType.RIGHT), 3);
            level.updateNeighborsAt(pos, Blocks.AIR);
            state.updateNeighbourShapes(level, pos, 3);
        }
    }

    @Override
    protected BlockState updateShape(BlockState state, LevelReader level, ScheduledTickAccess ticks,
                                     BlockPos pos, Direction direction, BlockPos neighborPos,
                                     BlockState neighborState, RandomSource random) {
        ChestType half = state.getValue(PART);
        Direction expected = getNeighbourDirection(half, state.getValue(FACING));
        if (direction == expected) {
            BlockPos requiredPos = pos.relative(expected);
            if (!level.getBlockState(requiredPos).is(this)) {
                return Blocks.AIR.defaultBlockState();
            }
        }
        return super.updateShape(state, level, ticks, pos, direction, neighborPos, neighborState, random);
    }

    private static Direction getNeighbourDirection(ChestType part, Direction facing) {
        // 我们模型向 counterClockWise 方向延伸（与铁魔法相反）
        return part == ChestType.LEFT ? facing.getClockWise() : facing.getCounterClockWise();
    }

    @Override
    protected void affectNeighborsAfterRemoval(BlockState state, ServerLevel level, BlockPos pos, boolean movedByPiston) {
        ChestType part = state.getValue(PART);
        BlockPos otherPos = pos.relative(getNeighbourDirection(part, state.getValue(FACING)));
        if (level.getBlockState(otherPos).is(this)) {
            level.destroyBlock(otherPos, true);
        }
        super.affectNeighborsAfterRemoval(state, level, pos, movedByPiston);
    }

    @Override
    protected InteractionResult useWithoutItem(BlockState state, Level level, BlockPos pos, Player player, BlockHitResult hitResult) {
        if (level.isClientSide()) return InteractionResult.SUCCESS;

        // 定位到 RIGHT 方块（唯一渲染模型的一方），LEFT 跟随切换
        BlockPos rightPos = state.getValue(PART) == ChestType.RIGHT ? pos : pos.relative(getNeighbourDirection(ChestType.LEFT, state.getValue(FACING)));
        BlockState rightState = level.getBlockState(rightPos);
        boolean next = !rightState.getValue(HAS_BLANKET);
        BlockState updated = rightState.setValue(HAS_BLANKET, next);

        level.setBlock(rightPos, updated, 3);
        // 同步切换 LEFT 方块
        BlockPos leftPos = rightPos.relative(getNeighbourDirection(ChestType.RIGHT, state.getValue(FACING)));
        BlockState leftState = level.getBlockState(leftPos);
        if (leftState.is(this)) {
            level.setBlock(leftPos, leftState.setValue(HAS_BLANKET, next), 3);
        }

        // 播放音效增强反馈
        level.playSound(null, rightPos, next ? SoundEvents.WOOL_PLACE : SoundEvents.WOOL_BREAK, SoundSource.BLOCKS, 1.0F, 1.0F);
        return InteractionResult.SUCCESS;
    }

    /** 方向旋转映射：与 getStateForPlacement 的 facing 一致 */
    private static Rotation rotationFor(Direction facing) {
        return switch (facing) {
            case EAST -> Rotation.CLOCKWISE_90;
            case SOUTH -> Rotation.CLOCKWISE_180;
            case WEST -> Rotation.COUNTERCLOCKWISE_90;
            default -> Rotation.NONE;
        };
    }

    @Override
    protected VoxelShape getShape(BlockState state, BlockGetter level, BlockPos pos, CollisionContext context) {
        VoxelShape base = state.getValue(PART) == ChestType.RIGHT ? SHAPE_NORTH_RIGHT : SHAPE_NORTH_LEFT;
        Rotation rot = rotationFor(state.getValue(FACING));
        return rot == Rotation.NONE ? base : Shapes.rotate(base, rot.rotation());
    }

    @Override
    protected VoxelShape getCollisionShape(BlockState state, BlockGetter level, BlockPos pos, CollisionContext context) {
        return getShape(state, level, pos, context);
    }
}
"""

with io.open(os.path.join(BASE, 'src/main/java/com/pastoralhome/block/OakTableBlock.java'), 'w', encoding='utf-8') as f:
    f.write(content)
print("已重写 OakTableBlock.java")
print(f"文件长度: {len(content)} 字符")
