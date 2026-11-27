// ワークスペースを開いた状態で、コマンドから差分タブ・push・ステータスバーを確かめる。esync は run.cjs の代用品。
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const vscode = require('vscode');
const { statusBarView, fileDecoration } = require('../status');

async function until(check, message) {
    for (let i = 0; i < 100; i++) {
        if (await check()) return;
        await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.fail(message);
}

function helpers() {
    const doc = state => ({ doc: { state, target: 'Lab', entity_id: 7 } });
    assert.match(statusBarView([doc('送信待ち')]).text, /cloud-upload.*送信待ち$/);
    assert.match(statusBarView([doc('最新'), doc('競合')]).text, /warning.*競合（送信先 2 件）/,
        'show the state that needs attention first');
    assert.equal(statusBarView([]), undefined);
    assert.equal(fileDecoration(['送信待ち']).badge, 'M');
    assert.equal(fileDecoration(['送信待ち', '競合']).badge, '!');
    assert.equal(fileDecoration(['最新']), undefined, 'no badge for documents in sync');
    assert.equal(fileDecoration(['最新', 'リモート削除']).badge, 'D', 'a deleted article is not hidden by another target');
    assert.match(statusBarView([doc('最新'), doc('リモート削除')]).text, /trash.*リモート削除/);
    assert.equal(fileDecoration(['最新', '新しい状態']).badge, '?', 'an unknown state comes before 最新');
    const failed = statusBarView([doc('最新')], ['Lab — HTTP 401']);
    assert.match(failed.text, /error.*取得できません（前回: 最新）/, 'do not present a stale state as current');
    assert.match(failed.tooltip, /HTTP 401[\s\S]*前回取得した状態/);
    assert.match(statusBarView([], ['Lab — HTTP 401']).text, /取得できません$/);
}

exports.run = async function () {
    helpers();
    const root = process.env.ESYNC_FIXTURE;
    if (!root) return console.log('PASS: status bar and badge helpers (no workspace fixture)');
    const calls = async () => (await fs.readFile(path.join(root, 'bin/calls.log'), 'utf8').catch(() => '')).trim().split('\n');
    const api = await vscode.extensions.getExtension('elab-doc-sync.esync').activate();
    const note = vscode.Uri.file(path.join(root, 'p1/docs/note.md'));
    await vscode.window.showTextDocument(note);
    await until(() => api.statusBar.text.includes('送信待ち'), 'status bar shows the state of the open document');
    // ステータスバーから、表示した送信先の差分を開く。
    const { command, arguments: args } = api.statusBar.command;
    assert.equal(command, 'esync.previewFromStatusBar');
    assert.equal(args[0].matches[0].folder.name, 'p1');
    await vscode.commands.executeCommand(command, ...args);
    const tab = vscode.window.tabGroups.activeTabGroup.activeTab;
    assert.ok(tab.input instanceof vscode.TabInputTextDiff, 'open a side-by-side diff');
    assert.equal(tab.input.original.scheme, 'esync-snapshot');
    assert.equal(tab.input.modified.scheme, 'esync-preview');
    assert.match(tab.label, /前回の同期 ↔ 送信する内容（Lab #42）/);
    assert.equal((await vscode.workspace.openTextDocument(tab.input.original)).getText(), '# old');
    const modified = await vscode.workspace.openTextDocument(tab.input.modified);
    assert.equal(modified.getText(), '# new');
    assert.equal(modified.languageId, 'markdown', 'highlight the reviewed text as Markdown');
    assert.ok((await calls()).includes('diff --json --bodies -- ' + note.fsPath));

    const preview = tab.input.modified.toString();
    await vscode.commands.executeCommand('esync.showRemoteChanges', preview);
    const remote = /** @type {vscode.TabInputTextDiff} */ (vscode.window.tabGroups.activeTabGroup.activeTab.input);
    assert.equal((await vscode.workspace.openTextDocument(remote.modified)).getText(), '# remote');

    await vscode.commands.executeCommand('esync.push', tab.input.original);
    assert.ok((await calls()).includes('push --expect-preview token --target=Lab -- ' + note.fsPath),
        'push from either side of the diff to the reviewed target');

    // 2つの同期プロジェクトがあり、ワークスペース外の文書ではフォルダーを選ぶ。進捗のキャンセルで選択画面を閉じる。
    const before = (await calls()).length;
    const source = new vscode.CancellationTokenSource();
    const pending = api.preview(vscode.Uri.file(path.join(root, 'outside/out.md')), undefined, source.token);
    setTimeout(() => source.cancel(), 300);
    assert.equal(await pending, undefined);
    assert.equal((await calls()).length, before, 'do not run esync diff after cancelling the folder picker');
    console.log('PASS: side-by-side diff, remote changes, push, status bar, folder picker cancel');
};
