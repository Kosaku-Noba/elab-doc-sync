const vscode = require('vscode');
const fs = require('node:fs/promises');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { createHash } = require('node:crypto');
const { StatusProvider } = require('./status');

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

async function activate(context) {
    const events = new vscode.EventEmitter();
    const previews = new Map();
    const pushing = new Set();
    let projects = [];
    let scan = 0;
    let sequence = 0;
    const status = new StatusProvider(() => projects, run, events);
    const output = vscode.window.createOutputChannel('esync');

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
        events.fire();
    }

    async function preview(uri) {
        const file = uri || vscode.window.activeTextEditor?.document.uri;
        if (file?.scheme !== 'file' || !projects.length) {
            throw new Error('.elab-sync.yaml のあるフォルダーを開き、同期対象の Markdown を選んでください。');
        }
        const owner = vscode.workspace.getWorkspaceFolder(file);
        let folder = projects.find(p => p.uri.toString() === owner?.uri.toString());
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
        const result = await run(folder, ['diff', '--', file.fsPath]);
        if (result.code !== 0) throw new Error(result.stderr.trim() || result.stdout.trim() || '差分を取得できませんでした。');
        const previewUri = vscode.Uri.from({
            scheme: previewScheme, path: file.path + '.diff', query: String(++sequence),
        });
        previews.set(previewUri.toString(), { folder, file, hash, text: result.stdout + result.stderr });
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
        const { folder, file, hash } = entry;
        const project = folder.uri.toString();
        if (pushing.has(project)) throw new Error('このプロジェクトで push を実行中です。');
        pushing.add(project);
        try {
            const doc = await vscode.workspace.openTextDocument(file);
            if (doc.isDirty || await fingerprint(file) !== hash) {
                throw new Error('差分を開いた後に文書が変更されました。文書を保存して差分を開き直してください。');
            }
            const result = await run(folder, ['push', '--', file.fsPath]);
            const report = (result.stdout + '\n' + result.stderr).trim();
            output.appendLine(report);
            if (result.code !== 0) {
                output.show(true);
                throw new Error('push に失敗しました。出力「esync」で結果を確認してください。');
            }
            vscode.window.showInformationMessage(path.basename(file.fsPath) + ' — ' + (result.stdout.trim().split('\n').pop() || 'push 完了'));
        } finally {
            pushing.delete(project);
            events.fire();
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
        events, output, watcher,
        vscode.window.registerTreeDataProvider('esync.status', status),
        vscode.workspace.registerTextDocumentContentProvider(previewScheme, {
            provideTextDocumentContent: uri => previews.get(uri.toString())?.text,
        }),
        vscode.workspace.onDidCloseTextDocument(doc => previews.delete(doc.uri.toString())),
        vscode.workspace.onDidChangeWorkspaceFolders(discover),
        watcher.onDidCreate(discover), watcher.onDidDelete(discover), watcher.onDidChange(discover),
        vscode.commands.registerCommand('esync.refresh', () => events.fire()),
        command('esync.preview', 'esync 差分を取得中', preview),
        command('esync.push', 'esync 送信中', push),
    );
    await discover();
}

module.exports = { activate };
