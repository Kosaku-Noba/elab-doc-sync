"""esync push でファイル・ディレクトリ・glob・正規表現を指定して一部の文書だけ同期する。"""

import copy
import json
import sys
from unittest.mock import MagicMock, patch

import pytest
import yaml

from elab_doc_sync.cli import main


# テストから接続先の URL を差し替えるため、fixture が作ったクライアントを置く。
CLIENTS = []


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
    CLIENTS[:] = [client]
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


def preview(file, capsys):
    capsys.readouterr()
    with patch.object(sys, 'argv', ['esync', 'diff', '--json', '--', file]):
        main()
    return json.loads(capsys.readouterr().out)['documents']


def bodies(file, capsys):
    capsys.readouterr()
    with patch.object(sys, 'argv', ['esync', 'diff', '--json', '--bodies', '--', file]):
        main()
    return json.loads(capsys.readouterr().out)['documents']


def test_preview_bodies_compare_last_sync_with_local_and_remote_changes(project, capsys):
    root, remote = project
    [doc] = preview('docs/a.md', capsys)
    assert 'base_body' not in doc and 'local_body' not in doc, 'bodies are only added on request'
    [doc] = bodies('docs/a.md', capsys)
    assert (doc['base_label'], doc['base_body'], doc['local_body']) == ('新規作成', '', '# docs/a.md')

    assert push('docs/a.md') in (0, None)
    eid = next(iter(remote))
    (root / 'docs/a.md').write_text('# docs/a.md\n\nlocal edit', encoding='utf-8')
    [doc] = bodies('docs/a.md', capsys)
    assert doc['base_label'] == '前回の同期'
    assert (doc['base_body'], doc['local_body']) == ('# docs/a.md', '# docs/a.md\n\nlocal edit')
    assert 'remote_body' not in doc

    remote[eid]['body'] = remote[eid]['body'] + '\n\nremote edit'
    [doc] = bodies('docs/a.md', capsys)
    assert doc['remote_base_body'] == '# docs/a.md'
    assert doc['remote_body'].endswith('remote edit')
    assert doc['base_body'] == '# docs/a.md', 'the left side stays the last synced text, not the remote edit'


def test_preview_keeps_rename_read_only_and_identifies_existing_article(project, capsys):
    root, remote = project
    assert push('docs/a.md') in (0, None)
    eid = next(iter(remote))
    (root / 'docs/a.md').rename(root / 'docs/moved.md')
    [doc] = preview('docs/moved.md', capsys)
    assert doc['renamed_from'] == 'a.md' and doc['entity_id'] == eid
    assert doc['state'] == 'リネーム予定'
    assert push('--target', doc['selector'], '--expect-preview', 'stale', 'docs/moved.md') == 1
    assert json.loads((root / '.ids/mapping.json').read_text()) == {'a.md': eid}
    assert push('--target', doc['selector'], '--expect-preview', doc['preview_token'], 'docs/moved.md') in (0, None)
    assert titles(remote) == ['moved'] and remote[eid]['title'] == 'moved'


def test_preview_separates_overlapping_targets_and_identifies_asset_changes(project, capsys):
    root, remote = project
    cfg = root / '.elab-sync.yaml'
    data = yaml.safe_load(cfg.read_text())
    data['targets'][1]['docs_dir'] = 'docs/sub'
    cfg.write_text(yaml.safe_dump(data))
    file = 'docs/sub/c.md'
    (root / file).write_text('![plot](plot.png)')
    asset = root / 'docs/sub/plot.png'
    asset.write_bytes(b'first')
    first, second = preview(file, capsys)
    assert [first['selector'], second['selector']] == ['T', 'N']
    assert '+![plot](plot.png)' in second['local_diff']
    asset.write_bytes(b'second')
    assert preview(file, capsys)[1]['preview_token'] != second['preview_token']
    assert push('--target', second['selector'], '--expect-preview', second['preview_token'], file) == 1
    assert not remote
    (root / file).write_text('# final')
    assert push('--target', second['selector'], file) in (0, None)
    assert len(remote) == 1
    assert not (root / '.ids/mapping.json').exists()


def test_guarded_push_checks_link_destination_and_hides_url_credentials(project, capsys):
    from elab_doc_sync.cli import ELabFTWClient
    root, remote = project
    ELabFTWClient.return_value.base_url = 'https://user:password@example.test/elab'
    (root / 'docs/a.md').write_text('[B](b.md)')
    [doc] = preview('docs/a.md', capsys)
    assert doc['server'] == 'https://example.test/elab'
    assert push('docs/b.md') in (0, None)
    assert push('--expect-preview', doc['preview_token'], 'docs/a.md') == 1
    assert titles(remote) == ['b']
    [current] = preview('docs/a.md', capsys)
    assert push('--expect-preview', current['preview_token'], 'docs/a.md') in (0, None)
    article = next(item for item in remote.values() if item['title'] == 'a')
    assert 'https://example.test/elab/database.php' in article['body']
    assert 'password' not in article['body']


def test_guarded_push_refuses_replaced_attachment_after_article_creation(project, capsys):
    from elab_doc_sync.cli import ELabFTWClient
    root, remote = project
    (root / 'docs/a.md').write_text('![付録](appendix.md)', encoding='utf-8')
    appendix = root / 'docs/appendix.md'
    appendix.write_text('original')
    [doc] = preview('docs/a.md', capsys)
    client = ELabFTWClient.return_value
    create = client.create_item.side_effect

    def create_then_edit(**kw):
        appendix.write_text('replacement')
        return create(**kw)

    client.create_item.side_effect = create_then_edit
    assert push('--expect-preview', doc['preview_token'], 'docs/a.md') == 1
    client.upload_file.assert_not_called()


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
    assert push(*args) == 2
    assert message in capsys.readouterr().err
    assert remote == {}


def test_excluded_document_is_reported(project, capsys):
    root, remote = project
    assert push() in (0, None)
    with patch.object(sys, 'argv', ['esync', 'rm', 'docs/a.md']):
        main()
    count = len(remote)
    assert push('docs/a.md') == 2
    assert 'rm で同期対象から除外された文書です' in capsys.readouterr().err
    # ディレクトリ指定では除外済みの文書を飛ばして残りを push する
    (root / 'docs/b.md').write_text('b changed')
    assert push('docs') in (0, None)
    assert len(remote) == count
    assert {e['title']: e['body'] for e in remote.values()}['b'] == 'b changed'


def test_unselected_documents_are_not_fetched(project):
    root, remote = project
    assert push() in (0, None)
    ids = {e['title']: e['id'] for e in remote.values()}
    from elab_doc_sync.cli import ELabFTWClient
    client = ELabFTWClient()
    fetch = client.get_item.side_effect
    def get_item(eid):
        if eid != ids['a']:
            raise AssertionError(f'unselected document #{eid} was fetched')
        return fetch(eid)
    client.get_item.side_effect = get_item
    (root / 'docs/a.md').write_text('a changed')
    (root / 'docs/b.md').write_text('b changed')
    assert push('docs/a.md') in (0, None)
    assert remote[ids['a']]['body'] == 'a changed'


def test_rename_of_unselected_document_moves_mapping_only(project):
    root, remote = project
    assert push() in (0, None)
    ids = {e['title']: e['id'] for e in remote.values()}
    (root / 'docs/b.md').rename(root / 'docs/b2.md')
    (root / 'docs/a.md').write_text('a changed')
    assert push('docs/a.md') in (0, None)
    mapping = json.loads((root / '.ids/mapping.json').read_text())
    assert mapping['b2.md'] == ids['b'] and 'b.md' not in mapping
    assert remote[ids['b']]['title'] == 'b'
    assert len(remote) == 4
    assert push() in (0, None)
    assert remote[ids['b']]['title'] == 'b2'
    assert len(remote) == 4


def pull_json(*args, capsys):
    capsys.readouterr()
    with patch.object(sys, 'argv', ['esync', 'pull', '--json', *args]):
        try:
            code = main()
        except SystemExit as exc:
            code = exc.code
    return code, json.loads(capsys.readouterr().out)


def test_pull_selected_document_only(project, capsys):
    root, remote = project
    assert push('docs/a.md', 'docs/b.md') in (0, None)
    ids = {remote[eid]['title']: eid for eid in remote}
    for eid in remote.values():
        eid['body'] = eid['body'] + '\n\nremote edit'
    code, data = pull_json('--', 'docs/a.md', capsys=capsys)
    assert code in (0, None)
    [doc] = data['documents']
    assert (doc['path'], doc['result'], doc['conflict'], doc['entity_id']) == ('docs/a.md', 'pulled', False, ids['a'])
    assert 'remote edit' in (root / 'docs/a.md').read_text(encoding='utf-8')
    assert 'remote edit' not in (root / 'docs/b.md').read_text(encoding='utf-8'), 'other documents are not pulled'


def test_pull_selected_conflict_and_untracked_documents(project, capsys):
    root, remote = project
    assert push('docs/a.md') in (0, None)
    [eid] = remote
    remote[eid]['body'] = '# remote heading'
    (root / 'docs/a.md').write_text('# local heading', encoding='utf-8')
    code, data = pull_json('--', 'docs/a.md', capsys=capsys)
    assert code == 1
    [doc] = data['documents']
    assert doc['conflict'] is True and doc['path'] == 'docs/a.md'
    assert data['conflict_files'] and '<<<<<<< ローカル' in (root / 'docs/a.md').read_text(encoding='utf-8')

    code, data = pull_json('--', 'docs/b.md', capsys=capsys)
    assert code in (0, None)
    assert data['documents'] == [{'target': 'docs', 'entity': 'items', 'path': 'docs/b.md', 'result': 'untracked'}]


def test_pull_document_selection_rejects_id_and_dir(project, capsys):
    assert push('docs/a.md') in (0, None)
    code, _ = pull_json('--id', '1', '--entity', 'items', '--', 'docs/a.md', capsys=capsys)
    assert code == 2


def test_renamed_document_keeps_its_article_after_mv_then_pull(project, capsys):
    root, remote = project
    assert push('docs/a.md') in (0, None)
    [eid] = remote
    (root / 'docs/a.md').rename(root / 'docs/moved.md')
    remote[eid]['body'] = remote[eid]['body'] + '\n\nremote edit'
    code, data = pull_json('--', 'docs/moved.md', capsys=capsys)
    assert data['documents'][0]['result'] == 'untracked', 'pull does not follow a rename by itself'
    assert not (root / 'docs/a.md').exists()

    with patch.object(sys, 'argv', ['esync', 'mv', 'docs/a.md', 'docs/moved.md']):
        assert main() in (0, None)
    code, data = pull_json('--', 'docs/moved.md', capsys=capsys)
    [doc] = data['documents']
    # pull はファイル名を eLabFTW のタイトルに合わせる。紐付けを移したので本文は取り込まれ、別記事にはならない。
    assert (doc['path'], doc['entity_id'], doc['result']) == ('docs/a.md', eid, 'pulled')
    assert 'remote edit' in (root / 'docs/a.md').read_text(encoding='utf-8')
    assert not (root / 'docs/moved.md').exists()
    assert json.loads((root / '.ids/mapping.json').read_text(encoding='utf-8')) == {'a.md': eid}


def test_pull_json_hides_credentials_in_server_url(project, capsys):
    root, remote = project
    CLIENTS[0].base_url = 'https://user:secret@example.test'
    assert push('docs/a.md') in (0, None)
    [eid] = remote
    remote[eid]['body'] += '\n\nremote edit'
    for args in (('--dry-run',), ()):
        code, data = pull_json(*args, '--', 'docs/a.md', capsys=capsys)
        assert 'secret' not in json.dumps(data)
        assert data['documents'][0]['server'] == 'https://example.test'


def test_pull_of_one_document_leaves_links_in_other_documents(project, capsys):
    root, remote = project
    assert push('docs/a.md') in (0, None)
    [eid] = remote
    url = f'https://example.test/database.php?mode=view&id={eid}'
    (root / 'docs/b.md').write_text(f'[A]({url})', encoding='utf-8')
    assert push('docs/b.md') in (0, None)
    remote[eid]['body'] += '\n\nremote edit'
    code, data = pull_json('--', 'docs/a.md', capsys=capsys)
    assert [d['path'] for d in data['documents']] == ['docs/a.md']
    assert (root / 'docs/b.md').read_text(encoding='utf-8') == f'[A]({url})', 'only the selected document is rewritten'


def test_pull_json_path_follows_a_title_change(project, capsys):
    root, remote = project
    assert push('docs/a.md') in (0, None)
    [eid] = remote
    remote[eid]['title'] = 'renamed'
    code, data = pull_json('--dry-run', '--', 'docs/a.md', capsys=capsys)
    assert data['documents'][0]['path'] == 'docs/renamed.md', 'the plan names the file pull will write'
    code, data = pull_json('--', 'docs/a.md', capsys=capsys)
    assert data['documents'][0]['path'] == 'docs/renamed.md'
    assert (root / 'docs/renamed.md').exists() and not (root / 'docs/a.md').exists()


def test_expect_id_refuses_a_document_linked_to_another_article(project, capsys):
    root, remote = project
    assert push('docs/a.md', 'docs/b.md') in (0, None)
    ids = {remote[eid]['title']: eid for eid in remote}
    (root / 'docs/a.md').write_text('# local', encoding='utf-8')
    before = {eid: dict(value) for eid, value in remote.items()}
    assert push('--force', '--expect-id', str(ids['b']), 'docs/a.md') == 2, 'a.md is linked to another article'
    assert remote == before
    assert push('--force', '--expect-id', str(ids['a']), 'docs/a.md') in (0, None)
    assert remote[ids['a']]['body'].startswith('# local')

    remote[ids['a']]['body'] = '# remote'
    code, _ = pull_json('--force', '--expect-id', str(ids['b']), '--', 'docs/a.md', capsys=capsys)
    assert code == 2 and (root / 'docs/a.md').read_text(encoding='utf-8') == '# local'
    code, data = pull_json('--force', '--expect-id', str(ids['a']), '--', 'docs/a.md', capsys=capsys)
    assert data['documents'][0]['result'] == 'pulled'
    code, _ = pull_json('--expect-id', str(ids['a']), capsys=capsys)
    assert code == 2, '--expect-id needs exactly one document'


def test_pull_error_hides_credentials_in_urls(project, capsys):
    root, remote = project
    assert push('docs/a.md') in (0, None)
    CLIENTS[0].get_item.side_effect = ConnectionError(
        "Max retries exceeded with url: https://us'er:se'c\"ret@example.test:9/api/v2/items/1")
    capsys.readouterr()
    with patch.object(sys, 'argv', ['esync', 'pull', '--json', '--dry-run', '--', 'docs/a.md']):
        try:
            main()
        except SystemExit:
            pass
    out, err = capsys.readouterr()
    for text in (out, err):
        assert 'se\'c' not in text and 'us\'er' not in text, 'hide old-style credentials with quotes in errors'
    assert 'https://***@example.test:9' in json.loads(out)['documents'][0]['error']
    assert 'https://***@example.test:9' in err


def test_expect_id_also_checks_server_and_entity(project, capsys):
    root, remote = project
    assert push('docs/a.md') in (0, None)
    [eid] = remote
    (root / 'docs/a.md').write_text('# local', encoding='utf-8')
    before = json.dumps(remote, sort_keys=True)
    base = ['--force', '--expect-id', str(eid)]
    assert push(*base, '--expect-server', 'https://other.test', 'docs/a.md') == 2, 'same ID on another server'
    assert push(*base, '--expect-entity', 'experiments', 'docs/a.md') == 2, 'same ID of another type'
    assert json.dumps(remote, sort_keys=True) == before
    assert push(*base, '--expect-server', 'https://example.test/', '--expect-entity', 'resources', 'docs/a.md') in (0, None)


def test_mv_checks_the_expected_article(project, capsys):
    root, remote = project
    assert push('docs/a.md') in (0, None)
    [eid] = remote
    (root / 'docs/a.md').rename(root / 'docs/moved.md')
    with patch.object(sys, 'argv', ['esync', 'mv', '--expect-id', str(eid + 1), 'docs/a.md', 'docs/moved.md']):
        with pytest.raises(SystemExit) as exited:
            main()
    assert exited.value.code == 2
    assert json.loads((root / '.ids/mapping.json').read_text(encoding='utf-8')) == {'a.md': eid}
    with patch.object(sys, 'argv', ['esync', 'mv', '--expect-id', str(eid), '--expect-server', 'https://example.test',
                                    'docs/a.md', 'docs/moved.md']):
        assert main() in (0, None)
    assert json.loads((root / '.ids/mapping.json').read_text(encoding='utf-8')) == {'moved.md': eid}


def test_status_json_includes_a_unique_selector(project, capsys):
    root, remote = project
    capsys.readouterr()
    with patch.object(sys, 'argv', ['esync', 'status', '--json']):
        try:
            main()
        except SystemExit:
            pass
    selectors = {doc['file']: doc['selector'] for doc in json.loads(capsys.readouterr().out)['documents']}
    assert selectors['a.md'] == 'T' and selectors['n.md'] == 'N'


def test_skipped_pull_reports_where_the_body_is(project, capsys):
    root, remote = project
    assert push('docs/a.md') in (0, None)
    [eid] = remote
    # ローカルだけ編集して改名する（送信待ち）。記事のタイトルは a のまま。
    (root / 'docs/a.md').write_text('# local edit only', encoding='utf-8')
    with patch.object(sys, 'argv', ['esync', 'mv', 'docs/a.md', 'docs/new.md']):
        assert main() in (0, None)
    code, data = pull_json('--', 'docs/new.md', capsys=capsys)
    [doc] = data['documents']
    assert doc['result'] == 'skipped' and doc['path'] == 'docs/new.md', 'a skipped document stays where it is'
    assert (root / 'docs/new.md').exists()


def test_expectations_need_an_article_id_and_hide_the_expected_server(project, capsys):
    root, remote = project
    assert push('docs/a.md') in (0, None)
    [eid] = remote
    (root / 'docs/a.md').write_text('# local', encoding='utf-8')
    before = json.dumps(remote, sort_keys=True)
    assert push('--force', '--expect-server', 'https://other.test', 'docs/a.md') == 2, '--expect-server alone is refused'
    code, _ = pull_json('--force', '--expect-entity', 'experiments', '--', 'docs/a.md', capsys=capsys)
    assert code == 2 and (root / 'docs/a.md').read_text(encoding='utf-8') == '# local', 'a refused pull keeps local edits'
    (root / 'docs/a.md').rename(root / 'docs/moved.md')
    with patch.object(sys, 'argv', ['esync', 'mv', '--expect-entity', 'experiments', 'docs/a.md', 'docs/moved.md']):
        with pytest.raises(SystemExit) as exited:
            main()
    assert exited.value.code == 2
    assert json.loads((root / '.ids/mapping.json').read_text(encoding='utf-8')) == {'a.md': eid}
    assert json.dumps(remote, sort_keys=True) == before
    (root / 'docs/moved.md').rename(root / 'docs/a.md')
    capsys.readouterr()
    assert push('--force', '--expect-id', str(eid), '--expect-server', 'https://user:secret@other.test', 'docs/a.md') == 2
    assert 'secret' not in capsys.readouterr().err


def test_malformed_server_url_is_rejected_without_showing_it(project, capsys):
    root, remote = project
    cfg = root / '.elab-sync.yaml'
    data = yaml.safe_load(cfg.read_text(encoding='utf-8'))
    data['elabftw']['url'] = 'https:/user:pa ss@example.test'
    cfg.write_text(yaml.safe_dump(data), encoding='utf-8')
    capsys.readouterr()
    with patch.object(sys, 'argv', ['esync', 'pull', '--json', '--dry-run', '--id', '1', '--entity', 'items']):
        try:
            code = main()
        except SystemExit as exc:
            code = exc.code
    out, err = capsys.readouterr()
    assert code not in (0, None)
    assert 'pa ss' not in out + err and 'user' not in out + err
    assert 'url が不正です' in out + err


def _run(args, capsys):
    capsys.readouterr()
    with patch.object(sys, 'argv', ['esync', *args]):
        try:
            code = main()
        except SystemExit as exc:
            code = exc.code
    out, err = capsys.readouterr()
    return code, out + err


def test_password_parsed_as_a_port_is_rejected(project, capsys):
    root, remote = project
    cfg = root / '.elab-sync.yaml'
    data = yaml.safe_load(cfg.read_text(encoding='utf-8'))
    data['elabftw']['url'] = 'https://user:pa55word/example.test'
    cfg.write_text(yaml.safe_dump(data), encoding='utf-8')
    code, text = _run(['pull', '--json', '--dry-run', '--id', '1', '--entity', 'items'], capsys)
    assert code not in (0, None) and 'pa55word' not in text and 'url が不正です' in text


def test_profile_list_hides_url_credentials_and_add_rejects_bad_urls(project, capsys):
    root, remote = project
    cfg = root / '.elab-sync.yaml'
    data = yaml.safe_load(cfg.read_text(encoding='utf-8'))
    data['profiles'] = {'good': {'url': 'https://user:secret@elab.example.test', 'api_key': 'k'},
                        'bad': {'url': 'https:/user:pa ss@elab.example.test', 'api_key': 'k'},
                        'wide': {'url': '\u3000https://wuser:wpass@elab.example.test', 'api_key': 'k'}}
    cfg.write_text(yaml.safe_dump(data, allow_unicode=True), encoding='utf-8')
    code, text = _run(['profile', 'list'], capsys)
    for secret in ('secret', 'pa ss', 'wpass', 'wuser'):
        assert secret not in text
    assert 'https://elab.example.test' in text and '（不正な URL）' in text
    # MCP などに返す構造化結果も同じ値にする。
    from elab_doc_sync.cli import run_profile_list
    from types import SimpleNamespace
    urls = {p['name']: p['url'] for p in run_profile_list(SimpleNamespace(config=str(cfg))).data['profiles']}
    assert urls == {'default': 'https://example.test', 'good': 'https://elab.example.test',
                    'bad': '（不正な URL）', 'wide': '（不正な URL）'}
    before = cfg.read_text(encoding='utf-8')
    for url in ('https:/x:y z@host', 'https://example .test', 'https://elab.example.test:65536', '\u3000https://e.test',
                'https://elab.example.test/la\u200bb'):
        code, text = _run(['profile', 'add', 'other', '--url', url], capsys)
        assert code == 2 and 'y z' not in text and cfg.read_text(encoding='utf-8') == before, url


def test_init_and_clone_check_the_url_like_the_config_loader(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('ELABFTW_API_KEY', 'k')
    code, text = _run(['clone', '--url', 'https://example.test/lab site', '--id', '1'], capsys)
    assert code == 2 and 'url が不正です' in text.lower()
    assert not any(tmp_path.iterdir()), 'clone creates nothing for a bad URL'


def test_init_asks_again_for_a_url_the_config_loader_would_reject(tmp_path, monkeypatch, capsys):
    from argparse import Namespace
    from elab_doc_sync.cli import cmd_init
    monkeypatch.chdir(tmp_path)
    inputs = iter(['https://example.test/lab site', 'https://elab.example.com', 'n', '', '', 'items', 'md'])
    monkeypatch.setattr('builtins.input', lambda _: next(inputs))
    cfg = tmp_path / '.elab-sync.yaml'
    cmd_init(Namespace(config=str(cfg)))
    assert 'URL が不正です' in capsys.readouterr().out
    assert yaml.safe_load(cfg.read_text(encoding='utf-8'))['elabftw']['url'] == 'https://elab.example.com'


def test_init_strips_surrounding_spaces_before_checking_the_url(tmp_path, monkeypatch, capsys):
    from argparse import Namespace
    from elab_doc_sync.cli import cmd_init
    monkeypatch.chdir(tmp_path)
    inputs = iter(['\u3000https://elab.example.com/\u3000', 'n', '', '', 'items', 'md'])
    monkeypatch.setattr('builtins.input', lambda _: next(inputs))
    cfg = tmp_path / '.elab-sync.yaml'
    cmd_init(Namespace(config=str(cfg)))
    assert 'URL が不正です' not in capsys.readouterr().out
    assert yaml.safe_load(cfg.read_text(encoding='utf-8'))['elabftw']['url'] == 'https://elab.example.com'


def test_clone_hides_url_credentials(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    from elab_doc_sync.cli import run_clone
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('ELABFTW_API_KEY', 'k')
    client = MagicMock()
    client.get_item.side_effect = ConnectionError('offline')
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        result = run_clone(SimpleNamespace(url='https://user:secret@elab.example.test', id=[1], dir=None,
                                           entity='items', no_verify=False, dry_run=True),
                           echo=lambda message, stderr=False: print(message))
    assert result.data['server'] == 'https://elab.example.test'
    assert 'secret' not in json.dumps(result.data) + capsys.readouterr().out


def test_pulled_links_and_state_files_do_not_keep_url_credentials(project, capsys):
    root, remote = project
    CLIENTS[0].base_url = 'https://user:secret@example.test'
    assert push('docs/a.md') in (0, None)
    [eid] = remote
    state = root / '.ids' / 'a.md.state.json'
    states = list(root.glob('.ids/**/a.md.state.json'))
    assert states and all('secret' not in p.read_text(encoding='utf-8') for p in states)
    # 添付一覧にない画像・添付のリンクは、接続先 URL を補った絶対 URL になる。認証情報は含めない。
    remote[eid]['body'] = '![img](app/download.php?f=x.png&storage=1)\n\n[doc](/app/download.php?f=y.pdf&storage=1)'
    code, data = pull_json('--', 'docs/a.md', capsys=capsys)
    body = (root / 'docs/a.md').read_text(encoding='utf-8')
    assert 'secret' not in body and 'user:' not in body
    assert 'https://example.test/app/download.php?f=x.png' in body


def test_unmatched_attachment_links_become_absolute_without_credentials(tmp_path):
    from pathlib import Path as _Path
    from elab_doc_sync.sync import _localize_attachment_links
    body = '[doc](/app/download.php?f=y.pdf&storage=1)'
    result = _localize_attachment_links(body, [], tmp_path / 'att', tmp_path / 'docs/a.md',
                                        'https://user:secret@example.test', 'items', 1)
    assert result == '[doc](https://example.test/app/download.php?f=y.pdf&storage=1)'


def test_old_state_files_with_credentials_still_match_the_server(project, capsys):
    root, remote = project
    CLIENTS[0].base_url = 'https://user:secret@example.test'
    assert push('docs/a.md') in (0, None)
    [state] = list(root.glob('.ids/**/a.md.state.json'))
    data = json.loads(state.read_text(encoding='utf-8'))
    data['server'] = 'https://user:secret@example.test'  # 以前の版が記録した形
    state.write_text(json.dumps(data), encoding='utf-8')
    [doc] = preview('docs/a.md', capsys)
    assert doc.get('error') is None and doc['entity_id'] is not None


def test_url_helpers_ignore_credentials():
    from elab_doc_sync.sync import _hosts_match
    from elab_doc_sync.search import entity_url, _server_key
    from elab_doc_sync.mcp_server import _scrub
    assert _hosts_match('https://u:p@Elab.Example.test', 'https://elab.example.test')
    assert entity_url('https://u:p@h.test/', 'items', 3) == 'https://h.test/database.php?mode=view&id=3'
    assert _server_key('https://u:p@H.test/x/') == _server_key('https://h.test/x')
    assert _scrub({'server': 'https://u:p@h.test', 'messages': ['接続先はhttps://a:b$c@h.test/x']}, []) == \
        {'server': 'https://***@h.test', 'messages': ['接続先はhttps://***@h.test/x']}
    assert _scrub({'https://k:v@h.test': 1}, []) == {'https://***@h.test': 1}, 'mask URLs in dictionary keys too'
    text = '資料 https://example.test を参照。\n担当者 admin@example.test'
    assert _scrub(text, []) == text, 'do not mask past the URL'
    assert not _hosts_match('https://h.test/a', 'https://h.test/b'), 'another installation on the same host'
    assert _hosts_match('https://u:p@h.test/a/', 'https://h.test/a')


def test_merging_pull_rewrites_an_old_state_server_without_credentials(project, capsys):
    root, remote = project
    CLIENTS[0].base_url = 'https://user:secret@example.test'
    (root / 'docs/a.md').write_text('# a\n\nline1\n\nline2', encoding='utf-8')
    assert push('docs/a.md') in (0, None)
    [eid] = remote
    [state] = list(root.glob('.ids/**/a.md.state.json'))
    data = json.loads(state.read_text(encoding='utf-8'))
    data['server'] = 'https://user:secret@example.test'  # 以前の版が記録した形
    state.write_text(json.dumps(data), encoding='utf-8')
    (root / 'docs/a.md').write_text('# a\n\nline1 local\n\nline2', encoding='utf-8')
    remote[eid]['body'] = remote[eid]['body'].replace('line2', 'line2 remote')
    code, result = pull_json('--', 'docs/a.md', capsys=capsys)
    assert result['documents'][0]['result'] == 'pulled'
    assert 'secret' not in state.read_text(encoding='utf-8')


def test_url_masking_edges_and_subpath_links():
    import time
    from elab_doc_sync.config import _valid_server_url
    from elab_doc_sync.mcp_server import _scrub
    from elab_doc_sync.result import redact_url_credentials
    from elab_doc_sync.sync import _rewrite_elab_links_to_local
    assert not _valid_server_url('https://a@b:pass@host.test'), 'a raw @ in the user name is rejected'
    assert _valid_server_url('https://a%40b:pass@host.test')
    link = 'https://example.test?to=a@example.org'
    assert redact_url_credentials(link) == link, 'do not mask into the query'
    assert redact_url_credentials('x https://u:p@h.test#y@z') == 'x https://***@h.test#y@z'
    assert _scrub({'https://a:1@h.test': 'one', 'https://b:2@h.test': 'two'}, []) == \
        {'https://***@h.test': 'one', 'https://***@h.test (2)': 'two'}, 'keep both values after masking keys'
    started = time.monotonic()
    redact_url_credentials('a' * 200_000 + '://' + 'b' * 200_000)
    assert time.monotonic() - started < 1, 'linear in the text length'
    body = '[b](https://example.test/a/database.php?mode=view&id=7) [c](https://example.test/b/database.php?mode=view&id=7)'
    result = _rewrite_elab_links_to_local(body, 'https://user:pw@example.test/a', {'b.md': 7}, 'items')
    assert result == '[b](./b.md) [c](https://example.test/b/database.php?mode=view&id=7)'


def test_masking_diff_lines_and_old_style_userinfo_and_query_links():
    from elab_doc_sync.mcp_server import _scrub
    from elab_doc_sync.sync import _rewrite_elab_links_to_local
    lines = ['+https://u:secret@h.test/x', '-https://u:secret@h.test/y', ' see https://a@b:secret@h.test/z']
    assert _scrub(lines, []) == ['+https://***@h.test/x', '-https://***@h.test/y', ' see https://***@h.test/z']
    body = '[b](https://example.test/a/database.php?mode=view&id=7&lang=ja#section)'
    assert _rewrite_elab_links_to_local(body, 'https://example.test/a', {'b.md': 7}, 'items') == body, \
        'keep links whose extra query a local link cannot express'


def test_masking_stays_inside_the_url_and_links_match_whole_targets():
    from elab_doc_sync.mcp_server import _scrub
    from elab_doc_sync.sync import _rewrite_elab_links_to_local
    text = '[eLab](https://user:pw@elab.test)（担当：ops@example.org）'
    assert _scrub(text, []) == '[eLab](https://***@elab.test)（担当：ops@example.org）'
    body = '[x](https://example.test/database.php?mode=view&id=7%32&lang=ja#s)'
    assert _rewrite_elab_links_to_local(body, 'https://example.test', {'seven.md': 7}, 'items') == body, \
        'do not take id=7%32 for article 7'
    assert _rewrite_elab_links_to_local('[y](https://example.test/database.php?mode=view&id=7#s)',
                                        'https://example.test', {'seven.md': 7}, 'items') == '[y](./seven.md#s)'


def test_accepted_credentials_are_always_masked_and_masking_stops_at_quotes():
    from elab_doc_sync.config import _valid_server_url
    from elab_doc_sync.mcp_server import _scrub
    from elab_doc_sync.sync import _rewrite_elab_links_to_local
    for url in ('https://user:pa(ss)@elab.test', "https://user:pa'ss@elab.test", 'https://user:パス@elab.test',
                'https://user:pa,ss@elab.test'):
        assert not _valid_server_url(url), url
    accepted = 'https://us.er~1:p%28a%29s!$&*+;=-s@elab.test'
    assert _valid_server_url(accepted)
    assert _scrub(f'[x]({accepted}/a)', []) == '[x](https://***@elab.test/a)', 'every accepted form is masked whole'
    line = '+{"url":"https://elab.test","owner":"ops@example.org"}'
    assert _scrub(line, []) == line, 'do not mask past a closing quote'
    body = '[a](https://example.test/database.php?mode=view&id=7#section(1))'
    assert _rewrite_elab_links_to_local(body, 'https://example.test', {'seven.md': 7}, 'items') == \
        '[a](./seven.md#section(1))'


def test_unbalanced_fragments_and_non_latin1_credentials():
    from elab_doc_sync.config import _valid_server_url
    from elab_doc_sync.sync import _rewrite_elab_links_to_local
    body = '[a](<https://example.test/database.php?mode=view&id=7#sec)end>)'
    assert _rewrite_elab_links_to_local(body, 'https://example.test', {'seven.md': 7}, 'items') == body
    assert not _valid_server_url('https://user:%E3%83%91%E3%82%B9@elab.test'), 'Basic auth cannot send Japanese'
    assert not _valid_server_url('https://user:caf%E9@elab.test')
    assert _valid_server_url('https://user:pa%28ss%29@elab.test')


def test_mcp_error_fields_use_the_broad_mask_and_fragment_order_is_checked():
    import time
    from elab_doc_sync.mcp_server import _scrub
    from elab_doc_sync.result import redact_url_credentials
    from elab_doc_sync.sync import _rewrite_elab_links_to_local
    reply = {'warnings': ["エラー: key=value 形式で指定してください: https://u:pa'ss@h.test"], 'error': 'see https://a:b"c@h.test/x'}
    assert _scrub(reply, [], top=True) == {'warnings': ['エラー: key=value 形式で指定してください: https://***@h.test'],
                                           'error': 'see https://***@h.test/x'}
    # 広いマスクは元のキー名で、トップレベルの診断欄にだけ使う。利用者のメタデータの error 欄は加工しない。
    assert _scrub({'warnings': ["x https://u:pa'ss@h.test"]}, ['warn'], top=True) == {'***ings': ['x https://***@h.test']}
    meta = {'data': {'metadata': {'error': 'https://elab.test?to=a@example.org'}}, 'warnings': []}
    assert _scrub(meta, [], top=True) == meta
    from elab_doc_sync.result import error_text
    started = time.monotonic()
    error_text(ValueError('a' * 200_000 + ':/' + 'b' * 200_000))
    assert time.monotonic() - started < 1, 'error_text stays linear'
    body = '[a](<https://example.test/database.php?mode=view&id=7#sec)mid(end>)'
    assert _rewrite_elab_links_to_local(body, 'https://example.test', {'seven.md': 7}, 'items') == body
    started = time.monotonic()
    redact_url_credentials('a' * 200_000 + ':/' + 'b' * 200_000, loose=True)
    assert time.monotonic() - started < 1
