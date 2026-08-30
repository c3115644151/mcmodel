#!/usr/bin/env python3
"""
模型拆分工具 - 从 BlockBench 导出的模型按元素索引拆分子模型。

适用场景 (来自独轮推车开发经验):
1. 动态部件分离: 轮子等可动部件需独立模型 (供渲染器运行时旋转), 其余为静态车身
2. 变体去轮子: 丰收变体(货物+基座完整模型)需去掉轮子, 避免与独立动轮重叠
3. 隐藏物品生成: 拆分出的子模型配 items JSON 供 ItemModelResolver 渲染

用法:
    python split_model.py <model.json> --keep 0,1,2 --out wheel.json
    python split_model.py <model.json> --drop 3,4 --out body_no_wheel.json
    # 自动检测: --auto-wheel 检测"同心双cube"(轮子特征: 质心重合的小嵌套cube)
    python split_model.py <model.json> --auto-wheel --out-prefix wheelbarrow

参数:
    --keep IDX  保留元素索引列表 (逗号分隔), 其余删除
    --drop IDX  删除元素索引列表 (逗号分隔), 其余保留
    --out PATH  输出路径
    --auto-wheel 自动检测轮子(质心重合的嵌套cube对)并拆分, 需 --out-prefix
"""
import json
import sys
import argparse


def load_model(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_model(model, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(model, f, indent=2, ensure_ascii=False)
    print(f"saved {path} ({len(model['elements'])} elements)")


def split_by_indices(model, keep=None, drop=None):
    """keep: 保留的索引集合; drop: 删除的索引集合"""
    elements = model["elements"]
    if keep is not None:
        new_elements = [e for i, e in enumerate(elements) if i in keep]
    else:
        old = set(drop or [])
        new_elements = [e for i, e in enumerate(elements) if i not in old]
    # 释放未引用的纹理 (仅保留被使用的, 加 particle)
    used = {f["texture"] for e in new_elements for f in e["faces"].values()}
    new_model = {k: v for k, v in model.items() if k != "elements"}
    new_model["elements"] = new_elements
    new_model["textures"] = {
        k: v for k, v in model["textures"].items()
        if ("#" + k) in used or k == "particle"
    }
    return new_model


def center(elem):
    f, t = elem["from"], elem["to"]
    return [(f[i] + t[i]) / 2 for i in range(3)]


def detect_wheels(model):
    """自动检测轮子: 质心重合 + 尺寸接近 + 小尺寸(≤8单位) 的嵌套 cube 对。
    特征(独轮推车): 外圈 4x8x8, 内圈 3.6x7.6x7.6, 直径 ≤8。
    排除: 车壁pair(尺寸>8 大板), 货物堆(尺寸差 >15%)。"""
    elements = model["elements"]

    def size(elem):
        f, t = elem["from"], elem["to"]
        return [abs(t[i] - f[i]) for i in range(3)]

    def max_dim(elem):
        return max(size(elem))

    wheels = []
    for i in range(len(elements)):
        for j in range(i + 1, len(elements)):
            ci, cj = center(elements[i]), center(elements[j])
            if abs(ci[0] - cj[0]) < 0.01 and abs(ci[1] - cj[1]) < 0.01 and abs(ci[2] - cj[2]) < 0.01:
                si, sj = size(elements[i]), size(elements[j])
                # 尺寸接近 (内圈=外圈缩水): 各轴尺寸比在 0.85~1.0
                similar = all(
                    0.85 <= sj[k] / si[k] <= 1.0 if si[k] > 0 else True
                    for k in range(3)
                )
                # 轮子尺寸小 (直径 ≤8): 排除车壁大板/货物堆
                small = max_dim(elements[i]) <= 8.0 and max_dim(elements[j]) <= 8.0
                if similar and small:
                    wheels.append(i)
                    wheels.append(j)
    return sorted(set(wheels))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("model", help="源模型 JSON")
    ap.add_argument("--keep", help="保留的元素索引 (逗号分隔)")
    ap.add_argument("--drop", help="删除的元素索引 (逗号分隔)")
    ap.add_argument("--out", help="输出路径")
    ap.add_argument("--auto-wheel", action="store_true", help="自动检测轮子")
    ap.add_argument("--wheel-hint", help="轮子元素索引 (逗号分隔), 精确指定")
    ap.add_argument("--out-prefix", help="自动模式的输出前缀")
    ap.add_argument("--copy-uv", action="store_true",
                    help="复制轮子 UV 时翻转负尺寸面 (双向 cube shell)")
    args = ap.parse_args()

    model = load_model(args.model)

    if args.auto_wheel or args.wheel_hint:
        if args.wheel_hint:
            wheels = {int(x) for x in args.wheel_hint.split(",")}
            print(f"使用提示轮子元素: {sorted(wheels)}")
        else:
            wheels = set(detect_wheels(model))
            if not wheels:
                print("未检测到轮子 (质心重合的嵌套cube对)")
                sys.exit(1)
            print(f"检测到轮子元素: {sorted(wheels)}")
        prefix = args.out_prefix or "split"
        # 轮子模型: 只留轮子
        wheel_model = split_by_indices(model, keep=set(wheels))
        save_model(wheel_model, f"{prefix}_wheel.json")
        # 主体模型: 去轮子
        body_model = split_by_indices(model, drop=set(wheels))
        save_model(body_model, f"{prefix}_no_wheel.json")
    else:
        keep = None
        drop = None
        if args.keep:
            keep = {int(x) for x in args.keep.split(",")}
        if args.drop:
            drop = {int(x) for x in args.drop.split(",")}
        if not args.out:
            print("需要 --out (或 --auto-wheel)")
            sys.exit(1)
        split_model = split_by_indices(model, keep=keep, drop=drop)
        save_model(split_model, args.out)


if __name__ == "__main__":
    main()
