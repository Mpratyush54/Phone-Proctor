from tools.synthetic_manifest import done_matches, lock_hash, write_done, write_scenario_manifest


def test_done_cache_requires_full_hash(tmp_path):
    cfg = {"sid": "s1", "code": "generate_synthetic_data"}
    write_scenario_manifest(
        tmp_path,
        seeds={"a": 1},
        domains={"behavior": "neutral"},
        observable_truth={"face_visible": True},
        pair_id="p1",
        config=cfg,
    )
    lock = lock_hash(cfg)
    write_done(tmp_path, lock)
    assert done_matches(tmp_path, lock)
    assert not done_matches(tmp_path, lock_hash({**cfg, "code": "other"}))
    assert (tmp_path / "latent_truth.jsonl").exists()
    assert (tmp_path / "scenario_manifest.json").exists()
