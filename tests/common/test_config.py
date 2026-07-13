import pytest

from sfi.common import config


def test_load_env_parses_and_skips_noise(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# a comment\n"
        "\n"
        "ANTHROPIC_API_KEY=sk-test-123\n"
        "QUOTED='hello'\n"
        "not a kv line\n"
    )
    env = config.load_env(env_file)
    assert env == {"ANTHROPIC_API_KEY": "sk-test-123", "QUOTED": "hello"}


def test_missing_api_key_rejected(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OTHER=1\n")
    with pytest.raises(config.ConfigError):
        config.api_key(env_file)
