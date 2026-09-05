from utils.paths import audio_dir, logs_dir, session_data_dir, user_data_root


def test_paths_use_override(monkeypatch, tmp_path):
    monkeypatch.setenv("PHONE_PROCTOR_DATA_DIR", str(tmp_path))
    assert user_data_root() == tmp_path.resolve()
    assert logs_dir().is_dir()
    assert session_data_dir().is_dir()
    assert audio_dir().is_dir()
