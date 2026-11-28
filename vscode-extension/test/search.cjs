const assert = require('node:assert/strict');
const vscode = require('vscode');
const { articleActions, openBeside } = require('../articles');

exports.run = async function () {
    const folder = { name: '実験室', index: 0, uri: vscode.Uri.file('/tmp/project') };
    const items = { entity: 'items', id: 17, title: '手順書', modified_at: '2026-11-01', url: 'https://example.test/database.php?mode=view&id=17' };
    const experiment = { ...items, entity: 'experiments', url: 'https://example.test/experiments.php?mode=view&id=17' };
    const pages = [{ results: [items, experiment], next_offset: 20 }, { results: [experiment], next_offset: null }];
    const calls = [], opened = [], messages = [];
    let targets = [{ profile: 'Lab', selector: 'a' }, { profile: 'Lab', selector: 'b' }];
    let fail = false;
    const actions = articleActions(async (_, args) => {
        calls.push(args);
        if (args.includes('--list-targets')) return { code: 0, stdout: JSON.stringify({ targets }) };
        if (fail) return { code: 1, stderr: '接続に失敗' };
        return { code: 0, stdout: JSON.stringify(pages.shift()) };
    }, () => [folder], () => {}, {}, {});
    const w = vscode.window, c = vscode.commands;
    const [input, pick, info, get, execute] = [w.showInputBox, w.showQuickPick, w.showInformationMessage, c.getCommands, c.executeCommand];
    const openExternal = vscode.env.openExternal;
    try {
        c.getCommands = async () => ['workbench.action.browser.open'];
        c.executeCommand = async (...args) => { opened.push(args); return undefined; };
        w.showInformationMessage = async (...args) => { messages.push(args); return undefined; };
        w.showInputBox = async () => '';
        let count = 0;
        w.showQuickPick = async choices => {
            const rows = await choices;
            if (typeof rows[0] === 'string') return rows[0];
            if (++count === 1) {
                assert.deepEqual(rows.map(r => r.description), ['リソース #17', '実験ノート #17', undefined]);
                assert.match(rows[1].detail, /2026-11-01/);
                return rows[2];
            }
            assert.equal(rows.length, 1);
            return rows[0];
        };
        await actions.search();
        assert.ok(calls[1].includes('--target=a'));
        assert.deepEqual(calls[1].slice(-3), ['--offset', '0', '--']);
        assert.deepEqual(calls[2].slice(-3), ['--offset', '20', '--']);
        assert.deepEqual(opened, [['workbench.action.browser.open', { url: experiment.url, openToSide: true }]]);
        targets = [...targets, { profile: '別の接続先', selector: 'other' }];
        w.showQuickPick = async choices => (await choices)[1];
        w.showInputBox = async () => '-操作';
        pages.push({ results: [], next_offset: null });
        await actions.search();
        assert.ok(calls.at(-1).includes('--target=other'));
        assert.deepEqual(calls.at(-1).slice(-2), ['--', '-操作']);
        assert.match(messages[0][0], /該当する記事はありません/);
        fail = true;
        await assert.rejects(actions.search(), /接続に失敗/);
        w.showInputBox = async () => undefined;
        await actions.search();
        assert.ok(calls.at(-1).includes('--list-targets'));
        w.showQuickPick = async () => undefined;
        w.showInputBox = async () => assert.fail('接続先の選択でキャンセル済み');
        await actions.search();
        targets = [];
        fail = false;
        w.showInputBox = async () => '資料';
        pages.push({ results: [items], next_offset: null });
        await actions.search();
        assert.equal(opened.length, 1, '結果一覧のキャンセルで記事を開かない');
        const tracked = { ...items, local_path: __filename };
        pages.push({ results: [tracked], next_offset: null });
        w.showQuickPick = async choices => {
            const rows = await choices;
            return typeof rows[0] === 'string' ? rows[1] : rows[0];
        };
        await actions.search();
        assert.equal(vscode.window.activeTextEditor.document.uri.fsPath, __filename);
        assert.equal(calls.at(-1)[0], 'search', 'existing local article is opened without pulling');
        c.getCommands = async () => [];
        await openBeside(items);
        assert.match(messages.at(-1)[1], /外部ブラウザ/);
        const externalUrls = [];
        vscode.env.openExternal = async uri => { externalUrls.push(uri.toString(true)); return true; };
        c.getCommands = async () => ['workbench.action.browser.open'];
        c.executeCommand = async () => { throw new Error('表示できません'); };
        w.showInformationMessage = async () => '外部ブラウザで開く';
        await openBeside(items);
        assert.deepEqual(externalUrls, [items.url]);
        assert.equal(opened.length, 1);
    } finally {
        vscode.env.openExternal = openExternal;
        [w.showInputBox, w.showQuickPick, w.showInformationMessage, c.getCommands, c.executeCommand] = [input, pick, info, get, execute];
    }
    console.log('PASS: article search, profiles, pagination, entity URLs, cancellation and browser fallback');
};
