"""Opt-in v1 roundtrip against a disposable entity on the selected server.

ELABFTW_TEST_CONFIG=/path/to/test-config.yaml uv run pytest tests/test_integration_v1.py -v
Creates one item per test and always registers cleanup before updating it.
"""
import os
from pathlib import Path

import pytest
import yaml

from elab_doc_sync.client import ELabFTWClient
from elab_doc_sync.cli import _pull_each_entity
from elab_doc_sync.config import TargetConfig
from elab_doc_sync.safety import BACKUPS, restore
from elab_doc_sync.sync import EachDocsSyncer

CONFIG_PATH = os.environ.get('ELABFTW_TEST_CONFIG')
pytestmark = [pytest.mark.integration, pytest.mark.skipif(not CONFIG_PATH, reason='ELABFTW_TEST_CONFIG not set')]


@pytest.fixture
def server(request):
    raw = yaml.safe_load(Path(CONFIG_PATH).read_text(encoding='utf-8'))
    connection = raw.get('elabftw') or raw['profiles']['default']
    client = ELabFTWClient(connection['url'], connection['api_key'], connection.get('verify_ssl', True))
    response = client._req('POST', '/api/v2/items')
    eid = client._parse_id(response)
    request.addfinalizer(lambda: client.delete_item(eid))
    client.update_item(eid, title='[test] elab-doc-sync v1', body='', content_type=2)
    return client, eid


@pytest.mark.parametrize('body_format', ['md', 'html'])
def test_real_roundtrip_conflict_and_restore(server, tmp_path, body_format):
    client, eid = server
    docs = tmp_path / 'docs'
    docs.mkdir()
    filename = '[test] elab-doc-sync v1.md'
    note = docs / filename
    body = '# Test\n\nA **bold** note with $x_1 < y_2$.'
    note.write_text(body, encoding='utf-8')
    target = TargetConfig(title='T', docs_dir='docs', id_file='.ids/default.id', body_format=body_format)
    syncer = EachDocsSyncer(client, target, tmp_path)
    syncer._save_mapping({filename: eid})
    assert syncer.sync(force=True) == 1
    assert syncer.inspect(filename, eid)['state'] == '最新'
    assert syncer.sync() == 0
    remote = client.get_item(eid)
    assert int(remote['content_type']) == (2 if body_format == 'md' else 1)
    remote_body = body + '\n\nRemote edit' if body_format == 'md' else remote['body'] + '<p>Remote edit</p>'
    client.update_item(eid, body=remote_body)
    assert syncer.inspect(filename, eid)['state'] == '取得待ち'
    mapping = syncer._load_mapping()
    assert _pull_each_entity(client, syncer, target, tmp_path, docs, mapping, {eid: filename}, eid,
                             client.get_item(eid), 'items', False, False) == 1
    assert 'Remote edit' in note.read_text(encoding='utf-8')
    assert syncer.inspect(filename, eid)['state'] == '最新'
    note.write_text('unsent local edit', encoding='utf-8')
    client.update_item(eid, body=remote_body + '\nAnother edit')
    assert syncer.inspect(filename, eid)['state'] == '競合'
    assert syncer.sync() == 0
    assert syncer.failures == 1
    before = {p.parent.name for p in (tmp_path / BACKUPS).glob('*/manifest.json')}
    assert _pull_each_entity(client, syncer, target, tmp_path, docs, mapping, {eid: filename}, eid,
                             client.get_item(eid), 'items', True, False) == 1
    backup_id = ({p.parent.name for p in (tmp_path / BACKUPS).glob('*/manifest.json')} - before).pop()
    restore(tmp_path, backup_id)
    assert note.read_text(encoding='utf-8') == 'unsent local edit'
