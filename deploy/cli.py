#!/usr/bin/env python3
"""
模型部署工具 - 零参数智能入口。

用法:
    python deploy.py <model.json|model.bbmodel> [--name ClassName]

自动完成:
1. 分析模型类型 (单格/多方块/多变体/旋转)
2. 验证实装问题 (UV/粒子/图标/旋转角/多方块一致性)
3. 自动修复可修复问题 (--fix 默认开启)
4. 生成 Block 类代码 (按类型选模板)
5. 生成碰撞箱 (复用 tools/collision)
6. 输出部署清单 (还需手动做什么)

设计目标: 无需记忆参数, 一条命令出完整结果。
"""
import argparse
import os
import sys
import json

# 复用现有 collision 工具 + 通用配置
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'collision'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'common'))

import analyzer
import codegen
import validate_model


def main():
    ap = argparse.ArgumentParser(description='模型一键部署工具')
    ap.add_argument('model', help='模型 JSON/.bbmodel 路径')
    ap.add_argument('--name', help='方块类名 (默认从文件名推断)')
    ap.add_argument('--no-fix', action='store_true', help='不自动修复')
    ap.add_argument('--out', help='生成的 Java 类输出目录', default=None)
    # 实体模式: 生成"拉车实体+渲染器+RenderState"骨架 (独轮推车经验)
    ap.add_argument('--entity', action='store_true',
                    help='实体模式: 生成拉车实体/渲染器/RenderState 骨架')
    ap.add_argument('--entity-id', help='实体注册 id (默认从文件名推断, 如 wheelbarrow)')
    args = ap.parse_args()

    if not os.path.exists(args.model):
        print(f"❌ 文件不存在: {args.model}")
        sys.exit(2)

    # 1. 分析
    print("=" * 60)
    analysis = analyzer.analyze(args.model)
    print(analyzer.format_analysis(analysis))
    print("=" * 60)

    # 2. 验证 + 自动修复
    print("\n[验证]")
    try:
        model = analyzer.load_model(args.model)
        issues = validate_model.detect_issues(model, args.model)
        errors = [i for i in issues if i[0] == 'ERROR']
        warns = [i for i in issues if i[0] == 'WARN']
        if not issues:
            print("  ✅ 无实装问题")
        for sev, code, msg, fix in issues:
            icon = '❌' if sev == 'ERROR' else '⚠️'
            print(f"  {icon} [{code}] {msg}")
        if errors and not args.no_fix:
            fixes = validate_model.apply_fixes(model, args.model, issues)
            if fixes:
                with open(args.model, 'w', encoding='utf-8') as f:
                    json.dump(model, f, indent=2, ensure_ascii=False)
                print(f"\n  🔧 自动修复 {len(fixes)} 项:")
                for fx in fixes:
                    print(f"     ✓ {fx}")
    except Exception as e:
        print(f"  ⚠️ 验证器异常: {e}")

    # 3. 生成 Block 类 (或实体模式骨架)
    if args.entity:
        entity_id = args.entity_id or os.path.splitext(os.path.basename(args.model))[0]
        entity_class = ''.join(w.capitalize() for w in entity_id.replace('-', '_').split('_') if w) + 'Entity'
        renderer_class = entity_class.removesuffix('Entity') + 'Renderer'
        rs_class = entity_class.removesuffix('Entity') + 'RenderState'
        print(f"\n[实体骨架生成] {entity_class} + {renderer_class} + {rs_class}")
        out_dir = args.out or '.'
        os.makedirs(out_dir, exist_ok=True)
        for cls_name, text in [
            (entity_class, codegen.generate_entity_class(entity_class, entity_id)),
            (renderer_class, codegen.generate_entity_renderer_class(renderer_class, entity_class,
                                                                     f'{entity_id}_body', f'{entity_id}_wheel')),
            (rs_class, codegen.generate_entity_render_state_class(rs_class, entity_class)),
        ]:
            with open(os.path.join(out_dir, cls_name + '.java'), 'w', encoding='utf-8') as f:
                f.write(text)
            print(f"  已写入: {cls_name}.java")
        print("\n  提示: 还需手动 -- 注册实体/物品(wheel/body/wheel_split/full_no_wheel)/items JSON/语言")
        return

    class_name = args.name or infer_class_name(args.model)
    print(f"\n[代码生成] {class_name}.java")
    code = codegen.generate(analysis, class_name)

    # 闭环: 用 run.py 的碰撞箱逻辑生成真实 Shapes 代码, 替换 SHAPE_BASE 占位
    shape_java = generate_shape_java(model, args)
    if shape_java and 'SHAPE_BASE = box(0, 0, 0, 16, 16, 16)' in code:
        # 保留变量名, 只替换右侧 box(...) 为 Shapes.or(...)
        code = code.replace('SHAPE_BASE = box(0, 0, 0, 16, 16, 16)', 'SHAPE_BASE = ' + shape_java)
        code = code.replace('// TODO: 用 tools/collision/run.py --facing 生成碰撞箱后替换', '')
        print(f"  ✓ 碰撞箱已生成并填入 (替换 SHAPE_BASE 占位)")
    elif shape_java and 'SHAPE = box(0, 0, 0, 16, 16, 16)' in code:
        code = code.replace('SHAPE = box(0, 0, 0, 16, 16, 16)', 'SHAPE = ' + shape_java)
        code = code.replace('// TODO: 用 tools/collision 生成每格碰撞箱后替换', '')
        print(f"  ✓ 碰撞箱已生成并填入 (替换 SHAPE 占位)")

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        out_path = os.path.join(args.out, class_name + '.java')
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(code)
        print(f"  已写入: {out_path}")
    else:
        print("  --- Java 代码 ---")
        print(code)

    # 4. 部署清单
    print("\n" + "=" * 60)
    print("部署清单 (还需手动完成):")

    # 若碰撞箱已填入, 清单里那条碰撞箱项改为完成/移除
    if shape_java:
        checklist = [i for i in generate_checklist(analysis, class_name) if 'generate' not in i and 'run.py' not in i and '碰撞箱' not in i]
    else:
        checklist = generate_checklist(analysis, class_name)
    for item in checklist:
        print(f"  ☐ {item}")
    print("=" * 60)


def infer_class_name(path):
    """从文件名推断类名 (snake_case -> CamelCase)"""
    base = os.path.splitext(os.path.basename(path))[0]
    return ''.join(w.capitalize() for w in base.replace('-', '_').split('_') if w) + 'Block'


def generate_shape_java(model, args):
    """从模型生成真实碰撞箱的 Shapes.java 代码 (复用 tools/collision 逻辑)。
    返回 "private static final VoxelShape SHAPE_BASE = Shapes.or(...);" 代码块,
    失败返回 None (工具报错时留占位, 不阻断生成)。"""
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'collision'))
        from parse_model import load_cubes, all_bounds
        from generate import compress_adaptive, to_java

        # 保存模型文件到临时 (load_cubes 需路径, write 后必须 close 再传)
        import tempfile, json as _json
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.json', mode='w', encoding='utf-8')
        _json.dump(model, tmp)
        tmp.close()
        cubes = load_cubes(tmp.name)
        boxes, rotated = compress_adaptive(cubes)

        # 主碰撞箱 java 代码 (归一化坐标)
        body = to_java(boxes)
        os.unlink(tmp.name)
        return body
    except Exception as e:
        print(f"  ⚠️ 碰撞箱生成失败(留占位): {e}")
        return None


def generate_checklist(analysis, class_name):
    import config as _cfg
    mod_id = _cfg.get_mod_id() or 'example_mod'
    a = analysis
    items = [
        f"注册方块: ModBlocks.{class_name.removesuffix('Block').upper()} (BlockBehaviour.Properties.ofFullCopy(Blocks.OAK_PLANKS).noOcclusion())",
        "注册物品: ModItems.registerSimpleBlockItem",
        "注册创造标签: ModCreativeTabs.displayItems",
        "语言: ModLanguageProvider addBlock (英文, 中文)",
        "loot 表: ModBlockLootProvider dropSelf + 运行 runClientData",
        f"blockstate: src/main/resources/assets/{mod_id}/blockstates/{a['base_name']}.json",
        f"item model: src/main/resources/assets/{mod_id}/items/{a['base_name']}.json",
        "运行 ./gradlew compileJava 验证编译",
    ]
    if a['kind'] == 'multiblock':
        cx, cy, cz = a['cells']
        items.insert(0, f"⚠️ 多方块 {cx}×{cy}×{cz}: 生成的 Block 类已含中心判定/tick填充/拆除联动, 需替换 SHAPE 为按格切割碰撞箱")
        items.append("碰撞箱: python tools/collision/run.py <model> --facing (按格切割后填入 SHAPES[layer][pos])")
    else:
        items.append("碰撞箱: python tools/collision/run.py <model> --facing 替换 SHAPE_BASE")
    return items


if __name__ == '__main__':
    main()
