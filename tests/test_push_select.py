"""esync push でファイル・ディレクトリ・glob・正規表現を指定して一部の文書だけ同期する。"""

import copy
import sys
from unittest.mock import MagicMock, patch

import pytest
import yaml

from elab_doc_sync.cli import main


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / '.elab-sync.yaml').write_text(yaml.safe_dump({
        'elabftw': {'url': 'https://example.test', 'api_key': 'SECRET'},
        'targets': [
            {'title': 'T', 'docs_dir': 'docs', 'id_file': '.ids/docs.id', 'body_format': 'md', 'pattern': '**/*.md'},
            {'title': 'N', 'docs_dir': 'notes', 'id_file': '.ids/notes/notes.id', 'body_format': 'md'},
        ],
    }))
    for path in ('docs/a.md', 'docs/b.md', 'docs/sub/c.md', 'notes/n.md'):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(f'# {path}')
    remote = {}
    client = MagicMock()
    client.base_url = 'https://example.test'

    def create(**kw):
        eid = max(remote, default=0) + 1
        remote[eid] = {'id': eid, 'body': '', 'title': '', 'content_type': 2}
        return eid
    client.create_item.side_effect = create
    client.get_item.side_effect = lambda eid: copy.deepcopy(remote[eid])
    client.update_item.side_effect = lambda eid, **kw: remote[eid].update(kw)
    client.list_uploads.return_value = []
    client.get_tags.return_value = []
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        yield tmp_path, remote


def push(*args):
    with patch.object(sys, 'argv', ['esync', 'push', *args]):
        try:
            return main()
        except SystemExit as exc:
            return exc.code


def titles(remote):
    return sorted(e['title'] for e in remote.values())


@pytest.mark.parametrize('args,expected', [
    (['docs/a.md'], ['a']),
    (['docs/a.md', 'notes/n.md'], ['a', 'n']),
    (['docs/sub'], ['c']),
    (['docs/*.md'], ['a', 'b']),
    (['docs/*'], ['a', 'b', 'c']),
    (['--regex', '^[bn]'], ['b', 'n']),
    (['docs/a.md', '--regex', '^a'], ['a']),
    (['--target', 'T', '--regex', '.'], ['a', 'b', 'c']),
])
def test_push_only_selected_documents(project, args, expected):
    root, remote = project
    assert push(*args) in (0, None)
    assert titles(remote) == expected


def test_selected_push_keeps_other_changes_pending(project, capsys):
    root, remote = project
    assert push() in (0, None)
    (root / 'docs/a.md').write_text('a changed')
    (root / 'docs/b.md').write_text('b changed')
    assert push('docs/a.md') in (0, None)
    bodies = {e['title']: e['body'] for e in remote.values()}
    assert bodies['a'] == 'a changed'
    assert bodies['b'] == '# docs/b.md'
    capsys.readouterr()
    assert push('--dry-run') in (0, None)
    out = capsys.readouterr().out
    assert '[a] 変更なし' in out and '[b] 変更あり' in out


def test_dry_run_lists_only_selected(project, capsys):
    root, remote = project
    assert push('docs/sub', '--dry-run') in (0, None)
    out = capsys.readouterr().out
    assert '[c]' in out and '[a]' not in out and '[n]' not in out
    assert remote == {}


@pytest.mark.parametrize('args,message', [
    (['docs/missing.md'], '同期対象の文書が見つかりません'),
    (['docs/a.md', 'other.txt'], '同期対象の文書が見つかりません'),
    (['--regex', 'zzz'], '同期対象の文書が見つかりません'),
    (['--regex', '('], '正規表現が不正です'),
    (['notes/n.md', '--target', 'T'], '同期対象の文書が見つかりません'),
])
def test_invalid_selection_pushes_nothing(project, args, message, capsys):
    root, remote = project
    assert push(*args) == 1
    assert message in capsys.readouterr().err
    assert remote == {}


def test_excluded_document_is_reported(project, capsys):
    root, remote = project
    assert push() in (0, None)
    with patch.object(sys, 'argv', ['esync', 'rm', 'docs/a.md']):
        main()
    count = len(remote)
    assert push('docs/a.md') == 1
    assert 'rm で同期対象から除外された文書です' in capsys.readouterr().err
    # ディレクトリ指定では除外済みの文書を飛ばして残りを push する
    (root / 'docs/b.md').write_text('b changed')
    assert push('docs') in (0, None)
    assert len(remote) == count
    assert {e['title']: e['body'] for e in remote.values()}['b'] == 'b changed'
