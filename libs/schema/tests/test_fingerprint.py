from schema import (
    Asset,
    AssetType,
    Meta,
    ProductionPackage,
    fingerprints,
    whole_seconds,
)


def _pkg() -> ProductionPackage:
    meta = Meta(
        title="T", premise="P", target_duration_s=6.0, style="s",
        narration_voice_id="v_meta", budget_usd=15.0,
    )
    return ProductionPackage(
        project_id="p_1",
        meta=meta,
        assets=[
            Asset(node_id="ref_a", type=AssetType.IMAGE, provider_hint="fal:flux-schnell",
                  prompt="a tree", spec={"width": 1024, "height": 576}),
            Asset(node_id="ref_b", type=AssetType.IMAGE, provider_hint="fal:flux-schnell",
                  prompt="a river", spec={"width": 1024, "height": 576}),
            Asset(node_id="shot_001", type=AssetType.VIDEO, provider_hint="fal:pixverse-v6-i2v",
                  depends_on=["ref_a"], reference_image_ids=["ref_a"], prompt="tree sways",
                  spec={"duration_s": 3.0, "aspect": "16:9"}),
            Asset(node_id="shot_002", type=AssetType.VIDEO, provider_hint="fal:pixverse-v6-i2v",
                  depends_on=["ref_b", "shot_001"], reference_image_ids=["ref_b"],
                  prompt="river flows", spec={"duration_s": 3.0, "aspect": "16:9"}),
            Asset(node_id="narration_full", type=AssetType.VOICEOVER,
                  provider_hint="elevenlabs:turbo-v2.5", text="Hello.", spec={}),
        ],
    )


def _changed(mutate) -> set[str]:
    base = fingerprints(_pkg())
    pkg = _pkg()
    mutate(pkg)
    after = fingerprints(pkg)
    return {nid for nid in base if base[nid] != after.get(nid)}


def test_identical_packages_have_identical_prints():
    assert fingerprints(_pkg()) == fingerprints(_pkg())
    assert all(len(v) == 64 for v in fingerprints(_pkg()).values())


def test_image_prompt_change_cascades_to_its_shot_only():
    def edit(p):
        p.asset_by_id("ref_a").prompt = "an oak"
    assert _changed(edit) == {"ref_a", "shot_001"}


def test_image_size_changes_print():
    def edit_w(p):
        p.asset_by_id("ref_b").spec["width"] = 512

    def edit_h(p):
        p.asset_by_id("ref_b").spec["height"] = 512
    assert _changed(edit_w) == {"ref_b", "shot_002"}
    assert _changed(edit_h) == {"ref_b", "shot_002"}


def test_video_prompt_change():
    def edit(p):
        p.asset_by_id("shot_002").prompt = "river roars"
    assert _changed(edit) == {"shot_002"}


def test_durations_hash_by_whole_second():
    def with_duration(d):
        pkg = _pkg()
        pkg.asset_by_id("shot_001").spec["duration_s"] = d
        return fingerprints(pkg)["shot_001"]
    assert with_duration(2.9) == with_duration(3.0) == with_duration(3.4)
    assert with_duration(3.6) != with_duration(3.0)


def test_aspect_is_ignored():
    def edit(p):
        p.asset_by_id("shot_001").spec["aspect"] = "9:16"
    assert _changed(edit) == set()


def test_take_changes_print():
    def edit(p):
        p.asset_by_id("shot_001").take = "abcd1234"
    assert _changed(edit) == {"shot_001"}


def test_continuation_edge_is_ignored():
    def edit(p):
        p.asset_by_id("shot_002").depends_on = ["ref_b"]
    assert _changed(edit) == set()


def test_voice_falls_back_to_meta():
    pkg = _pkg()
    implicit = fingerprints(pkg)["narration_full"]
    pkg.asset_by_id("narration_full").spec["voice_id"] = "v_meta"
    assert fingerprints(pkg)["narration_full"] == implicit
    pkg.asset_by_id("narration_full").spec["voice_id"] = "v_other"
    assert fingerprints(pkg)["narration_full"] != implicit


def test_node_ids_do_not_matter():
    pkg = _pkg()
    renamed = _pkg()
    ids = {"ref_a": "img_x", "ref_b": "img_y", "shot_001": "clip_1", "shot_002": "clip_2",
           "narration_full": "vo"}
    for asset in renamed.assets:
        asset.node_id = ids[asset.node_id]
        asset.depends_on = [ids[d] for d in asset.depends_on]
        asset.reference_image_ids = [ids[r] for r in asset.reference_image_ids]
    before, after = fingerprints(pkg), fingerprints(renamed)
    assert {ids[k]: v for k, v in before.items()} == after


def test_cycle_terminates():
    pkg = _pkg()
    a, b = pkg.asset_by_id("shot_001"), pkg.asset_by_id("shot_002")
    a.reference_image_ids = ["shot_002"]
    b.reference_image_ids = ["shot_001"]
    prints = fingerprints(pkg)
    assert set(prints) == {a.node_id for a in pkg.assets}


def test_whole_seconds():
    assert whole_seconds(None) is None
    assert whole_seconds(0) is None
    assert whole_seconds("3.4") == 3
    assert whole_seconds(2.5) == 2
