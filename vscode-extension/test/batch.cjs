const assert = require('node:assert/strict');
const vscode = require('vscode');
const { batchSync } = require('../batch');

exports.run = async function () {
    const folder = { uri: vscode.Uri.file('/tmp/batch-example') };
    const base = { selector: 'notes', target: 'Lab', entity: 'items', server: 'https://lab.test' };
    const documents = ['送信待ち', '取得待ち', '競合'].map((state, i) => ({ ...base, state, entity_id: i + 1,
        path: 'notes/' + i + '.md', preview_token: 'token-' + i }));
    const writes = [], counts = [], history = [];
    let approve = true, changed = false, recovery = false, reads = 0, refreshes = 0;
    const run = async (_, args) => {
        let result;
        if (args[0] === 'status') return { code: 1, stdout: JSON.stringify({ documents, recovery_pending: recovery }), stderr: '' };
        else if (args.includes('--dry-run')) result = { documents: [{ entity_id: 2, result: 'would_pull', path: 'notes/1.md' }] };
        else {
            writes.push(args);
            result = { documents: [{ result: 'pulled' }] };
        }
        return { code: 0, stdout: JSON.stringify(result), stderr: '' };
    };
    const load = async (_, file) => {
        const doc = documents.find(d => file.fsPath.endsWith(d.path));
        return { documents: [changed && ++reads === 4 ? { ...doc, state: '競合' } : doc] };
    };
    const perform = () => batchSync(folder, run, load, msg => { counts.push(msg); return approve; },
        () => refreshes++, { appendLine: s => history.push(s) });
    const old = vscode.window.showQuickPick;
    try {
        vscode.window.showQuickPick = async choices => {
            const rows = await choices;
            assert.equal(rows.length, 2);
            return rows;
        };
        approve = false;
        await perform();
        assert.equal(writes.length, 0);
        approve = true;
        await perform();
        assert.match(counts[1], /送信 1 件・取得 1 件/);
        assert.ok(writes[0].includes('--target=notes') && writes[0].includes('--expect-preview'));
        assert.ok(writes[1].includes('--incoming-only') && writes[1].includes('--expect-path=notes/1.md'));
        changed = true;
        await assert.rejects(perform(), /1\/2 件完了.*取得.*停止/);
        assert.equal(writes.length, 3);
        assert.equal(refreshes, 2);
        recovery = true;
        await assert.rejects(perform(), /復旧待ち/);
        assert.equal(writes.length, 3);
    } finally {
        vscode.window.showQuickPick = old;
    }
    console.log('PASS: mixed batch sync, cancellation, conflict exclusion and partial completion');
};
