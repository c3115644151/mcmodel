import unittest

import icon_tuner as T
from icon_overrides import load_overrides
from normalize_item_icons import collect_model_ids, resolve_gui_sources


class TunerPreviewTests(unittest.TestCase):
    """预览必须和落盘 proxy 走同一条几何路径，否则本地微调就是自欺欺人。"""

    def test_gui_source_falls_back_when_proxy_parent_has_no_geometry(self):
        # arch 的 GUI 模型是本项自己的 proxy，其 parent 是原版 minecraft:block/block 模板(无 elements)。
        # 只解一层 parent 会得到 0 个源，预览因此报 "no GUI source geometry"，而生成器因为有
        # fallback 兜底早就正常出图——两边走了两条路。这里钉住兜底顺序。
        import json
        definition = json.loads((T.ITEMS_DIR / "arch.json").read_text(encoding="utf-8"))
        sources, status, ids = resolve_gui_sources(definition.get("model", {}), T.ASSETS, T.MOD_ID)
        self.assertEqual(status, "ok")
        self.assertTrue(sources, "arch 的 GUI 源不该为空")
        self.assertTrue(any(m.get("elements") for _r, _s, m, _p in sources))

    def test_render_icon_covers_every_registered_item(self):
        failures = []
        for item_id in T.item_ids():
            try:
                image, report = T.render_icon(item_id, {})
            except Exception as exc:  # noqa: BLE001 - 测试要收集全部失败项
                failures.append(f"{item_id}: {exc}")
                continue
            self.assertEqual(image.size, (T.ICON_SIZE, T.ICON_SIZE))
            self.assertIn("target_px", report)
        self.assertEqual(failures, [], "这些物品预览渲染失败: " + "; ".join(failures))

    def test_extra_yaw_turns_the_camera_and_keeps_the_geometry(self):
        # 额外朝向只改 display 旋转：预览必须出图、相机角度正确，且模型没被转坏。
        base, base_report = T.render_icon("wardrobe", {})
        turned, report = T.render_icon("wardrobe", {"yaw": 45})
        self.assertEqual(report["gui_rotation"], [30.0, 270.0, 0.0])
        self.assertEqual(base_report["gui_rotation"], [30.0, 225.0, 0.0])
        self.assertNotEqual(base.tobytes(), turned.tobytes(), "换了视角画面却完全一样")
        # 长边仍落在该物品的目标尺寸附近（换视角不该把图标放大或缩小失控）。
        # report 的 bounds 是投影单位（未乘 GUI scale 0.625），target_px 是槽内像素。
        scale = 0.625
        target = report["target_px"]
        width = (report["bounds"][2] - report["bounds"][0]) * scale
        height = (report["bounds"][3] - report["bounds"][1]) * scale
        self.assertLess(max(width, height), target * 1.35,
                        f"yaw 后可见尺寸失控: {width:.2f}x{height:.2f} / target {target}")

    def test_preview_matches_shipped_proxy_for_every_item(self):
        # 用该物品已保存的 override 作为候选：这时预览应当与落盘 proxy 逐像素一致。
        overrides = load_overrides(T.ROOT)
        diffs = []
        for item_id in T.item_ids():
            image, _report = T.render_icon(item_id, dict(overrides.get(item_id, {})))
            thumb = T.render_thumb(item_id)
            self.assertIsNotNone(thumb, f"{item_id} 没有 proxy")
            a, b = image.convert("RGBA"), _decode(thumb)
            if a.size != b.size:
                diffs.append(f"{item_id}: size {a.size} vs {b.size}")
                continue
            if a.tobytes() != b.tobytes():
                changed = sum(1 for pa, pb in zip(a.tobytes(), b.tobytes()) if pa != pb)
                diffs.append(f"{item_id}: 至少 {changed // 4} 像素不同")
        self.assertEqual(diffs, [], "预览与 proxy 不一致: " + "; ".join(diffs[:8]))


def _decode(b64: str):
    import base64, io
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(b64)))


if __name__ == "__main__":
    unittest.main()