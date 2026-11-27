// 「開いている文書」の記事操作。展開したグループだけを eLabFTW に問い合わせる。
const vscode = require('vscode');
const path = require('node:path');

const groups = { tag: 'タグ', relate: '関連リンク', metadata: 'メタデータ' };
const kindName = type => type === 'experiments' ? '実験ノート' : 'リソース';

function articleGroups(folder, doc) {
    return Object.entries(groups).map(([kind, label]) => Object.assign(
        new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.Collapsed),
        { kind, folder, doc, contextValue: 'esync.group.' + kind }));
}

function articleUri(doc) {
    const url = new URL(doc.url);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) {
        throw new Error('記事 URL を確認してください。');
    }
    return vscode.Uri.parse(url.href);
}

/** @param {() => vscode.WorkspaceFolder[]} projects */
function articleActions(run, projects, refresh, output, dialogs) {
    async function json(folder, args, writing = false, input = undefined) {
        const result = await run(folder, args, writing ? { timeout: 0, input } : {});
        if (result.code !== 0) throw new Error(result.stderr.trim() || 'esync の操作に失敗しました。');
        return JSON.parse(result.stdout);
    }
    async function article(row, action, options = [], writing = false, input = undefined) {
        const { doc, folder, kind } = row;
        if (!doc.selector || !Number.isSafeInteger(doc.entity_id) || doc.entity_id <= 0) {
            throw new Error('記事を特定できません。一覧を更新してください。');
        }
        const args = [kind, '--json', '--target=' + doc.selector, '--expect-article-url=' + doc.url,
            action, '--id=' + doc.entity_id];
        if (kind !== 'metadata') args.push('--entity=' + doc.entity);
        return json(folder, [...args, ...options], writing, input);
    }
    async function children(row) {
        try {
            const { kind } = row;
            const data = await article(row, kind === 'metadata' ? 'get' : 'list');
            const leaf = (label, value, description = '') => Object.assign(new vscode.TreeItem(label),
                { folder: row.folder, doc: row.doc, kind, value, description, contextValue: 'esync.entry.' + kind });
            let rows;
            if (kind === 'tag') rows = data.entities[0].tags.map(tag => leaf(tag, tag));
            else if (kind === 'relate') {
                rows = Object.entries(data.sources[0].links).flatMap(([type, links]) => links.map(link =>
                    leaf(kindName(type) + ' #' + link.id, { type, id: link.id }, link.title)));
            } else {
                rows = Object.entries(data.entities[0].metadata).map(([key, value]) =>
                    Object.assign(leaf(key, key, typeof value === 'string' ? value : JSON.stringify(value)), { previous: value }));
            }
            return rows.length ? rows : [new vscode.TreeItem(groups[kind] + 'はありません')];
        } catch (error) {
            return [new vscode.TreeItem(error.message)];
        }
    }
    async function edit(row, remove = false) {
        const { kind, doc } = row;
        let action = remove ? 'remove' : 'add';
        let options, summary, input;
        if (kind === 'tag') {
            const tag = remove ? row.value : await vscode.window.showInputBox({ prompt: '追加するタグ名' });
            if (!tag?.trim()) return;
            options = ['--', tag];
            summary = 'タグ「' + tag + '」を' + (remove ? '外す' : '追加');
        } else if (kind === 'relate') {
            let dest = row.value;
            if (!remove) {
                const type = await vscode.window.showQuickPick(['items', 'experiments'], { placeHolder: 'リンク先の記事種別' });
                if (!type) return;
                const id = await vscode.window.showInputBox({ prompt: 'リンク先の記事 ID',
                    validateInput: v => /^[1-9]\d*$/.test(v) && Number.isSafeInteger(Number(v)) ? undefined : '正の整数を入力してください。' });
                if (!id) return;
                dest = { type, id };
            }
            options = ['--to=' + dest.type, '--', String(dest.id)];
            summary = kindName(dest.type) + ' #' + dest.id + ' へのリンクを' + (remove ? '外す' : '追加');
        } else {
            const key = row.value ?? await vscode.window.showInputBox({ prompt: 'メタデータのキー',
                validateInput: v => v.trim() && !v.includes('=') ? undefined : '「=」を含まないキーを入力してください。' });
            if (!key) return;
            const value = await vscode.window.showInputBox({ prompt: key + ' の値（文字列）', value: row.description || '' });
            if (value === undefined) return;
            input = JSON.stringify({ key, value, previous: row.previous });
            options = ['--edit-stdin'];
            action = 'set';
            summary = 'メタデータ「' + key + '」を設定';
        }
        if (!await dialogs.confirm(doc.target + ' の ' + doc.url + ' で' + summary + 'します。', '変更する')) return;
        await article(row, action, options, true, input);
        refresh();
    }
    /** @returns {Promise<vscode.WorkspaceFolder | undefined>} */
    async function project() {
        const folders = projects();
        if (!folders.length) throw new Error('同期設定のあるフォルダーを開いてください。');
        if (folders.length === 1) return folders[0];
        const choice = await vscode.window.showQuickPick(folders.map(folder => ({
            label: folder.name, description: folder.uri.fsPath, folder })), { placeHolder: 'プロジェクトを選択' });
        return choice?.folder;
    }
    async function newDocument() {
        const folder = await project();
        if (!folder) return;
        const { targets } = await json(folder, ['new', '--json', '--list-targets']);
        const choices = targets.filter(t => t.selector).map(t => ({ label: t.target, description: t.docs_dir, selector: t.selector, pattern: t.pattern }));
        if (!choices.length) throw new Error('作成先を特定できません。ターゲットに一意の title を指定してください。');
        /** @type {any} */
        const target = await vscode.window.showQuickPick(choices, { placeHolder: '文書の作成先を選択' });
        if (!target) return;
        const args = ['new', '--json', '--target=' + target.selector];
        const { templates } = await json(folder, [...args, '--list']);
        if (!templates.length) throw new Error('この接続先に実験テンプレートがありません。');
        /** @type {any} */
        const template = await vscode.window.showQuickPick(templates.map(t => ({ label: t.title || '無題', description: '#' + t.id, id: t.id })),
            { placeHolder: 'テンプレートを選択' });
        if (!template) return;
        const title = await vscode.window.showInputBox({ prompt: '文書のタイトル', value: template.label });
        if (!title?.trim()) return;
        const create = [...args, '--template-id=' + template.id, '--title=' + title];
        if (target.pattern && !['*.md', '**/*.md'].includes(target.pattern)) {
            const filename = await vscode.window.showInputBox({ prompt: target.description + ' 内のファイル名（' + target.pattern + '）' });
            if (!filename?.trim()) return;
            create.push('--output=' + path.resolve(folder.uri.fsPath, target.description, filename));
        }
        const result = await json(folder, create, true);
        await vscode.window.showTextDocument(vscode.Uri.file(path.resolve(folder.uri.fsPath, result.path)));
        refresh();
    }
    async function log() {
        const folder = await project();
        if (!folder) return;
        const result = await run(folder, ['log']);
        if (result.code !== 0) throw new Error(result.stderr.trim() || '同期ログを読み取れません。');
        output.appendLine('── ' + folder.name + ' ──\n' + result.stdout.trimEnd());
        output.show(true);
    }
    return { children, edit, newDocument, log };
}
module.exports = { articleActions, articleGroups, articleUri };
