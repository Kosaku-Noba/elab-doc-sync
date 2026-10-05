"""Safety scenarios using a stateful remote, rather than fixed API responses."""
import copy
import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
import yaml

from elab_doc_sync.cli import cmd_pull, cmd_link, cmd_mv, cmd_status, main
from elab_doc_sync.config import TargetConfig, load_config
from elab_doc_sync.safety import snapshot, restore, atomic_write, project_lock, local_transaction, RECOVERY, BACKUPS
from elab_doc_sync.sync import EachDocsSyncer, ConflictError


@pytest.fixture
def project(tmp_path):
    (tmp_path / "docs").mkdir()
    cfg = tmp_path / '.elab-sync.yaml'
    cfg.write_text(yaml.safe_dump({
        'elabftw': {'url': 'https://example.test', 'api_key': 'SECRET'},
        'targets': [{'title': 'T', 'docs_dir': 'docs', 'id_file': '.ids/default.id', 'body_format': 'md'}],
    }))
    remote = {}
    client = MagicMock()
    client.base_url = 'https://example.test'
    def create(**kw):
        eid = max(remote, default=0) + 1
        remote[eid] = {'id': eid, 'body': '', 'title': '', 'content_type': 2}
        return eid
    def get(eid):
        if eid not in remote:
            response = requests.Response()
            response.status_code = 404
            raise requests.HTTPError(response=response)
        return copy.deepcopy(remote[eid])
    client.create_item.side_effect = create
    client.get_item.side_effect = get
    client.update_item.side_effect = lambda eid, **kw: remote[eid].update(kw)
    client.list_uploads.return_value = []
    client.get_tags.side_effect = lambda entity, eid: copy.deepcopy(remote[eid].get("tags") or [])
    client.add_tag.side_effect = lambda entity, eid, tag: remote[eid].setdefault("tags", []).append(tag)
    client.resolve_category_id.side_effect = lambda entity, category, current=None: int(category)
    client.patch_entity.side_effect = lambda entity, eid, **kw: remote[eid].update(kw)
    target = load_config(cfg).targets[0]
    syncer = EachDocsSyncer(client, target, tmp_path)
    def args(**kw):
        data = dict(config=str(cfg), target=None, dry_run=False, force=False, id=None, entity=None, dir=None, auto=False)
        data.update(kw)
        return Namespace(**data)
    return tmp_path, client, remote, syncer, args


def push_note(project, body='original'):
    root, client, remote, syncer, args = project
    (root / 'docs/a.md').write_text(body)
    assert syncer.sync() == 1
    return root, client, remote, syncer, args


@pytest.mark.parametrize('local,remote_change,expected', [
    (False, False, '最新'), (True, False, '送信待ち'),
    (False, True, '取得待ち'), (True, True, '競合'),
])
def test_three_way_status_and_pull(project, local, remote_change, expected):
    root, client, remote, syncer, args = push_note(project)
    if local:
        (root / 'docs/a.md').write_text('local')
    if remote_change:
        remote[1]['body'] = 'remote'
    assert syncer.inspect('a.md', 1)['state'] == expected
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        code = cmd_pull(args())
    assert code == int(local and remote_change)
    assert (root / 'docs/a.md').read_text().strip() == ('local' if local else 'remote' if remote_change else 'original')
    if not local and remote_change:
        assert syncer.inspect('a.md', 1)['state'] == '最新'


def test_rename_does_not_overwrite_local_edits(project):
    root, client, remote, syncer, args = push_note(project)
    remote[1]['title'] = 'renamed'
    (root / 'docs/a.md').write_text('unsent')
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        assert cmd_pull(args()) == 1
    assert (root / 'docs/a.md').read_text() == 'unsent'
    assert not (root / 'docs/renamed.md').exists()


def test_remote_title_only_change_pulls_safely(project):
    root, client, remote, syncer, args = push_note(project)
    remote[1]['title'] = 'renamed'
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        assert cmd_pull(args()) == 0
    assert (root / 'docs/renamed.md').read_text().strip() == 'original'
    assert syncer._load_mapping() == {'renamed.md': 1}
    assert syncer.inspect('renamed.md', 1)['state'] == '最新'


@pytest.mark.parametrize('status', [401, 403, 404, 429, 500, None])
def test_network_failure_never_creates_replacement(project, status):
    root, client, remote, syncer, args = push_note(project)
    (root / 'docs/a.md').write_text('local')
    response = requests.Response()
    response.status_code = status or 500
    client.get_item.side_effect = requests.HTTPError(response=response) if status else requests.Timeout()
    assert syncer.sync(force=True) == 0
    assert syncer.failures == 1
    assert client.create_item.call_count == 1
    assert syncer._load_mapping() == {'a.md': 1}


def test_unknown_create_result_blocks_retry(project):
    root, client, remote, syncer, args = project
    (root / 'docs/a.md').write_text('local')
    client.create_item.side_effect = requests.Timeout('response lost')
    with pytest.raises(requests.Timeout):
        syncer.sync()
    with pytest.raises(ConflictError, match='作成結果が不明'):
        syncer.sync()
    assert client.create_item.call_count == 1


def test_patch_failure_retains_id_and_retries_without_post(project):
    root, client, remote, syncer, args = project
    (root / 'docs/a.md').write_text('local')
    update = client.update_item.side_effect
    client.update_item.side_effect = requests.Timeout('PATCH failed')
    assert syncer.sync() == 0
    assert syncer._load_mapping() == {'a.md': 1}
    assert not syncer._hash_path('a.md').exists()
    client.update_item.side_effect = update
    # A failed request before application leaves the original empty entity.
    assert syncer.sync() == 1
    assert client.create_item.call_count == 1


def test_post_patch_response_loss_is_resumable(project):
    root, client, remote, syncer, args = project
    (root / 'docs/a.md').write_text('local')
    update = client.update_item.side_effect
    def apply_then_fail(eid, **kw):
        update(eid, **kw)
        raise requests.Timeout('response lost')
    client.update_item.side_effect = apply_then_fail
    assert syncer.sync() == 0
    client.update_item.side_effect = update
    assert syncer.sync() == 1
    assert client.create_item.call_count == 1


def test_failed_metadata_is_not_marked_complete(project):
    root, client, remote, syncer, args = project
    (root / 'docs/a.md').write_text('local')
    syncer.target.tags = ['tag']
    client.add_tag.side_effect = requests.Timeout()
    assert syncer.sync() == 0
    assert syncer.failures == 1
    assert syncer._pending()
    assert not syncer._state('a.md')
    client.add_tag.side_effect = lambda entity, eid, tag: remote[eid].setdefault("tags", []).append(tag)
    assert syncer.sync() == 1
    assert client.create_item.call_count == 1


def test_force_pull_backup_restore_and_undo_restore(project):
    root, client, remote, syncer, args = push_note(project, 'unsent original')
    (root / 'docs/a.md').write_text('local edits')
    remote[1]['body'] = 'remote edits'
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        assert cmd_pull(args(force=True)) == 0
    manifest = next((root / BACKUPS).glob('*/manifest.json'))
    backup_id = manifest.parent.name
    restore(root, backup_id, dry_run=True)
    assert (root / 'docs/a.md').read_text().strip() == 'remote edits'
    restore(root, backup_id)
    assert (root / 'docs/a.md').read_text() == 'local edits'
    undo = [p for p in (root / BACKUPS).glob('*/manifest.json') if p != manifest][0]
    restore(root, undo.parent.name)
    assert (root / 'docs/a.md').read_text().strip() == 'remote edits'


def test_force_push_saves_remote_without_secrets(project):
    root, client, remote, syncer, args = push_note(project)
    remote[1]['body'] = 'remote edits'
    assert syncer.sync(force=True) == 1
    manifest = next((root / BACKUPS).glob('*/manifest.json'))
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    assert saved['remote']['body'] == 'remote edits'
    assert 'SECRET' not in manifest.read_text(encoding="utf-8")
    restore(root, manifest.parent.name)
    exported = json.loads((root / BACKUPS / f'{manifest.parent.name}-remote.json').read_text(encoding="utf-8"))
    assert exported['body'] == 'remote edits'
    assert remote[1]['body'] == 'original'


def test_backup_failure_prevents_pull_changes(project):
    root, client, remote, syncer, args = push_note(project)
    remote[1]['body'] = 'remote'
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client), patch('elab_doc_sync.safety.snapshot', side_effect=OSError('disk full')):
        assert cmd_pull(args()) == 1
    assert (root / 'docs/a.md').read_text() == 'original'
    assert not (root / RECOVERY).exists()


def test_interrupted_transaction_is_recoverable(tmp_path):
    note = tmp_path / 'note.md'
    note.write_text('before')
    with pytest.raises(RuntimeError):
        with local_transaction(tmp_path, [note], 'failure'):
            note.write_text('partial')
            raise RuntimeError()
    pending = json.loads((tmp_path / RECOVERY).read_text())
    restore(tmp_path, pending['backup'])
    assert note.read_text() == 'before'
    assert not (tmp_path / RECOVERY).exists()


def test_atomic_write_keeps_existing_on_replace_error(tmp_path):
    note = tmp_path / 'note.md'
    note.write_text('before')
    with patch('elab_doc_sync.safety.os.replace', side_effect=OSError('failed')):
        with pytest.raises(OSError):
            atomic_write(note, 'after')
    assert note.read_text() == 'before'
    assert list(tmp_path.iterdir()) == [note]


def test_concurrent_writer_is_rejected(tmp_path):
    with project_lock(tmp_path):
        with pytest.raises(RuntimeError, match='別のesync'):
            with project_lock(tmp_path):
                pytest.fail('second writer entered')
    with project_lock(tmp_path):
        pass


def test_readonly_status_and_pull_dry_run(project):
    root, client, remote, syncer, args = push_note(project)
    remote[1]['body'] = 'remote'
    def tree():
        return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    before = tree()
    client.reset_mock()
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        assert cmd_status(args()) == 0
        assert cmd_pull(args(dry_run=True)) == 0
    assert tree() == before
    client.download_upload.assert_not_called()
    client.update_item.assert_not_called()


@pytest.mark.parametrize('title', ['../escape', '/absolute', '..\\escape', 'sub/note'])
def test_pull_rejects_unsafe_remote_title(project, title):
    root, client, remote, syncer, args = push_note(project)
    remote[1]['title'] = title
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        assert cmd_pull(args(force=True)) == 1
    assert (root / 'docs/a.md').read_text() == 'original'
    assert not (root / BACKUPS).exists()


def test_markdown_math_roundtrip(project):
    body = '# Test\n\n$a_b$ and **bold**\n\n$$x < y$$\n\n`<literal>`'
    root, client, remote, syncer, args = push_note(project, body)
    assert remote[1]['content_type'] == 2
    assert remote[1]['body'] == body
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        assert cmd_pull(args(force=True)) == 0
    assert (root / 'docs/a.md').read_text().strip() == body
    assert syncer.sync() == 0


def test_mv_and_relink_preserve_entity(project):
    root, client, remote, syncer, args = push_note(project)
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        cmd_mv(args(old=str(root / 'docs/a.md'), new=str(root / 'docs/b.md')))
    assert remote[1]['title'] == 'a'
    assert syncer.sync() == 1
    assert remote[1]['title'] == 'b'
    syncer.untrack({'b.md'}, syncer._load_mapping())
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        cmd_link(args(entity_id=1, file='b.md'))
    assert not syncer._load_excluded()
    (root / 'docs/c.md').write_text('new document')
    assert syncer.sync() == 1
    assert syncer._load_mapping() == {'b.md': 1, 'c.md': 2}
    assert remote[1]['body'] == 'original'


def test_merge_rejected_before_network(project):
    root, client, remote, syncer, args = project
    cfg = root / '.elab-sync.yaml'
    raw = yaml.safe_load(cfg.read_text())
    raw['targets'][0]['mode'] = 'merge'
    cfg.write_text(yaml.safe_dump(raw))
    with pytest.raises(SystemExit) as exc:
        load_config(cfg)
    assert exc.value.code == 2
    assert client.mock_calls == []


def test_image_attachment_and_document_link_roundtrip(project):
    import hashlib
    root, client, remote, syncer, args = project
    uploads = {}
    data_by_upload = {}
    def upload(entity, eid, path):
        source = Path(path)
        content = source.read_bytes()
        uid = len(data_by_upload) + 1
        data_by_upload[uid] = content
        record = {'id': uid, 'real_name': source.name, 'long_name': f'blob{uid}',
                  'storage': '1', 'filesize': len(content), 'hash': hashlib.sha256(content).hexdigest()}
        uploads.setdefault(eid, []).append(record)
        return {'id': uid, 'url': f'https://example.test/app/download.php?f=blob{uid}&name={source.name}&storage=1'}
    client.upload_file.side_effect = upload
    client.list_uploads.side_effect = lambda entity, eid: copy.deepcopy(uploads.get(eid, []))
    client.download_upload.side_effect = lambda **kw: data_by_upload[kw['upload_id']]
    (root / 'docs/picture.png').write_bytes(b'old image')
    (root / 'attachments').mkdir()
    (root / 'attachments/report.csv').write_bytes(b'old csv')
    syncer.target.attachments_dir = 'attachments'
    config_path = root / '.elab-sync.yaml'
    cfg = yaml.safe_load(config_path.read_text())
    cfg['targets'][0]['attachments_dir'] = 'attachments'
    config_path.write_text(yaml.safe_dump(cfg))
    (root / 'docs/a.md').write_text('![image](picture.png)\n\n[other](./b.md#section)')
    (root / 'docs/b.md').write_text('# section')
    assert syncer.sync() == 2
    assert 'id=2#section' in remote[1]['body']
    assert 'app/download.php' in remote[1]['body']
    image_record = next(u for u in uploads[1] if u['real_name'] == 'picture.png')
    image_record['hash'] = hashlib.sha256(b'new image').hexdigest()
    data_by_upload[image_record['id']] = b'new image'
    assert syncer.inspect('a.md', 1)['state'] == '取得待ち'
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        assert cmd_pull(args(id=[1], entity='items')) == 0
    assert (root / 'docs/images/items_1_picture.png').read_bytes() == b'new image'
    assert (root / 'attachments/report.csv').read_bytes() == b'old csv'
    assert '[other](./b.md#section)' in (root / 'docs/a.md').read_text()
    assert syncer.sync() == 0


def test_local_asset_edit_is_not_overwritten_by_remote_change(project):
    root, client, remote, syncer, args = project
    (root / 'docs/picture.png').write_bytes(b'original image')
    (root / 'docs/a.md').write_text('![image](picture.png)')
    client.upload_file.return_value = {'url': 'https://example.test/app/download.php?f=blob'}
    assert syncer.sync() == 1
    (root / 'docs/picture.png').write_bytes(b'local image')
    remote[1]['body'] += '\nremote edit'
    assert syncer.inspect('a.md', 1)['state'] == '競合'
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        assert cmd_pull(args()) == 1
    client.download_upload.assert_not_called()


def test_restore_cannot_silently_forget_created_entity(project):
    root, client, remote, syncer, args = project
    (root / 'docs/a.md').write_text('local')
    backup_id = snapshot(root, syncer.backup_paths(), 'before first push')
    assert syncer.sync() == 1
    restore(root, backup_id)
    with pytest.raises(ConflictError, match='作成記録'):
        syncer.sync()
    assert client.create_item.call_count == 1
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        cmd_link(args(entity_id=1, file='a.md'))
    assert syncer.sync() == 0


def test_unknown_post_can_be_resolved_as_new(project):
    root, client, remote, syncer, args = project
    (root / 'docs/a.md').write_text('local')
    create = client.create_item.side_effect
    client.create_item.side_effect = requests.Timeout()
    with pytest.raises(requests.Timeout):
        syncer.sync()
    client.create_item.side_effect = create
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        cmd_link(args(entity_id=None, file='a.md', new=True))
    assert syncer.sync() == 1
    assert len(remote) == 1


def test_successful_entity_is_not_repeated_after_another_fails(project):
    root, client, remote, syncer, args = project
    (root / 'docs/a.md').write_text('a')
    (root / 'docs/b.md').write_text('b')
    update = client.update_item.side_effect
    def fail_second(eid, **kw):
        if eid == 2:
            raise requests.Timeout()
        update(eid, **kw)
    client.update_item.side_effect = fail_second
    assert syncer.sync() == 1
    assert syncer.failures == 1
    client.update_item.side_effect = update
    client.update_item.reset_mock()
    assert syncer.sync() == 1
    assert [c.args[0] for c in client.update_item.call_args_list] == [2]
    assert client.create_item.call_count == 2


def test_damaged_backup_is_rejected_before_any_write(tmp_path):
    note = tmp_path / 'a.md'
    note.write_text('before')
    backup_id = snapshot(tmp_path, [note], 'test')
    note.write_text('after')
    manifest = json.loads((tmp_path / BACKUPS / backup_id / 'manifest.json').read_text())
    blob = manifest['files']['a.md']['sha256']
    (tmp_path / BACKUPS / backup_id / blob).write_bytes(b'corrupted')
    with pytest.raises(ValueError, match='破損'):
        restore(tmp_path, backup_id)
    assert note.read_text() == 'after'


def test_symlink_replaced_after_backup_is_not_followed(tmp_path):
    note = tmp_path / 'a.md'
    outside = tmp_path / 'outside.md'
    note.write_text('before')
    outside.write_text('must preserve')
    backup_id = snapshot(tmp_path, [note], 'test')
    note.unlink()
    try:
        note.symlink_to(outside)
    except OSError:
        pytest.skip('symlink creation unavailable')
    with pytest.raises(ValueError, match='シンボリックリンク'):
        restore(tmp_path, backup_id)
    assert outside.read_text() == 'must preserve'


def test_profile_change_blocks_force_push(project):
    root, client, remote, syncer, args = push_note(project)
    client.base_url = 'https://other.test'
    assert syncer.sync(force=True) == 0
    assert syncer.failures == 1
    assert client.update_item.call_count == 1


def test_pull_same_id_on_two_profiles_requires_target(project):
    root, client, remote, syncer, args = push_note(project)
    cfg_path = root / '.elab-sync.yaml'
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg['profiles'] = {'other': {'url': 'https://other.test', 'api_key': 'OTHER-SECRET'}}
    cfg['targets'].append({'title': 'Other', 'docs_dir': 'other', 'id_file': '.other/default.id', 'profile': 'other'})
    cfg_path.write_text(yaml.safe_dump(cfg))
    (root / '.other').mkdir()
    (root / '.other/mapping.json').write_text('{"other.md": 1}')
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        with pytest.raises(ValueError, match='複数接続先'):
            cmd_pull(args(id=[1], entity='items'))
        assert cmd_pull(args(id=[1], entity='items', target='T')) == 0


def test_cli_exit_code_signals_conflict(project):
    import sys
    root, client, remote, syncer, args = push_note(project)
    (root / 'docs/a.md').write_text('local')
    remote[1]['body'] = 'remote'
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client), patch.object(sys, 'argv', ['esync', 'push', '-c', str(root / '.elab-sync.yaml')]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    assert remote[1]['body'] == 'remote'


def test_legacy_hash_migration_keeps_baseline(project):
    root, client, remote, syncer, args = project
    (root / 'docs/a.md').write_text('local')
    remote[1] = {'id': 1, 'body': 'local', 'title': 'a', 'content_type': 2}
    legacy = root / '.elab-sync-ids'
    legacy.mkdir()
    (legacy / 'mapping.json').write_text('{"a.md": 1}')
    syncer._save_hash('a.md', 'local')
    syncer._save_remote_hash('a.md', 'local')
    assert syncer._load_mapping(migrate=False) == {'a.md': 1}
    assert not syncer.mapping_file.exists()
    assert syncer.inspect('a.md', 1)['state'] == '最新'
    assert syncer.sync() == 0
    assert syncer.mapping_file.exists()
    assert client.create_item.call_count == 0


def test_nested_document_asset_change_is_detected(project):
    root, client, remote, syncer, args = project
    syncer.target.pattern = '**/*.md'
    (root / 'docs/sub').mkdir()
    (root / 'docs/sub/a.md').write_text('![picture](photo.png)')
    (root / 'docs/sub/photo.png').write_bytes(b'original')
    client.upload_file.return_value = {'url': 'https://example.test/app/download.php?f=image'}
    assert syncer.sync() == 1
    (root / 'docs/sub/photo.png').write_bytes(b'edited')
    assert syncer.inspect('a.md', 1)['state'] == '送信待ち'
    assert syncer.sync() == 1


def test_body_format_change_is_sent_without_force(project):
    root, client, remote, syncer, args = push_note(project, '# Title')
    syncer.target.body_format = 'html'
    assert syncer.inspect('a.md', 1)['state'] == '送信待ち'
    assert syncer.sync() == 1
    assert remote[1]['content_type'] == 1
    assert '<h1' in remote[1]['body']
    assert syncer.inspect('a.md', 1)['state'] == '最新'


@pytest.mark.parametrize('remote_field,changed_value', [('category', 99), ('tags', ['other-user'])])
def test_resume_stops_after_remote_metadata_change(project, remote_field, changed_value):
    root, client, remote, syncer, args = push_note(project)
    (root / 'docs/a.md').write_text('local edit')
    update = client.update_item.side_effect
    def apply_then_fail(eid, **kw):
        update(eid, **kw)
        raise requests.Timeout('response lost')
    client.update_item.side_effect = apply_then_fail
    assert syncer.sync() == 0
    remote[1][remote_field] = changed_value
    client.update_item.side_effect = update
    client.update_item.reset_mock()
    assert syncer.sync() == 0
    assert syncer.failures == 1
    client.update_item.assert_not_called()
    assert remote[1][remote_field] == changed_value


def test_resume_stops_after_remote_attachment_change(project):
    root, client, remote, syncer, args = push_note(project)
    (root / 'docs/a.md').write_text('local edit')
    update = client.update_item.side_effect
    client.update_item.side_effect = requests.Timeout()
    assert syncer.sync() == 0
    client.list_uploads.return_value = [{'id': 77, 'real_name': 'external.csv', 'hash': 'changed'}]
    client.update_item.side_effect = update
    client.update_item.reset_mock()
    assert syncer.sync() == 0
    client.update_item.assert_not_called()


@pytest.mark.parametrize('syntax', ['![image]({})', '[video]({})', '[file]({})'])
def test_outside_asset_reference_never_uploads(project, syntax):
    from elab_doc_sync.sync import _rewrite_images, _rewrite_videos, _rewrite_file_links
    root, client, remote, syncer, args = project
    suffix = '.png' if 'image' in syntax else '.mp4' if 'video' in syntax else '.txt'
    outside = root.parent / ('outside' + suffix)
    outside.write_bytes(b'private bytes')
    handler = _rewrite_images if 'image' in syntax else _rewrite_videos if 'video' in syntax else _rewrite_file_links
    try:
        with pytest.raises(ValueError, match='プロジェクト外'):
            handler(syntax.format('../../' + outside.name), 'items', 1, client, root / 'docs', root, strict=True)
        client.upload_file.assert_not_called()
    finally:
        outside.unlink()


def test_hidden_project_configuration_never_uploads(project):
    from elab_doc_sync.sync import _rewrite_file_links
    root, client, remote, syncer, args = project
    with pytest.raises(ValueError, match='隠しファイル'):
        _rewrite_file_links('[config](../.elab-sync.yaml)', 'items', 1, client, root / 'docs', root, strict=True)
    client.upload_file.assert_not_called()


def test_clone_preview_does_not_create_project(project, monkeypatch):
    from elab_doc_sync.cli import cmd_clone
    root, client, remote, syncer, args = push_note(project)
    monkeypatch.setenv('ELABFTW_API_KEY', 'test-key')
    clone_root = root / 'clone'
    before = client.download_upload.call_count
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        assert cmd_clone(args(url=client.base_url, id=[1], entity='items', dir=str(clone_root), no_verify=False, dry_run=True)) == 0
    assert not clone_root.exists()
    assert client.download_upload.call_count == before


def test_unresolved_local_operation_cannot_be_replaced(tmp_path):
    note = tmp_path / 'a.md'
    note.write_text('before')
    with pytest.raises(RuntimeError):
        with local_transaction(tmp_path, [note], 'first'):
            note.write_text('partial')
            raise RuntimeError('interrupted')
    pending = (tmp_path / RECOVERY).read_bytes()
    with pytest.raises(RuntimeError, match='未完了'):
        with local_transaction(tmp_path, [note], 'second'):
            pytest.fail('must not start')
    assert (tmp_path / RECOVERY).read_bytes() == pending


def test_external_attachment_directory_is_rejected_before_post(project):
    root, client, remote, syncer, args = project
    outside = root.parent / 'external-attachments'
    outside.mkdir(exist_ok=True)
    note = outside / 'private.csv'
    note.write_bytes(b'private')
    syncer.target.attachments_dir = str(outside)
    (root / 'docs/a.md').write_text('note')
    try:
        with pytest.raises(ValueError, match='プロジェクト外'):
            syncer.sync()
        client.create_item.assert_not_called()
        client.upload_file.assert_not_called()
    finally:
        note.unlink()
        outside.rmdir()


def test_concurrent_category_change_after_our_patch_is_not_adopted(project):
    root, client, remote, syncer, args = push_note(project)
    syncer.target.category = 10
    def override_category(entity, eid, **fields):
        remote[eid].update(fields)
        remote[eid]['category'] = 99
    client.patch_entity.side_effect = override_category
    assert syncer.sync() == 0
    assert syncer.failures == 1
    assert remote[1]['category'] == 99
    assert syncer.inspect('a.md', 1)['state'] == '競合'
    assert syncer._pending()


def test_concurrent_tag_change_after_our_add_is_not_adopted(project):
    root, client, remote, syncer, args = push_note(project)
    syncer.target.tags = ['ours']
    def add_then_other_user(entity, eid, tag):
        remote[eid]['tags'] = [tag, 'third-party']
    client.add_tag.side_effect = add_then_other_user
    assert syncer.sync() == 0
    assert syncer.failures == 1
    assert syncer.inspect('a.md', 1)['state'] == '競合'
    assert syncer._pending()


def test_expected_category_and_tag_changes_complete(project):
    root, client, remote, syncer, args = push_note(project)
    syncer.target.category = 10
    syncer.target.tags = ['ours']
    assert syncer.sync() == 1
    assert remote[1]['category'] == 10
    assert remote[1]['tags'] == ['ours']
    assert syncer.inspect('a.md', 1)['state'] == '最新'


def test_force_push_with_unlisted_current_category_succeeds(project):
    # カテゴリ一覧に出ない（権限なし）カテゴリが既に付いている文書でも --force push が通る
    from elab_doc_sync.client import ELabFTWClient
    root, client, remote, syncer, args = push_note(project)
    remote[1].update(category=64, category_title='SPECIFICATION')
    syncer.target.category = 'SPECIFICATION'
    client.list_categories.return_value = [{'id': 65, 'title': 'OTHER'}]
    client.resolve_category_id.side_effect = lambda entity, category, current=None: \
        ELabFTWClient.resolve_category_id(client, entity, category, current=current)
    (root / 'docs/a.md').write_text('changed')
    assert syncer.sync(force=True) == 1
    assert syncer.failures == 0
    assert not syncer._pending()
    assert remote[1]['category'] == 64
    assert not any(c.kwargs.get('category') for c in client.patch_entity.call_args_list)


def test_unresolvable_category_reports_body_updated(project, capsys):
    from elab_doc_sync.client import ELabFTWClient
    root, client, remote, syncer, args = push_note(project)
    syncer.target.category = 'SPECIFICATION'
    client.list_categories.return_value = [{'id': 65, 'title': 'OTHER'}]
    client.resolve_category_id.side_effect = lambda entity, category, current=None: \
        ELabFTWClient.resolve_category_id(client, entity, category, current=current)
    (root / 'docs/a.md').write_text('changed')
    assert syncer.sync(force=True) == 0
    out = capsys.readouterr().out
    assert '本文は更新済み' in out and '数字で指定' in out


def test_category_change_at_final_read_is_not_adopted(project):
    root, client, remote, syncer, args = push_note(project)
    syncer.target.category = 10
    calls_after_patch = 0
    get = client.get_item.side_effect
    def get_with_late_change(eid):
        nonlocal calls_after_patch
        if remote[eid].get('category') == 10:
            calls_after_patch += 1
            if calls_after_patch == 2:
                remote[eid]['category'] = 99
        return get(eid)
    client.get_item.side_effect = get_with_late_change
    assert syncer.sync() == 0
    assert remote[1]['category'] == 99
    assert syncer._pending()


@pytest.mark.parametrize('old_tags', [None, 'a|b', [{'id': 1, 'tag': 'a'}, {'id': 2, 'tag': 'b'}]])
def test_old_state_metadata_is_normalized_without_writing(project, old_tags):
    root, client, remote, syncer, args = push_note(project)
    remote[1]['category'] = 10
    remote[1]['tags'] = [] if old_tags is None else ['a', 'b']
    path = syncer.hash_dir / 'a.md.state.json'
    state = json.loads(path.read_text())
    state['remote']['category'] = '10'
    state['remote']['tags'] = old_tags
    path.write_text(json.dumps(state))
    before = path.read_bytes()
    assert syncer.inspect('a.md', 1)['state'] == '最新'
    assert path.read_bytes() == before
    (root / 'docs/a.md').write_text('local edit')
    assert syncer.inspect('a.md', 1)['state'] == '送信待ち'
    assert syncer.sync() == 1
    assert remote[1]['body'] == 'local edit'


@pytest.mark.parametrize('old_tags', [None, 'a|b'])
def test_old_pending_guard_resumes_without_false_conflict(project, old_tags):
    root, client, remote, syncer, args = push_note(project)
    remote[1]['category'] = 10
    remote[1]['tags'] = [] if old_tags is None else ['a', 'b']
    syncer._save_baseline('a.md', 'original', client.get_item(1), [])
    (root / 'docs/a.md').write_text('local edit')
    update = client.update_item.side_effect
    client.update_item.side_effect = requests.Timeout()
    assert syncer.sync() == 0
    path = syncer.hash_dir / 'pending.json'
    pending = json.loads(path.read_text())
    pending['a.md']['guard']['category'] = '10'
    pending['a.md']['guard']['tags'] = old_tags
    path.write_text(json.dumps(pending))
    client.update_item.side_effect = update
    assert syncer.sync() == 1
    assert client.create_item.call_count == 1
    assert not syncer._pending()


@pytest.mark.parametrize("tags", [None, "", [], [None]])
def test_untagged_article_pull_then_push(project, tags):
    root, client, remote, syncer, args = project
    remote[42] = {"id": 42, "title": "untagged", "body": "remote body", "content_type": 2, "tags": tags}
    # Exercise ID-based dispatch with multiple targets and no tag match.
    cfg = root / '.elab-sync.yaml'
    raw = yaml.safe_load(cfg.read_text())
    raw['targets'].append({'title': 'Other', 'docs_dir': 'other', 'tags': ['other']})
    cfg.write_text(yaml.safe_dump(raw))
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        assert cmd_pull(args(id=[42], entity='items', auto=True)) == 0
    note = root / 'docs/untagged.md'
    assert note.read_text().strip() == 'remote body'
    note.write_text('local edit')
    assert syncer.sync() == 1
    assert remote[42]['body'] == 'local edit'
    assert syncer.inspect('untagged.md', 42)['state'] == '最新'


def test_push_adds_first_tag_when_tags_endpoint_returns_null(project):
    root, client, remote, syncer, args = project
    (root / 'docs/a.md').write_text('body')
    syncer.target.tags = ['first']
    client.get_tags.side_effect = lambda entity, eid: None
    assert syncer.sync() == 1
    client.add_tag.assert_called_once_with('items', 1, 'first')
    assert syncer.inspect('a.md', 1)['state'] == '最新'


# ── v1.0.2: eLabFTW の本文書き換え・変更理由の表示・古い版の添付 ──


def _rewrite_quotes_on_save(remote):
    """eLabFTW が保存時に行頭の > を &gt; にする挙動を模す。"""
    def update(eid, **kw):
        if 'body' in kw:
            kw['body'] = kw['body'].replace('> ', '&gt; ')
        remote[eid].update(kw)
    return update


def test_interrupted_sync_resumes_when_elabftw_rewrote_body(project):
    root, client, remote, syncer, args = push_note(project)
    client.update_item.side_effect = _rewrite_quotes_on_save(remote)
    syncer.target.category = 'SPEC'
    client.resolve_category_id.side_effect = ValueError('カテゴリ「SPEC」が見つかりません')
    (root / 'docs/a.md').write_text('> **注意:** quoted', encoding='utf-8')
    assert syncer.sync() == 0
    assert syncer._pending()['a.md']['stored']['body'] == '&gt; **注意:** quoted'
    client.resolve_category_id.side_effect = lambda entity, category, current=None: 10
    assert syncer.sync() == 1
    assert not syncer._pending()
    assert remote[1]['category'] == 10
    assert syncer.inspect('a.md', 1)['state'] == '最新'


def test_blocked_resume_names_the_changed_fields(project, capsys):
    root, client, remote, syncer, args = push_note(project)
    syncer.target.category = 'SPEC'
    client.resolve_category_id.side_effect = ValueError('not found')
    (root / 'docs/a.md').write_text('changed')
    assert syncer.sync() == 0
    remote[1]['body'] = 'third party'
    remote[1]['tags'] = ['other']
    capsys.readouterr()
    assert syncer.sync() == 0
    out = capsys.readouterr().out
    assert '未完了の同期後にリモート変更があります' in out
    assert '前回の同期記録と異なる項目: 本文, タグ' in out


def test_status_and_diff_show_remote_metadata_changes(project, capsys):
    from elab_doc_sync.cli import cmd_diff
    root, client, remote, syncer, args = push_note(project)
    remote[1]['body'] = 'original\nremote line'
    remote[1]['tags'] = ['added']
    remote[1]['category'] = 7
    client.list_uploads.return_value = [{'id': 5, 'real_name': 'x.png', 'long_name': 'blob5', 'hash': 'h'}]
    capsys.readouterr()
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        cmd_status(args())
        status_out = capsys.readouterr().out
        cmd_diff(args())
        diff_out = capsys.readouterr().out
    assert '取得待ち' in status_out
    assert 'eLabFTW 側の変更: 本文, カテゴリ, タグ, 添付' in status_out
    assert '前回の同期以降の eLabFTW 側の変更' in diff_out
    assert 'カテゴリ: なし → #7' in diff_out
    assert 'タグ: +added' in diff_out
    assert '添付追加: x.png (#5)' in diff_out
    assert '+remote line' in diff_out


def _stateful_uploads(client):
    import hashlib
    uploads = {}
    def upload(entity, eid, path):
        source = Path(path)
        content = source.read_bytes()
        uid = sum(len(v) for v in uploads.values()) + 100
        uploads.setdefault(eid, []).append({'id': uid, 'real_name': source.name, 'long_name': f'blob{uid}', 'storage': '1',
                                            'filesize': len(content), 'hash': hashlib.sha256(content).hexdigest()})
        return {'id': uid, 'url': f'https://example.test/app/download.php?f=blob{uid}&name={source.name}&storage=1'}
    def delete(entity, eid, uid):
        uploads[eid] = [u for u in uploads[eid] if u['id'] != uid]
    client.upload_file.side_effect = upload
    client.delete_upload.side_effect = delete
    client.list_uploads.side_effect = lambda entity, eid: copy.deepcopy(uploads.get(eid, []))
    return uploads


def test_replaced_image_old_version_is_deleted_after_successful_push(project):
    root, client, remote, syncer, args = project
    uploads = _stateful_uploads(client)
    (root / 'docs/picture.png').write_bytes(b'old image')
    (root / 'docs/a.md').write_text('![image](picture.png)')
    assert syncer.sync() == 1
    old_id = uploads[1][0]['id']
    (root / 'docs/picture.png').write_bytes(b'new image, longer')
    assert syncer.sync() == 1
    assert [u['real_name'] for u in uploads[1]] == ['picture.png']
    assert uploads[1][0]['id'] != old_id
    assert f"blob{uploads[1][0]['id']}" in remote[1]['body']
    assert syncer.inspect('a.md', 1)['state'] == '最新'


def test_failed_push_keeps_old_image_version(project):
    root, client, remote, syncer, args = project
    uploads = _stateful_uploads(client)
    (root / 'docs/picture.png').write_bytes(b'old image')
    (root / 'docs/a.md').write_text('![image](picture.png)')
    assert syncer.sync() == 1
    (root / 'docs/picture.png').write_bytes(b'new image, longer')
    syncer.target.category = 'SPEC'
    client.resolve_category_id.side_effect = ValueError('not found')
    assert syncer.sync() == 0
    assert len(uploads[1]) == 2
    client.delete_upload.assert_not_called()


def test_old_version_referenced_by_upload_id_is_kept(project):
    root, client, remote, syncer, args = project
    uploads = _stateful_uploads(client)
    (root / 'docs/picture.png').write_bytes(b'old image')
    (root / 'docs/a.md').write_text('![image](picture.png)')
    assert syncer.sync() == 1
    old_id = uploads[1][0]['id']
    (root / 'docs/picture.png').write_bytes(b'new image, longer')
    (root / 'docs/a.md').write_text(f'![image](picture.png)\n\n[旧版](https://example.test/api/v2/items/1/uploads/{old_id})', encoding='utf-8')
    assert syncer.sync() == 1
    assert old_id in [u['id'] for u in uploads[1]]
    client.delete_upload.assert_not_called()


def test_network_failure_after_deleting_old_version_can_resume(project):
    root, client, remote, syncer, args = project
    uploads = _stateful_uploads(client)
    (root / 'docs/picture.png').write_bytes(b'old image')
    (root / 'docs/a.md').write_text('![image](picture.png)')
    assert syncer.sync() == 1
    (root / 'docs/picture.png').write_bytes(b'new image, longer')
    get = client.get_item.side_effect
    failed = []
    def get_failing_once_after_delete(eid):
        if client.delete_upload.called and not failed:
            failed.append(True)
            raise requests.ConnectionError('lost')
        return get(eid)
    client.get_item.side_effect = get_failing_once_after_delete
    assert syncer.sync() == 0
    assert syncer._pending()['a.md']['deleting']
    assert len(uploads[1]) == 1
    client.get_item.side_effect = get
    assert syncer.sync() == 1
    assert not syncer._pending()
    assert [u['real_name'] for u in uploads[1]] == ['picture.png']
    assert syncer.inspect('a.md', 1)['state'] == '最新'


def test_change_to_pending_deletion_candidate_blocks_resume(project, capsys):
    root, client, remote, syncer, args = project
    uploads = _stateful_uploads(client)
    (root / 'docs/picture.png').write_bytes(b'old image')
    (root / 'docs/a.md').write_text('![image](picture.png)')
    assert syncer.sync() == 1
    (root / 'docs/picture.png').write_bytes(b'new image, longer')
    client.delete_upload.side_effect = requests.ConnectionError('lost')
    get = client.get_item.side_effect
    failed = []
    def get_failing_once_after_delete(eid):
        if client.delete_upload.called and not failed:
            failed.append(True)
            raise requests.ConnectionError('lost')
        return get(eid)
    client.get_item.side_effect = get_failing_once_after_delete
    assert syncer.sync() == 0
    client.get_item.side_effect = get
    candidate = syncer._pending()['a.md']['deleting'][0]
    next(u for u in uploads[1] if u['id'] == candidate)['hash'] = 'changed by someone'
    capsys.readouterr()
    assert syncer.sync() == 0
    out = capsys.readouterr().out
    assert '未完了の同期後にリモート変更があります' in out
    assert '添付' in out


# ── v1.0.3: 別PCでの pull とターゲットをまたぐ文書間リンク ──

def _two_target_project(root):
    """docs/ と reports/ の2ターゲット構成にする。"""
    cfg = root / '.elab-sync.yaml'
    raw = yaml.safe_load(cfg.read_text(encoding='utf-8'))
    raw['targets'].append({'title': 'R', 'docs_dir': 'reports', 'id_file': '.ids/reports/default.id', 'body_format': 'md'})
    cfg.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding='utf-8')
    (root / 'reports').mkdir()
    return cfg


def test_push_resolves_encoded_link_to_other_target(project):
    from elab_doc_sync.cli import cmd_sync
    root, client, remote, syncer, args = project
    _two_target_project(root)
    (root / 'docs/仕様.md').write_text('spec', encoding='utf-8')
    # エディタがファイル名を URL エンコードしたリンク
    (root / 'reports/週報.md').write_text('[仕様](../docs/%E4%BB%95%E6%A7%98.md#intro)', encoding='utf-8')
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        assert cmd_sync(args(prune_attachments=False)) == 0
    spec_id = next(eid for eid, r in remote.items() if r['title'] == '仕様')
    report = next(r for r in remote.values() if r['title'] == '週報')
    assert report['body'] == f'[仕様](https://example.test/database.php?mode=view&id={spec_id}#intro)'


def test_pull_on_another_pc_restores_links_in_any_order(project):
    root, client, remote, syncer, args = project
    _two_target_project(root)
    remote[10] = {'id': 10, 'title': '仕様', 'body': 'spec', 'content_type': 2}
    remote[11] = {'id': 11, 'title': '週報', 'content_type': 2,
                  'body': '[仕様](https://example.test/database.php?mode=view&id=10#intro)'}
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        # リンク元を先に取得すると、リンク先はまだ追跡されていない
        assert cmd_pull(args(id=[11], entity='items', target='R')) == 0
        report = root / 'reports/週報.md'
        assert 'id=10' in report.read_text(encoding='utf-8')
        assert cmd_pull(args(id=[10], entity='items', target='T')) == 0
    assert report.read_text(encoding='utf-8').strip() == '[仕様](../docs/仕様.md#intro)'
    reports = EachDocsSyncer(client, load_config(root / '.elab-sync.yaml').targets[1], root)
    assert reports.inspect('週報.md', 11)['state'] == '最新'
    # 次の push は同じ URL に戻るので、送信不要のまま
    reports.link_syncers = [syncer, reports]
    assert reports.sync() == 0


def test_relink_after_pull_keeps_local_edits(project):
    root, client, remote, syncer, args = project
    _two_target_project(root)
    remote[10] = {'id': 10, 'title': '仕様', 'body': 'spec', 'content_type': 2}
    remote[11] = {'id': 11, 'title': '週報', 'content_type': 2,
                  'body': '[仕様](https://example.test/database.php?mode=view&id=10)'}
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        assert cmd_pull(args(id=[11], entity='items', target='R')) == 0
        report = root / 'reports/週報.md'
        edited = report.read_text(encoding='utf-8') + '追記\n'
        report.write_text(edited, encoding='utf-8')
        assert cmd_pull(args(id=[10], entity='items', target='T')) == 0
    assert report.read_text(encoding='utf-8') == edited


def test_link_targets_skip_mappings_recorded_on_another_server(project):
    root, client, remote, syncer, args = project
    (root / 'docs/a.md').write_text('a', encoding='utf-8')
    syncer._save_mapping({'a.md': 42})
    syncer._save_baseline('a.md', 'a', {'body': 'a'}, [])
    client.base_url = 'https://new.example.test'
    assert syncer.link_targets().path_for('items', 42) is None


def test_relink_backs_up_only_changed_documents(project):
    root, client, remote, syncer, args = project
    _two_target_project(root)
    (root / 'docs/unrelated.md').write_text('x', encoding='utf-8')
    remote[10] = {'id': 10, 'title': '仕様', 'body': 'spec', 'content_type': 2}
    for eid, title in ((11, 'r1'), (12, 'r2')):
        remote[eid] = {'id': eid, 'title': title, 'content_type': 2,
                       'body': '[仕様](https://example.test/database.php?mode=view&id=10)'}
    with patch('elab_doc_sync.cli.ELabFTWClient', return_value=client):
        assert cmd_pull(args(id=[11, 12], entity='items', target='R')) == 0
        before = set((root / BACKUPS).iterdir())
        assert cmd_pull(args(id=[10], entity='items', target='T')) == 0
    new = set((root / BACKUPS).iterdir()) - before
    manifests = [json.loads((d / 'manifest.json').read_text(encoding='utf-8')) for d in new if d.is_dir()]
    relink = [m for m in manifests if m['reason'] == 'pull:文書間リンクの更新']
    assert len(relink) == 1
    roots = {r['path'] for r in relink[0]['roots']}
    assert {'reports/r1.md', 'reports/r2.md'} <= roots
    assert not any(r.startswith('docs') for r in roots)
