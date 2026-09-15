"""追跡解除の CLI と同期への影響を検証する。"""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest
import yaml

from elab_doc_sync.cli import main
from elab_doc_sync.config import load_config
from elab_doc_sync.sync import EachDocsSyncer


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / '.elab-sync.yaml').write_text(yaml.safe_dump({
        'elabftw': {'url': 'https://example.invalid', 'api_key': 'test'},
        'targets': [{'title': 'T', 'docs_dir': 'docs', 'id_file': '.ids/default.id'}],
    }))
    docs = tmp_path / 'docs'
    docs.mkdir()
    state = tmp_path / '.ids'
    state.mkdir()
    (state / 'mapping.json').write_text(json.dumps({'note.md': 42, 'keep.md': 43}))
    for name in ('note.md', 'keep.md'):
        (docs / name).write_text('# ' + name)
        for suffix in ('.hash', '.remote_hash', '.meta_hash', '.assets_hash'):
            (state / (name + suffix)).write_text('hash')
    return tmp_path


def run(*args):
    with patch.object(sys, 'argv', ['esync', 'rm', *args]), patch('elab_doc_sync.cli.ELabFTWClient') as client:
        main()
        client.assert_not_called()


def snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('selector', [('docs/note.md',), ('--id', '42', '--entity', 'resources')])
@pytest.mark.parametrize('delete', [False, True])
def test_untrack_preserves_other_document_and_prevents_push(project, selector, delete):
    run(*selector, *(['--local'] if delete else []))
    state = project / '.ids'
    assert json.loads((state / 'mapping.json').read_text()) == {'keep.md': 43}
    assert json.loads((state / 'excluded.json').read_text()) == ['note.md']
    assert (project / 'docs/note.md').exists() is not delete
    for suffix in ('.hash', '.remote_hash', '.meta_hash', '.assets_hash'):
        assert not (state / ('note.md' + suffix)).exists()
        assert (state / ('keep.md' + suffix)).read_text() == 'hash'
    cfg = load_config(project / '.elab-sync.yaml')
    syncer = EachDocsSyncer(MagicMock(), cfg.targets[0], project)
    assert [p.name for p in syncer.collect_files()] == ['keep.md']
    assert [r['filename'] for r in syncer.dry_run()] == ['keep.md']
    run('docs/keep.md')
    assert syncer.sync(force=True) == 0
    assert syncer.client.mock_calls == []
    # 削除後、同名文書を再作成しても除外が持続する。
    (project / 'docs/note.md').write_text('recreated')
    assert syncer.collect_files() == []


@pytest.mark.parametrize('extra', [[], ['--local']])
def test_dry_run_is_read_only(project, extra, capsys):
    before = snapshot(project)
    run('--id', '42', '--entity', 'items', '--dry-run', *extra)
    assert snapshot(project) == before
    assert '追跡解除予定' in capsys.readouterr().out


@pytest.mark.parametrize('args', [[], ['--id', '42'], ['--entity', 'items'],
    ['docs/unknown.md'], ['docs/note.md', 'docs/unknown.md'],
    ['--id', '42', '--entity', 'experiments'], ['docs/note.md', '--target', 'missing']])
def test_invalid_selection_does_not_modify_files(project, args):
    before = snapshot(project)
    with pytest.raises(SystemExit) as exc:
        run(*args)
    assert exc.value.code == 1
    assert snapshot(project) == before


def test_multiple_and_missing_local_file(project):
    (project / 'docs/note.md').unlink()
    run('--id', '42', '--id', '43', '--entity', 'items', '--local')
    assert json.loads((project / '.ids/mapping.json').read_text()) == {}
    assert list((project / 'docs').iterdir()) == []


def test_repeat_path_untrack(project):
    run('docs/note.md')
    before = snapshot(project)
    run('docs/note.md')
    assert snapshot(project) == before


def test_ambiguous_id_requires_target(project):
    path = project / '.elab-sync.yaml'
    data = yaml.safe_load(path.read_text())
    data['targets'].append({'title': 'Other', 'docs_dir': 'other', 'id_file': '.other/default.id'})
    path.write_text(yaml.safe_dump(data))
    (project / '.other').mkdir()
    (project / '.other/mapping.json').write_text('{"other.md": 42}')
    before = snapshot(project)
    with pytest.raises(SystemExit):
        run('--id', '42', '--entity', 'items')
    assert snapshot(project) == before
    run('--id', '42', '--entity', 'items', '--target', 'T')
    assert (project / '.other/mapping.json').read_text() == '{"other.md": 42}'


def test_legacy_dry_run_does_not_migrate(project):
    state = project / '.ids/mapping.json'
    legacy = project / '.elab-sync-ids'
    legacy.mkdir()
    state.rename(legacy / 'mapping.json')
    before = snapshot(project)
    run('docs/note.md', '--dry-run')
    assert snapshot(project) == before
    run('docs/note.md')
    assert json.loads(state.read_text()) == {'keep.md': 43}


def test_absolute_path_from_other_directory(project, monkeypatch, tmp_path_factory):
    monkeypatch.chdir(tmp_path_factory.mktemp('elsewhere'))
    run(str(project / 'docs/note.md'), '-c', str(project / '.elab-sync.yaml'))
    assert json.loads((project / '.ids/mapping.json').read_text()) == {'keep.md': 43}


@pytest.mark.parametrize('selector', [('docs/sub/note.md',), ('--id', '42', '--entity', 'items')])
def test_nested_document_local_deletion(project, selector):
    path = project / '.elab-sync.yaml'
    data = yaml.safe_load(path.read_text())
    data['targets'][0]['pattern'] = '**/*.md'
    path.write_text(yaml.safe_dump(data))
    sub = project / 'docs/sub'
    sub.mkdir()
    (project / 'docs/note.md').rename(sub / 'note.md')
    run(*selector, '--local')
    assert not (sub / 'note.md').exists()
    assert (project / 'docs/keep.md').exists()
