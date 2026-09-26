from schema import SCHEMA_VERSION, Lineage, Meta, ProductionPackage, film_id_of, version_of


def _pkg(**kw) -> ProductionPackage:
    meta = Meta(
        title="T", premise="P", target_duration_s=3.0, style="s",
        narration_voice_id="v", budget_usd=15.0,
    )
    return ProductionPackage(project_id="p_1", meta=meta, **kw)


def test_new_package_defaults_to_1_2_without_lineage():
    pkg = _pkg()
    assert pkg.schema_version == SCHEMA_VERSION == "1.2"
    assert pkg.lineage is None


def test_lineage_defaults():
    lineage = Lineage(film_id="p_1")
    assert lineage.version == 1
    assert lineage.parent_project_id is None
    assert lineage.note == ""
    assert lineage.from_stage is None
    assert lineage.changes == []


def test_legacy_package_is_v1_of_its_own_film():
    pkg = _pkg()
    assert film_id_of(pkg) == "p_1"
    assert version_of(pkg) == 1


def test_revision_reads_its_lineage():
    pkg = _pkg(lineage=Lineage(film_id="p_0", version=3, parent_project_id="p_2"))
    assert film_id_of(pkg) == "p_0"
    assert version_of(pkg) == 3


def test_1_1_document_still_parses():
    doc = {
        "schema_version": "1.1",
        "project_id": "p_old",
        "meta": {
            "title": "T", "premise": "P", "target_duration_s": 3, "style": "s",
            "narration_voice_id": "v", "budget_usd": 15,
        },
        "assets": [{"node_id": "ref_a", "type": "image", "prompt": "x"}],
        "narrative": {
            "logline": "",
            "scenes": [],
            "shots": [{"node_id": "shot_001", "scene_id": "scene_01"}],
        },
    }
    pkg = ProductionPackage.model_validate(doc)
    assert pkg.schema_version == "1.1"
    assert pkg.lineage is None
    assert pkg.assets[0].take is None
    assert pkg.narrative.shots[0].location_id == ""
    assert pkg.narrative.shots[0].subject_ids == []
