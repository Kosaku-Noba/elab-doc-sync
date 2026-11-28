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

async function openBeside(doc) {
    const uri = articleUri(doc);
    const command = 'workbench.action.browser.open';
    let message = 'この VS Code では統合ブラウザーを利用できません。';
    if ((await vscode.commands.getCommands(true)).includes(command)) {
        try {
            await vscode.commands.executeCommand(command, { url: new URL(doc.url).href, openToSide: true });
            return;
        } catch (error) {
            message = '統合ブラウザーで記事を開けませんでした。' + error.message;
        }
    }
    const external = '外部ブラウザで開く';
    if (await vscode.window.showInformationMessage(message, external) === external) {
        await vscode.env.openExternal(uri);
    }
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
                if (!Array.isArray(data.entities[0].fields)) throw new Error('拡張と同じ版の CLI をインストールしてください。');
                rows = data.entities[0].fields.map(({ key, text, token }) =>
                    Object.assign(leaf(key, key, text), { previousToken: token }));
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
            input = JSON.stringify({ key, value, previous_token: row.previousToken });
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
    async function openMarkdown(folder, doc, targets) {
        if (doc.local_path) {
            const local = vscode.Uri.file(path.resolve(folder.uri.fsPath, doc.local_path));
            try {
                const stat = await vscode.workspace.fs.stat(local);
                if (stat.type & vscode.FileType.File) {
                    await vscode.window.showTextDocument(local);
                    return;
                }
            } catch (error) {
                if (error.code !== 'FileNotFound') throw error;
            }
        }
        const choices = targets.filter(t => t.entity === doc.entity && t.selector).map(t => ({
            label: t.target, description: t.docs_dir, selector: t.selector,
        }));
        if (!targets.some(t => t.selector)) throw new Error('取得元の接続先を特定できません。ターゲットを確認してください。');
        const target = !choices.length ? targets.find(t => t.selector) : choices.length === 1 ? choices[0]
            : await vscode.window.showQuickPick(choices, { placeHolder: 'Markdown の保存先を選択' });
        if (!target) return;
        const args = ['pull', '--json', '--target=' + target.selector, '--entity=' + doc.entity,
            '--id=' + doc.id, '--expect-article-url=' + doc.url];
        const resultDoc = data => {
            const result = data.documents.find(d => d.entity === doc.entity && d.entity_id === doc.id);
            if (!result?.path || result.error) throw new Error(result?.error || '記事の保存先を確認できません。');
            return result;
        };
        const plan = resultDoc(await json(folder, [...args, '--dry-run']));
        const file = vscode.Uri.file(path.resolve(folder.uri.fsPath, plan.path));
        if (plan.result !== 'existing') {
            if (plan.result !== 'would_pull') throw new Error('この記事を取り込めません。同期状態を確認してください。');
            const notice = choices.length ? '' : ' 必要に応じてこの保存先を同期設定に追加します。';
            if (!await dialogs.confirm(kindName(doc.entity) + ' #' + doc.id + '「' + doc.title + '」を ' + plan.path + ' に取り込みます。' + notice, '取り込む')) return;
            if (vscode.workspace.textDocuments.some(d => d.isDirty && d.uri.toString() === file.toString())) {
                throw new Error(plan.path + ' に未保存の編集があります。');
            }
            try {
                const result = resultDoc(await json(folder, [...args, '--expect-path=' + plan.path], true));
                if (!['existing', 'pulled'].includes(result.result)) throw new Error('記事を取り込めませんでした。');
                await vscode.window.showTextDocument(vscode.Uri.file(path.resolve(folder.uri.fsPath, result.path)));
            } finally {
                refresh();
            }
        } else {
            await vscode.window.showTextDocument(file);
        }
    }
    async function search() {
        const folder = await project();
        if (!folder) return;
        const { targets } = await json(folder, ['new', '--json', '--list-targets']);
        const connections = new Map();
        for (const target of targets) {
            const profile = target.profile ?? target.selector;
            if (target.selector && !connections.has(profile)) connections.set(profile, target.selector);
        }
        if (!connections.size && targets.length) throw new Error('検索先を特定できません。ターゲットに一意の title を指定してください。');
        const profiles = [...connections.keys()];
        const profile = profiles.length > 1
            ? await vscode.window.showQuickPick(profiles, { placeHolder: '検索する接続先' }) : profiles[0];
        if (profiles.length && profile === undefined) return;
        const keyword = await vscode.window.showInputBox({ prompt: '記事を検索（空欄で最近の記事を表示）' });
        if (keyword === undefined) return;
        const args = ['search', '--json', '--scope', 'all', '--entity', 'all', '--order', 'lastchange', '--sort', 'desc', '--limit', '20'];
        if (profile !== undefined) args.push('--target=' + connections.get(profile));
        let offset = 0;
        while (true) {
            const page = await json(folder, [...args, '--offset', String(offset), '--', ...(keyword.trim() ? [keyword.trim()] : [])]);
            const limitMessage = '検索上限に達しました。検索語を絞ってください。';
            if (!page.results.length) {
                await vscode.window.showInformationMessage(page.truncated ? limitMessage : '該当する記事はありません。');
                return;
            }
            /** @type {(vscode.QuickPickItem & { doc?: any })[]} */
            const items = page.results.map(doc => ({
                label: doc.title || '無題', description: kindName(doc.entity) + ' #' + doc.id,
                detail: '更新日　' + (doc.modified_at || '不明'), doc,
            }));
            if (Number.isSafeInteger(page.next_offset) && page.next_offset > offset) items.push({ label: '次の20件' });
            const choice = await vscode.window.showQuickPick(items, {
                placeHolder: page.truncated ? limitMessage : '記事を選択',
            });
            if (!choice) return;
            if (choice.doc) {
                const markdown = choice.doc.local_path ? 'Markdown を開く' : 'Markdown に取り込む';
                const beside = '記事を横に開く';
                const action = await vscode.window.showQuickPick([beside, markdown], { placeHolder: choice.label });
                if (action === beside) return openBeside(choice.doc);
                if (action === markdown) return openMarkdown(folder, choice.doc,
                    targets.filter(t => (t.profile ?? t.selector) === profile));
                return;
            }
            offset = page.next_offset;
        }
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
    return { children, edit, newDocument, search, log, project };
}
module.exports = { articleActions, articleGroups, articleUri, openBeside };
