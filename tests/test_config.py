import os

from backend.acs.config import load_environment


def test_environment_precedence_and_literal_credentials(tmp_path, monkeypatch):
    for key in ('OPENAI_API_KEY', 'ACS_MODEL', 'ACS_MAX_ROUNDS'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('ACS_MODEL', 'shell-model')
    (tmp_path / '.env').write_text(
        'OPENAI_API_KEY=shared\nACS_MODEL=file-model\nACS_MAX_ROUNDS=2\n'
    )
    (tmp_path / '.env.local').write_text(
        'OPENAI_API_KEY="local-${LITERAL}-key"\nACS_MODEL=local-model\n'
    )
    monkeypatch.chdir(tmp_path.parent)

    load_environment(tmp_path)

    assert os.environ['OPENAI_API_KEY'] == 'local-${LITERAL}-key'
    assert os.environ['ACS_MODEL'] == 'shell-model'
    assert os.environ['ACS_MAX_ROUNDS'] == '2'


def test_environment_files_are_optional(tmp_path, monkeypatch):
    monkeypatch.delenv('ACS_MODEL', raising=False)
    load_environment(tmp_path)
    assert 'ACS_MODEL' not in os.environ
