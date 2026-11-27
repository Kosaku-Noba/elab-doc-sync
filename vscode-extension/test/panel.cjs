// VS Code Extension Host test (--extensionTestsPath). No eLabFTW connection is needed.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const vscode = require('vscode');
const { StatusProvider, CurrentDocumentProvider, statusBarView } = require('../status');

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

    const refreshWith = async documents => {
        status.invalidate();
        await current.getChildren();
        const updated = waitForUpdate();
        respond(documents);
        await updated;
    };
    const finishLookup = async (index, result) => {
        const updated = waitForUpdate();
        lookups[index](result);
        await updated;
    };

    await current.getChildren();
    const first = waitForUpdate();
    respond([doc, candidate(17)]);
    await first;
    assert.equal(await idOf(), '確認中…');
    // 初回の照会中に候補が #17 から #42 に変わると、その照会結果は表示しない。
    await refreshWith([doc, candidate(42)]);
    assert.equal(await idOf(), '確認中…');
    assert.equal(lookups.length, 1, 'do not start a second lookup while the stale one is in flight');
    await finishLookup(0, renamed(17));
    assert.equal(await idOf(), '確認中…', 'ignore a lookup started before the candidates changed');
    assert.equal(lookups.length, 2, 'look up again only after the stale request finishes');
    await finishLookup(1, renamed(42));
    assert.equal(await idOf(), '#42');
    // ステータスバーとバッジも、照会済みの結果で改名先の記事を示す（新たに照会はしない）。
    assert.deepEqual(status.statesOf(file), ['リネーム予定']);
    assert.equal((await status.documentsFor(file, undefined)).matches[0].doc.entity_id, 42);
    assert.equal(lookups.length, 2);
    // 保存などで同期状態を取り直したら、再照会が終わるまで改名先の記事を示さない。
    status.invalidate();
    const refreshing = await status.documentsFor(file, undefined);
    assert.deepEqual(refreshing.errors, [], 'a refresh in progress is not a fetch failure');
    assert.ok(refreshing.matches.every(match => match.stale), 'results being refreshed are marked as previous');
    assert.match(statusBarView(refreshing.matches, refreshing.errors).text, /（更新中）$/);
    let refreshed = waitForUpdate();
    respond([doc, candidate(42)]);
    await refreshed;
    assert.deepEqual(status.statesOf(file), ['未追跡'], 'do not reuse a lookup that needs re-checking');
    assert.equal((await status.documentsFor(file, undefined)).matches[0].doc.entity_id, null);
    assert.equal(lookups.length, 2, 'the status bar and badges do not start lookups');
    await idOf();
    await finishLookup(2, renamed(42));
    assert.deepEqual(status.statesOf(file), ['リネーム予定']);

    await refreshWith([doc, candidate(42)]);
    assert.equal(await idOf(), '#42', 'keep the confirmed ID while the same candidates are re-checked');
    await finishLookup(3, renamed(42));
    // 候補が増えると改名先が曖昧になりうるので、確認済みの ID も表示しない。
    await refreshWith([doc, candidate(42), candidate(17)]);
    assert.equal(await idOf(), '確認中…', 'drop the ID when another candidate appears');
    await finishLookup(4, renamed(42, { state: undefined, error: 'HTTP 403' }));
    const rows = await current.getChildren();
    assert.equal(rows.find(r => r.label === '記事 ID').description, '#42', 'show the ID even if fetching it failed');
    assert.ok(rows.find(r => r.label === 'HTTP 403'), 'keep the fetch error in its own row');
    assert.equal(rows.find(r => r.label === '同期状態（保存時点）').description, '未追跡');

    // 照会中に最後の候補が消えると、照会の完了を待たずに「未割り当て」を表示する。
    await refreshWith([doc, candidate(42)]);
    assert.equal(await idOf(), '確認中…', 'the candidates shrank from #17 and #42 to #42');
    assert.equal(lookups.length, 6);
    await refreshWith([doc]);
    assert.equal(await idOf(), '未割り当て', 'show 未割り当て as soon as the last rename candidate is gone');
    await finishLookup(5, renamed(42));
    assert.equal(await idOf(), '未割り当て', 'ignore the lookup started while a candidate existed');
    assert.equal(lookups.length, 6, 'do not look up a document without rename candidates');
    console.log('PASS: replaced and added rename candidates, stale first lookup, ID with fetch error');
}

// 取り直しの間は「取得中」として扱い、前回の失敗や前回の一覧だけで判断しない。
async function refreshStates(folder, file, doc, waitForUpdate, events, currentEvents) {
    const statuses = [];
    const status = new StatusProvider(() => [folder], () => new Promise(resolve => statuses.push(resolve)),
        events, currentEvents);
    const reply = async result => {
        const updated = waitForUpdate();
        statuses.at(-1)(result);
        await updated;
    };
    const ok = documents => ({ code: 0, stderr: '', stdout: JSON.stringify({ documents, recovery_pending: false }) });
    await status.documentsFor(file, undefined);
    await reply(ok([{ ...doc, file: 'other.md', path: 'other.md' }]));
    let found = await status.documentsFor(file, undefined);
    assert.equal(found.waiting, false);
    assert.equal(found.matches.length, 0, 'the file is not in the first list');
    status.invalidate();
    found = await status.documentsFor(file, undefined);
    assert.equal(found.waiting, true, 'a file missing from the previous list may appear after the refresh');

    // CLI は記事の取得に失敗すると、終了コード 1 と文書ごとの error を返す。取り直し中は前回のものと示す。
    await reply({ ...ok([{ ...doc, state: '確認失敗', error: 'HTTP 401' }]), code: 1 });
    const current = new CurrentDocumentProvider(status, () => ({ file }), currentEvents, async () => ({ documents: [] }));
    status.invalidate();
    let rows = await current.getChildren();
    assert.ok(rows.find(r => r.label === '同期状態を取得中…'), 'show that the state is being fetched again');
    assert.equal(rows.find(r => r.label === '同期状態（保存時点）').description, '確認失敗（前回取得）');
    assert.ok(rows.find(r => r.label === 'HTTP 401（前回取得）'), 'a cached document error is marked as previous');
    await reply(ok([{ ...doc, state: '確認失敗', error: 'HTTP 401' }]));
    rows = await current.getChildren();
    assert.equal(rows.find(r => r.label === '同期状態（保存時点）').description, '確認失敗');
    assert.ok(!rows.find(r => r.label === '同期状態を取得中…'));

    status.invalidate();
    await status.documentsFor(file, undefined);
    await reply({ code: 2, stdout: '', stderr: 'HTTP 401' });
    found = await status.documentsFor(file, undefined);
    assert.deepEqual(found.errors, ['Project — HTTP 401']);
    status.invalidate();
    found = await status.documentsFor(file, undefined);
    assert.deepEqual(found.errors, [], 'a retry in progress does not repeat the previous failure');
    assert.equal(found.waiting, true);
    await reply({ code: 2, stdout: '', stderr: 'HTTP 401' });
    assert.deepEqual((await status.documentsFor(file, undefined)).errors, ['Project — HTTP 401'],
        'report the failure again once the retry fails');
    console.log('PASS: refresh of a new file, previous document errors, retry after a failure');
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
        /** @type {(error: Error) => void} */
        let rejectLookup = () => {};
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
        // 保存による取り直しがまだ終わっていないので、状態は前回取得したものとして示す。
        assert.equal(updated.find(r => r.label === '同期状態（保存時点）').description, 'リネーム予定（前回取得）');
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
        await refreshStates(folder, file, doc, waitForUpdate, events, currentEvents);
    } finally {
        events.dispose();
        currentEvents.dispose();
        await fs.rm(root, { recursive: true, force: true });
    }
};
