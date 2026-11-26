const vscode = require('vscode');
const fs = require('node:fs/promises');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { createHash } = require('node:crypto');
const { StatusProvider, CurrentDocumentProvider } = require('./status');

const configName = '.elab-sync.yaml';
const previewScheme = 'esync-preview';

function run(folder, args) {
    const executable = vscode.workspace.getConfiguration('esync').get('executable', 'esync');
    return new Promise((resolve, reject) => {
        const child = spawn(executable, args, {
            cwd: folder.uri.fsPath,
            env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
            stdio: ['ignore', 'pipe', 'pipe'],
            windowsHide: true,
        });
        let stdout = '';
        let stderr = '';
        child.stdout.setEncoding('utf8').on('data', data => { stdout += data; });
        child.stderr.setEncoding('utf8').on('data', data => { stderr += data; });
        child.on('error', error => reject(error.code === 'ENOENT'
            ? new Error('esync を起動できません。設定 esync.executable で実行ファイルを指定してください。')
            : error));
        child.on('close', (code, signal) => {
            if (signal) reject(new Error('esync が中断されました (' + signal + ')'));
            else resolve({ code, stdout, stderr });
        });
    });
}

async function fingerprint(file) {
    return createHash('sha256').update(await fs.readFile(file.fsPath)).digest('hex');
}

async function loadDiff(folder, file, options) {
    const result = await run(folder, ['diff', '--json', ...options, '--', file.fsPath]);
    if (result.code !== 0 && !(result.code === 1 && result.stdout.trim())) {
        throw new Error(result.stderr.trim() || '差分を取得できませんでした。');
    }
    return { documents: JSON.parse(result.stdout).documents, warnings: result.stderr.trim() };
}

function diffText(doc, warnings) {
    const destination = doc.entity_id == null ? '新規作成' : '#' + doc.entity_id;
    const lines = [targetLabel(doc) + ' — ' + doc.server + ' / ' + doc.entity + ' ' + destination,
        doc.path + ' — ' + doc.state];
    if (doc.renamed_from) lines.push('改名前の文書: ' + doc.renamed_from);
    if (warnings) lines.push(warnings);
    for (const [label, changes] of [
        ['ローカルの変更', doc.local_diff],
        ['ローカルと eLabFTW の本文の差', doc.direct_diff],
        ['eLabFTW 側の変更', doc.remote_changes],
        ['eLabFTW 側の本文の差', doc.remote_diff],
    ]) {
        if (changes?.length) lines.push('', label, changes.join('\n'));
    }
    if (doc.local_changed) lines.push('画像・添付ファイルまたは設定に変更があります。');
    return lines.join('\n') + '\n';
}

function targetLabel(doc) {
    return doc.selector && doc.selector !== doc.target ? doc.target + ' (' + doc.selector + ')' : doc.target;
}

async function activate(context) {
    const events = new vscode.EventEmitter();
    const currentEvents = new vscode.EventEmitter();
    const previews = new Map();
    const pushing = new Set();
    let projects = [];
    let scan = 0;
    let sequence = 0;
    const status = new StatusProvider(() => projects, run, events, currentEvents);
    const currentDocument = new CurrentDocumentProvider(status, () => {
        const doc = vscode.window.activeTextEditor?.document;
        if (!doc) return;
        const entry = previews.get(doc.uri.toString());
        if (entry) return { file: entry.file, folder: entry.folder };
        if (doc.uri.scheme === 'file' && doc.languageId === 'markdown') return { file: doc.uri };
    }, currentEvents, loadDiff);
    const output = vscode.window.createOutputChannel('esync');

    function refresh() {
        status.invalidate();
        events.fire();
        currentEvents.fire();
    }

    async function discover() {
        const current = ++scan;
        const folders = vscode.workspace.workspaceFolders || [];
        const found = await Promise.all(folders.map(async folder => {
            try {
                if ((await fs.stat(path.join(folder.uri.fsPath, configName))).isFile()) return folder;
            } catch (error) {
                if (error.code !== 'ENOENT') output.appendLine(error.message);
            }
        }));
        if (current !== scan) return;
        projects = found.filter(Boolean);
        await vscode.commands.executeCommand('setContext', 'esync.hasProjects', projects.length > 0);
        refresh();
    }

    async function preview(uri, row) {
        const file = uri || vscode.window.activeTextEditor?.document.uri;
        if (file?.scheme !== 'file' || !projects.length) {
            throw new Error('.elab-sync.yaml のあるフォルダーを開き、同期対象の Markdown を選んでください。');
        }
        const owner = vscode.workspace.getWorkspaceFolder(file);
        const projectUri = row ? row.folder.uri : owner?.uri;
        let folder = projects.find(p => p.uri.toString() === projectUri?.toString());
        if (row && !folder) throw new Error('同期設定が変わりました。一覧を更新してください。');
        if (!folder) {
            // docs_dir はワークスペース外のディレクトリも指定できる。
            if (projects.length === 1) folder = projects[0];
            else {
                const choice = await vscode.window.showQuickPick(
                    projects.map(p => ({ label: p.name, description: p.uri.fsPath, folder: p })),
                    { placeHolder: 'この文書の同期設定があるフォルダーを選択' },
                );
                if (!choice) return;
                folder = choice.folder;
            }
        }
        const doc = await vscode.workspace.openTextDocument(file);
        if (doc.isDirty) {
            const save = '保存して差分を確認';
            if (await vscode.window.showInformationMessage('差分の確認には文書の保存が必要です。', save) !== save) return;
            if (!await doc.save()) throw new Error('文書を保存できませんでした。');
        }
        const hash = await fingerprint(file);
        const config = vscode.Uri.joinPath(folder.uri, configName);
        const configHash = await fingerprint(config);
        const diffResult = await loadDiff(folder, file, []);
        const warnings = diffResult.warnings;
        const documents = row ? diffResult.documents.filter(doc =>
            doc.target === row.doc.target && doc.entity === row.doc.entity) : diffResult.documents;
        if (row && !documents.length) throw new Error('送信先が変わりました。一覧を更新してください。');
        let selected = documents[0];
        if (documents.length > 1) {
            const choice = await vscode.window.showQuickPick(documents.map(doc => ({
                label: targetLabel(doc), description: doc.server + ' / ' + doc.entity, doc,
            })), { placeHolder: '差分を確認して push するターゲットを選択' });
            if (!choice) return;
            selected = choice.doc;
        }
        if (!selected) throw new Error('同期対象の文書がありません。');
        if (selected.error) throw new Error(selected.error);
        if (diffResult.documents.length > 1 && !selected.selector) throw new Error('送信先を区別できるよう設定でターゲットに一意の title を付けてください。');
        if (!selected.preview_token) throw new Error('push --expect-preview に対応した esync CLI に更新してください。');
        const options = selected.selector ? ['--target=' + selected.selector] : [];
        const previewUri = vscode.Uri.from({
            scheme: previewScheme, path: file.path + '.diff', query: String(++sequence),
        });
        previews.set(previewUri.toString(), { folder, file, hash, config, configHash, options,
            selected, text: diffText(selected, warnings) });
        try {
            const diff = await vscode.workspace.openTextDocument(previewUri);
            await vscode.window.showTextDocument(diff, { preview: true });
        } catch (error) {
            previews.delete(previewUri.toString());
            throw error;
        }
    }

    async function push(uri) {
        const entry = previews.get((uri || vscode.window.activeTextEditor?.document.uri)?.toString());
        if (!entry) throw new Error('送信する文書の差分を開き直してください。');
        const { folder, file, hash, config, configHash, options, selected } = entry;
        const project = folder.uri.toString();
        if (pushing.has(project)) throw new Error('このプロジェクトで push を実行中です。');
        pushing.add(project);
        try {
            const doc = await vscode.workspace.openTextDocument(file);
            if (doc.isDirty || await fingerprint(file) !== hash) {
                throw new Error('差分を開いた後に文書が変更されました。文書を保存して差分を開き直してください。');
            }
            const current = await loadDiff(folder, file, options);
            if (current.documents.length !== 1 || JSON.stringify(current.documents[0]) !== JSON.stringify(selected)
                    || await fingerprint(config) !== configHash || doc.isDirty || await fingerprint(file) !== hash) {
                throw new Error('同期対象の内容、設定または eLabFTW の状態が変わりました。差分を開き直してください。');
            }
            const result = await run(folder, ['push', '--expect-preview', selected.preview_token, ...options, '--', file.fsPath]);
            const report = (result.stdout + '\n' + result.stderr).trim();
            output.appendLine(report);
            if (result.code !== 0) {
                output.show(true);
                throw new Error('push に失敗しました。出力「esync」で結果を確認してください。');
            }
            vscode.window.showInformationMessage(path.basename(file.fsPath) + ' — ' + (result.stdout.trim().split('\n').pop() || 'push 完了'));
        } finally {
            pushing.delete(project);
            refresh();
        }
    }

    function command(name, title, action) {
        return vscode.commands.registerCommand(name, async uri => {
            try {
                await vscode.window.withProgress({ location: vscode.ProgressLocation.Window, title }, () => action(uri));
            } catch (error) {
                vscode.window.showErrorMessage(error.message);
            }
        });
    }

    const watcher = vscode.workspace.createFileSystemWatcher('**/' + configName);
    context.subscriptions.push(
        events, currentEvents, output, watcher,
        vscode.window.registerTreeDataProvider('esync.status', status),
        vscode.window.registerTreeDataProvider('esync.current', currentDocument),
        vscode.window.onDidChangeActiveTextEditor(() => currentEvents.fire()),
        vscode.workspace.onDidSaveTextDocument(doc => {
            if (doc.languageId === 'markdown') refresh();
        }),
        vscode.workspace.onDidChangeConfiguration(event => {
            if (event.affectsConfiguration('esync.executable')) refresh();
        }),
        vscode.workspace.registerTextDocumentContentProvider(previewScheme, {
            provideTextDocumentContent: uri => previews.get(uri.toString())?.text,
        }),
        vscode.workspace.onDidCloseTextDocument(doc => previews.delete(doc.uri.toString())),
        vscode.workspace.onDidChangeWorkspaceFolders(discover),
        watcher.onDidCreate(discover), watcher.onDidDelete(discover), watcher.onDidChange(discover),
        vscode.commands.registerCommand('esync.refresh', refresh),
        command('esync.previewFromPanel', 'esync 差分を取得中', row => preview(row.resourceUri, row)),
        command('esync.preview', 'esync 差分を取得中', preview),
        command('esync.push', 'esync 送信中', push),
    );
    await discover();
}

module.exports = { activate };
