const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const vscode = require('vscode');
const { articleGroups, articleUri, articleActions } = require('../articles');

exports.run = async function () {
    const doc = { entity: 'items', entity_id: 42, target: 'Lab', selector: 'docs',
        url: 'https://example.test/lab/database.php?mode=view&id=42' };
    const folder = { uri: vscode.Uri.file('/tmp'), name: 'project', index: 0 };
    const [tags, links, metadata] = articleGroups(folder, doc);
    const calls = [];
    let refreshed = false;
    let confirmed = false;
    const run = async (project, args, options) => {
        assert.equal(project, folder);
        calls.push({ args, options });
        const data = args.includes('remove') ? {} : args[0] === 'relate' ?
            { sources: [{ links: { items: [{ id: 7, title: '材料' }], experiments: [] } }] } :
            { entities: [{ tags: ['-第1回'], metadata: { 担当: 'A' }, value_tokens: { 担当: 'previous-token' } }] };
        return { code: 0, stdout: JSON.stringify(data) };
    };
    const actions = articleActions(run, () => [folder], () => { refreshed = true; }, {}, { confirm: () => confirmed });
    assert.equal(articleUri(doc).query, 'mode=view&id=42');
    assert.throws(() => articleUri({ url: 'file:///tmp/file' }));
    assert.throws(() => articleUri({ url: 'https://user:pass@example.test' }));
    const [tag] = await actions.children(tags);
    assert.equal(tag.label, '-第1回');
    assert.equal((await actions.children(links))[0].description, '材料');
    const [metadataRow] = await actions.children(metadata);
    assert.equal(metadataRow.label, '担当');
    await actions.edit(tag, true);
    assert.equal(calls.length, 3);
    confirmed = true;
    await actions.edit(tag, true);
    assert.deepEqual(calls[3], { args: ['tag', '--json', '--target=docs', '--expect-article-url=' + doc.url,
        'remove', '--id=42', '--entity=items', '--', '-第1回'], options: { timeout: 0, input: undefined } });
    assert.ok(refreshed);
    const root = await fs.mkdtemp(path.join(os.tmpdir(), 'esync-new-'));
    const previousPick = vscode.window.showQuickPick;
    const previousInput = vscode.window.showInputBox;
    try {
        vscode.window.showInputBox = async () => 'B';
        await actions.edit(metadataRow);
        assert.deepEqual(JSON.parse(calls[4].options.input), { key: '担当', value: 'B', previous_token: 'previous-token' });
        assert.ok(calls[4].args.includes('--edit-stdin'));
        assert.ok(!calls[4].args.includes('担当=B'));
        const project = { ...folder, uri: vscode.Uri.file(root) };
        const history = [];
        const requests = [];
        const filename = 'notes/example.md';
        const cli = async (_, args) => {
            requests.push(args);
            if (args[0] === 'log') return { code: 0, stdout: '同期履歴' };
            let data;
            if (args.includes('--list-targets')) data = { targets: [{ target: 'Lab', docs_dir: 'notes', selector: 'notes' }] };
            else if (args.includes('--list')) data = { templates: [{ title: '日報', id: 7 }] };
            else {
                await fs.mkdir(path.join(root, 'notes'));
                await fs.writeFile(path.join(root, filename), '# 日報');
                data = { path: filename };
            }
            return { code: 0, stdout: JSON.stringify(data) };
        };
        const templateActions = articleActions(cli, () => [project], () => {}, {
            appendLine: line => history.push(line), show: () => {} }, {});
        vscode.window.showQuickPick = async choices => (await choices)[0];
        vscode.window.showInputBox = async () => '実験記録';
        await templateActions.newDocument();
        assert.deepEqual(requests[2], ['new', '--json', '--target=notes', '--template-id=7', '--title=実験記録']);
        assert.equal(vscode.window.activeTextEditor.document.uri.fsPath, path.join(root, filename));
        await templateActions.log();
        assert.match(history[0], /project.*\n同期履歴/);
    } finally {
        vscode.window.showQuickPick = previousPick;
        vscode.window.showInputBox = previousInput;
        await fs.rm(root, { recursive: true, force: true });
    }
    console.log('PASS: article URLs, tag/link/metadata rows, confirmed single-article edit');
};
