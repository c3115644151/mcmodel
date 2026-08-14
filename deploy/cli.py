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

# 复用现有 collision 工具
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'collision'))

import analyzer
import codegen
import validate_model


def main():
    ap = argparse.ArgumentParser(description='模型一键部署工具')
    ap.add_argument('model', help='模型 JSON/.bbmodel 路径')
    ap.add_argument('--name', help='方块类名 (默认从文件名推断)')
    ap.add_argument('--no-fix', action='store_true', help='不自动修复')
    ap.add_argument('--out', help='生成的 Java 类输出目录', default=None)
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

    # 3. 生成 Block 类
    class_name = args.name or infer_class_name(args.model)
    print(f"\n[代码生成] {class_name}.java")
    code = codegen.generate(analysis, class_name)
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
    checklist = generate_checklist(analysis, class_name)
    for item in checklist:
        print(f"  ☐ {item}")
    print("=" * 60)


def infer_class_name(path):
    """从文件名推断类名 (snake_case -> CamelCase)"""
    base = os.path.splitext(os.path.basename(path))[0]
    return ''.join(w.capitalize() for w in base.replace('-', '_').split('_') if w) + 'Block'


def generate_checklist(analysis, class_name):
    a = analysis
    items = [
        f"注册方块: ModBlocks.{class_name.removesuffix('Block').upper()} (BlockBehaviour.Properties.ofFullCopy(Blocks.OAK_PLANKS).noOcclusion())",
        "注册物品: ModItems.registerSimpleBlockItem",
        "注册创造标签: ModCreativeTabs.displayItems",
        "语言: ModLanguageProvider addBlock (英文, 中文)",
        "loot 表: ModBlockLootProvider dropSelf + 运行 runClientData",
        f"blockstate: src/main/resources/assets/pastoral_home/blockstates/{a['base_name']}.json",
        f"item model: src/main/resources/assets/pastoral_home/items/{a['base_name']}.json",
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
