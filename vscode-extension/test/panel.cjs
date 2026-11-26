// VS Code Extension Host test (--extensionTestsPath). No eLabFTW connection is needed.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const vscode = require('vscode');
const { StatusProvider, CurrentDocumentProvider } = require('../status');

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
        const current = new CurrentDocumentProvider(status, () => ({ file }), currentEvents, async () => ({
            documents: [{ ...doc, entity_id: 17, renamed_from: 'old.md', state: 'リネーム予定' }],
        }));
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
        respond(requests[0], [doc, { ...doc, file: 'old.md', path: null, entity_id: 17 }]);
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
        console.log('PASS: symlink, partial refresh, coalesced saves, rename ID, row actions');
        const completed = waitForUpdate();
        for (const request of requests.slice(1)) respond(request, []);
        await completed;
    } finally {
        events.dispose();
        currentEvents.dispose();
        await fs.rm(root, { recursive: true, force: true });
    }
};
