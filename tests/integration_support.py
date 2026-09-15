"""Explicit connection selection and disposable-entity audit for integration tests."""
import json
import os
from pathlib import Path

import yaml
from elab_doc_sync.config import _read_yaml_text


def connection_settings():
    path = os.environ.get('ELABFTW_TEST_CONFIG')
    if path:
        raw = yaml.safe_load(_read_yaml_text(Path(path)))
        connection = raw.get('elabftw') or raw['profiles']['default']
        return connection['url'], connection['api_key'], connection.get('verify_ssl', True)
    return 'https://demo.elabftw.net', os.environ.get('ELABFTW_DEMO_API_KEY', ''), True


def record_entity(event, entity_id):
    path = os.environ.get('ELABFTW_TEST_JOURNAL')
    if path:
        with Path(path).open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'event': event, 'entity': 'items', 'id': entity_id}) + '\n')


def delete_test_entity(client, entity_id):
    client.delete_item(entity_id)
    # Verify actual deletion, including servers that retain a soft-deleted row.
    from requests import HTTPError
    try:
        client.get_item(entity_id)
    except HTTPError as error:
        if error.response is None or error.response.status_code != 404:
            raise
    else:
        raise AssertionError(f"Test item {entity_id} remains active after DELETE")
    record_entity('deleted', entity_id)
