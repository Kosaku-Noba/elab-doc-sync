const vscode = require('vscode');
const fs = require('node:fs/promises');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { StatusProvider, CurrentDocumentProvider, statusBarView, fileDecoration } = require('./status');
const { createRunner, checkVersion } = require('./cli');

const configName = '.elab-sync.yaml';
// 差分タブの右側（確認した送信内容）。push はこのタブから行う。
const previewScheme = 'esync-preview';
// 差分タブの左側や eLabFTW 側の本文。読み取り専用。
const snapshotScheme = 'esync-snapshot';
const output = vscode.window.createOutputChannel('esync');
const settings = () => vscode.workspace.getConfiguration('esync');
const run = createRunner(() => settings().get('executable', 'esync'), line => output.appendLine(line),
    () => Math.max(0, settings().get('timeoutSeconds', 120)) * 1000);

async function fingerprint(file) {
    return createHash('sha256').update(await fs.readFile(file.fsPath)).digest('hex');
}

async function loadDiff(folder, file, options, token) {
    const result = await run(folder, ['diff', '--json', '--bodies', ...options, '--', file.fsPath], { token });
    if (result.code !== 0 && !(result.code === 1 && result.stdout.trim())) {
        throw new Error(result.stderr.trim() || '差分を取得できませんでした。');
    }
    return { documents: JSON.parse(result.stdout).documents, warnings: result.stderr.trim() };
}

function targetLabel(doc) {
    return doc.selector && doc.selector !== doc.target ? doc.target + ' (' + doc.selector + ')' : doc.target;
}

async function activate(context) {
    const events = new vscode.EventEmitter();
    const currentEvents = new vscode.EventEmitter();
    const previews = new Map();
    /** @type {Map<string, string>} */
    const snapshots = new Map();
    // 差分タブの左側から、その差分タブの右側（確認した内容）を引く。左側にフォーカスがあっても push できるようにする。
    /** @type {Map<string, string>} */
    const owners = new Map();
    const pushing = new Set();
    let projects = [];
    let scan = 0;
    let sequence = 0;
    const status = new StatusProvider(() => projects, run, events, currentEvents);
    const currentDocument = new CurrentDocumentProvider(status, () => {
        const doc = vscode.window.activeTextEditor?.document;
        if (!doc) return;
        const entry = previews.get(doc.uri.toString());
        if (entry) return { file: entry.file, folder: entry.folder, preview: entry };
        if (doc.uri.scheme === 'file' && doc.languageId === 'markdown') return { file: doc.uri };
    }, currentEvents, loadDiff);
    let checkedExecutable;

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
        checkCli();
    }

    // 古い CLI では差分や push が途中で失敗するので、使い始める前に一度だけ知らせる。
    async function checkCli() {
        const executable = settings().get('executable', 'esync');
        if (!projects.length || executable === checkedExecutable) return;
        checkedExecutable = executable;
        let problem;
        try {
            problem = await checkVersion(run, projects[0]);
        } catch (error) {
            problem = error.message;
        }
        if (!problem || executable !== settings().get('executable', 'esync')) return;
        const open = '設定を開く';
        if (await vscode.window.showWarningMessage(problem, open) === open) {
            await vscode.commands.executeCommand('workbench.action.openSettings', 'esync.executable');
        }
    }

    async function preview(uri, row, token) {
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
                    { placeHolder: 'この文書の同期設定があるフォルダーを選択' }, token,
                );
                if (!choice || token?.isCancellationRequested) return;
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
        const diffResult = await loadDiff(folder, file, [], token);
        const warnings = diffResult.warnings;
        const documents = row ? diffResult.documents.filter(doc =>
            doc.target === row.doc.target && doc.entity === row.doc.entity) : diffResult.documents;
        if (row && !documents.length) throw new Error('送信先が変わりました。一覧を更新してください。');
        let selected = documents[0];
        if (documents.length > 1) {
            /** @type {(vscode.QuickPickItem & { doc: any })[]} */
            const items = documents.map(doc => ({
                label: targetLabel(doc), description: doc.server + ' / ' + doc.entity, doc,
            }));
            const choice = await vscode.window.showQuickPick(items,
                { placeHolder: '差分を確認して push するターゲットを選択' }, token);
            if (!choice || token?.isCancellationRequested) return;
            selected = choice.doc;
        }
        if (!selected) throw new Error('同期対象の文書がありません。');
        if (selected.error) throw new Error(selected.error);
        if (diffResult.documents.length > 1 && !selected.selector) throw new Error('送信先を区別できるよう設定でターゲットに一意の title を付けてください。');
        if (!selected.preview_token || selected.local_body == null) {
            throw new Error('esync CLI を 1.5.0 以降に更新してください。');
        }
        const options = selected.selector ? ['--target=' + selected.selector] : [];
        if (token?.isCancellationRequested) return;
        const id = String(++sequence);
        const snapshot = (/** @type {string} */ side, /** @type {string} */ text) => {
            const uri = vscode.Uri.from({ scheme: snapshotScheme, path: file.path, query: id + '-' + side });
            snapshots.set(uri.toString(), text);
            return uri;
        };
        // 右側は保存した文書そのものではなく、確認時点の内容。push はこの内容と一致する場合だけ送信する。
        const previewUri = vscode.Uri.from({ scheme: previewScheme, path: file.path, query: id });
        const left = snapshot('base', selected.base_body ?? '');
        const remote = selected.remote_body == null ? undefined
            : { left: snapshot('remote-base', selected.remote_base_body ?? ''), right: snapshot('remote', selected.remote_body) };
        const entry = { uri: previewUri.toString(), folder, file, hash, config, configHash, options, selected,
            warnings, text: selected.local_body, snapshots: [left, remote?.left, remote?.right].filter(Boolean), remote };
        previews.set(entry.uri, entry);
        for (const uri of entry.snapshots) owners.set(uri.toString(), entry.uri);
        const destination = selected.entity_id == null ? '新規作成' : '#' + selected.entity_id;
        const title = path.basename(file.fsPath) + ': ' + (selected.base_label || '前回の同期') + ' ↔ 送信する内容（'
            + targetLabel(selected) + ' ' + destination + '）';
        try {
            await vscode.commands.executeCommand('vscode.diff', left, previewUri, title, { preview: true });
        } catch (error) {
            forget(entry);
            throw error;
        }
        if ((selected.base_body ?? '') === selected.local_body) {
            vscode.window.showInformationMessage(selected.local_changed
                ? '本文の変更はありません。画像・添付ファイルまたは設定の変更が push で送信されます。'
                : '本文の変更はありません。');
        }
    }

    // ステータスバーに表示した送信先から差分を開く。複数あれば選ぶ。
    async function previewMatches({ file, matches }, token) {
        if (!matches.length) return preview(file, undefined, token);
        let match = matches[0];
        if (matches.length > 1) {
            const choice = await vscode.window.showQuickPick(matches.map(m => ({
                label: m.doc.target, description: m.folder.name + ' / ' + m.doc.entity + ' — ' + m.doc.state, match: m,
            })), { placeHolder: '差分を確認する送信先を選択' }, token);
            if (!choice || token?.isCancellationRequested) return;
            match = choice.match;
        }
        return preview(file, match, token);
    }

    function forget(entry) {
        previews.delete(entry.uri);
        for (const uri of entry.snapshots) {
            snapshots.delete(uri.toString());
            owners.delete(uri.toString());
        }
    }

    async function showRemoteChanges(uri) {
        const entry = previews.get(uri);
        if (!entry?.remote) throw new Error('差分を開き直してください。');
        // プレビュー用のタブで開くと差分タブと置き換わり、確認中の内容が破棄されるので、別のタブで開く。
        await vscode.commands.executeCommand('vscode.diff', entry.remote.left, entry.remote.right,
            path.basename(entry.file.fsPath) + ': 前回の同期 ↔ eLabFTW の現在の本文', { preview: false });
    }

    async function push(uri) {
        const key = (uri || vscode.window.activeTextEditor?.document.uri)?.toString();
        const entry = previews.get(key) || previews.get(owners.get(key));
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
            // 送信を途中で止めると記事が中途半端に更新されるので、push は時間で打ち切らない。
            const result = await run(folder, ['push', '--expect-preview', selected.preview_token, ...options, '--', file.fsPath],
                { timeout: 0 });
            // stderr は run が出力に書く。
            if (result.stdout.trim()) output.appendLine(result.stdout.trimEnd());
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

    function command(name, title, action, cancellable = false) {
        return vscode.commands.registerCommand(name, async uri => {
            const location = cancellable ? vscode.ProgressLocation.Notification : vscode.ProgressLocation.Window;
            try {
                await vscode.window.withProgress({ location, title, cancellable }, (_, token) => action(uri, token));
            } catch (error) {
                if (!(error instanceof vscode.CancellationError)) vscode.window.showErrorMessage(error.message);
            }
        });
    }

    // 開いている Markdown の同期状態。クリックで差分を開く。
    const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
    statusBar.name = 'esync';
    let statusUpdate = 0;
    async function updateStatusBar() {
        const current = ++statusUpdate;
        const doc = vscode.window.activeTextEditor?.document;
        const found = projects.length && doc?.uri.scheme === 'file' && doc.languageId === 'markdown'
            ? await status.documentsFor(doc.uri, undefined) : undefined;
        const view = found && statusBarView(found.matches, found.errors);
        if (current !== statusUpdate) return;
        if (!view) {
            statusBar.hide();
            return;
        }
        statusBar.text = view.text;
        statusBar.tooltip = view.tooltip;
        // 表示した送信先の差分を開く。ファイルが属するフォルダーではなく、同期設定のあるプロジェクトを使う。
        statusBar.command = { command: 'esync.previewFromStatusBar', title: '差分を確認',
            arguments: [{ file: doc.uri, matches: found.matches }] };
        statusBar.show();
    }

    // Explorer のバッジ。取得済みの同期状態だけを使い、表示のために eLabFTW へ問い合わせない。
    const decorations = {
        changed: new vscode.EventEmitter(),
        get onDidChangeFileDecorations() { return this.changed.event; },
        provideFileDecoration: uri => uri.scheme === 'file' ? fileDecoration(status.statesOf(uri)) : undefined,
    };

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
            if (event.affectsConfiguration('esync.executable')) {
                refresh();
                checkCli();
            }
        }),
        vscode.workspace.registerTextDocumentContentProvider(previewScheme, {
            provideTextDocumentContent: uri => previews.get(uri.toString())?.text,
        }),
        vscode.workspace.registerTextDocumentContentProvider(snapshotScheme, {
            provideTextDocumentContent: uri => snapshots.get(uri.toString()),
        }),
        // 差分タブを閉じたら、その左側と eLabFTW 側の本文も破棄する。
        vscode.workspace.onDidCloseTextDocument(doc => {
            const entry = previews.get(doc.uri.toString());
            if (entry) forget(entry);
        }),
        vscode.workspace.onDidChangeWorkspaceFolders(discover),
        watcher.onDidCreate(discover), watcher.onDidDelete(discover), watcher.onDidChange(discover),
        vscode.commands.registerCommand('esync.refresh', refresh),
        command('esync.previewFromPanel', 'esync 差分を取得中', (row, token) => preview(row.resourceUri, row, token), true),
        command('esync.preview', 'esync 差分を取得中', (uri, token) => preview(uri, undefined, token), true),
        command('esync.push', 'esync 送信中', push),
        command('esync.showRemoteChanges', 'esync 差分を表示中', showRemoteChanges),
        command('esync.previewFromStatusBar', 'esync 差分を取得中', previewMatches, true),
        statusBar,
        vscode.window.registerFileDecorationProvider(decorations),
        events.event(() => decorations.changed.fire(undefined)),
        // 改名した文書の記事 ID が照会で分かったら、バッジも更新する。
        currentEvents.event(() => decorations.changed.fire(undefined)),
        decorations.changed,
        currentEvents.event(updateStatusBar),
    );
    await discover();
    // テスト用。拡張ホストのテストから内部の状態を確かめる。
    return { preview, statusBar, snapshots, previews, decorations };
}

module.exports = { activate };
