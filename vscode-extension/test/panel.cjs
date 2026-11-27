// VS Code Extension Host test (--extensionTestsPath). No eLabFTW connection is needed.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const vscode = require('vscode');
const { StatusProvider, CurrentDocumentProvider } = require('../status');

// 改名元の候補が変わったら古い ID を捨て、取得エラーがあっても判明した ID は表示する。
async function renameCandidates(folder, file, doc, waitForUpdate, events, currentEvents) {
    const statuses = [];
    const lookups = [];
    const status = new StatusProvider(() => [folder], () => new Promise(resolve => statuses.push(resolve)),
        events, currentEvents);
    const current = new CurrentDocumentProvider(status, () => ({ file }), currentEvents,
        () => new Promise(resolve => lookups.push(resolve)));
    const respond = (documents) => statuses.at(-1)({ code: 0, stderr: '',
        stdout: JSON.stringify({ documents, recovery_pending: false }) });
    const candidate = id => ({ ...doc, file: 'old' + id + '.md', path: null, entity_id: id });
    const renamed = (id, extra) => ({ documents: [{ ...doc, entity_id: id, renamed_from: 'old' + id + '.md',
        state: 'リネーム予定', ...extra }] });
    const idOf = async () => (await current.getChildren()).find(r => r.label === '記事 ID').description;

    await current.getChildren();
    let updated = waitForUpdate();
    respond([doc, candidate(17)]);
    await updated;
    assert.equal(await idOf(), '確認中…');
    updated = waitForUpdate();
    lookups[0](renamed(17));
    await updated;
    assert.equal(await idOf(), '#17');

    // 再照会中に候補が #17 から #42 に変わると、#17 の照会結果は表示しない。
    status.invalidate();
    await current.getChildren();
    updated = waitForUpdate();
    respond([doc, candidate(17)]);
    await updated;
    assert.equal(await idOf(), '#17', 'keep the confirmed ID while the same candidate is re-checked');
    assert.equal(lookups.length, 2);
    status.invalidate();
    await current.getChildren();
    updated = waitForUpdate();
    respond([doc, candidate(42)]);
    await updated;
    assert.equal(await idOf(), '確認中…', 'drop an ID whose rename source left the candidates');
    updated = waitForUpdate();
    lookups[1](renamed(17));
    await updated;
    assert.equal(await idOf(), '確認中…', 'ignore a lookup started before the candidates changed');
    assert.equal(lookups.length, 3, 'look up again after the stale request finishes');
    updated = waitForUpdate();
    lookups[2](renamed(42, { state: undefined, error: 'HTTP 403' }));
    await updated;
    const rows = await current.getChildren();
    assert.equal(rows.find(r => r.label === '記事 ID').description, '#42', 'show the ID even if fetching it failed');
    assert.ok(rows.find(r => r.label === 'HTTP 403'), 'keep the fetch error in its own row');
    assert.equal(rows.find(r => r.label === '同期状態（保存時点）').description, '未追跡');
    console.log('PASS: changed rename candidates, stale lookup, ID with fetch error');
}

exports.run = async function () {
    const root = await fs.mkdtemp(path.join(os.tmpdir(), 'esync-panel-'));
    const events = new vscode.EventEmitter();
    const currentEvents = new vscode.EventEmitter();
    try {
        const project = path.join(root, 'project');
        const alias = path.join(root, 'alias');
        await fs.mkdir(project);
        await fs.symlink(project, alias, 'junction');
        await fs.writeFile(path.join(project, 'new.md'), 'text');
        const folder = { name: 'Project', uri: vscode.Uri.file(alias) };
        const other = { name: 'Other', uri: vscode.Uri.file(root) };
        const file = vscode.Uri.file(path.join(alias, 'new.md'));
        const requests = [];
        const status = new StatusProvider(() => [folder, other], (projectFolder, args) => {
            assert.deepEqual(args, ['status', '--json']);
            return new Promise(resolve => requests.push({ projectFolder, resolve }));
        }, events, currentEvents);
        const doc = { file: 'new.md', path: 'new.md', entity: 'items', entity_id: null, target: 'Lab',
            state: '未追跡', remote_changes: [], next_actions: [] };
        let lookups = 0;
        let rejectLookup;
        const current = new CurrentDocumentProvider(status, () => ({ file }), currentEvents, async () => {
            if (++lookups === 1) return { documents: [{ ...doc, entity_id: 17, renamed_from: 'old.md', state: 'リネーム予定' }] };
            return new Promise((resolve, reject) => { rejectLookup = reject; });
        });
        const waitForUpdate = () => new Promise(resolve => {
            const sub = currentEvents.event(() => { sub.dispose(); resolve(); });
        });
        await current.getChildren();
        assert.equal(requests.length, 2);
        status.invalidate();
        status.invalidate();
        const published = waitForUpdate();
        const respond = (request, documents) => request.resolve({ code: 0, stderr: '',
            stdout: JSON.stringify({ documents, recovery_pending: false }) });
        const renamed = [doc, { ...doc, file: 'old.md', path: null, entity_id: 17 }];
        respond(requests[0], renamed);
        await published;
        const rows = await current.getChildren();
        assert.ok(rows.find(r => r.label === '差分を確認'), 'show the ready project while other requests are pending');
        assert.equal(requests.filter(r => r.projectFolder === folder).length, 2, 'coalesce saves into one follow-up');
        const updated = await current.getChildren();
        assert.equal(updated.find(r => r.label === '記事 ID').description, '#17');
        assert.equal(updated.find(r => r.label === '同期状態（保存時点）').description, 'リネーム予定');
        assert.equal(updated.find(r => r.label === '差分を確認').command.arguments[0].folder, folder);
        const group = (await status.getChildren({ projectRoot: folder })).find(r => r.label === '未追跡');
        assert.equal(group.children[0].contextValue, 'esync.document');
        assert.equal(group.children[1].command, undefined);
        const refresh = waitForUpdate();
        respond(requests[2], renamed);
        await refresh;
        const previous = await current.getChildren();
        assert.equal(previous.find(r => r.label === '記事 ID').description, '#17');
        status.invalidate();
        await current.getChildren();
        const refreshedAgain = waitForUpdate();
        respond(requests[3], renamed);
        await refreshedAgain;
        await current.getChildren();
        assert.equal(lookups, 2, 'keep one detail lookup in flight for each file');
        const lookupFailed = waitForUpdate();
        rejectLookup(new Error('照会に失敗'));
        await lookupFailed;
        assert.equal((await current.getChildren()).find(r => r.label === '記事 ID').description, '確認できません');
        console.log('PASS: symlink, partial refresh, coalesced saves, rename ID, failed lookup, row actions');
        const completed = waitForUpdate();
        for (const request of requests.slice(1)) respond(request, []);
        await completed;
        await renameCandidates(folder, file, doc, waitForUpdate, events, currentEvents);
    } finally {
        events.dispose();
        currentEvents.dispose();
        await fs.rm(root, { recursive: true, force: true });
    }
};
