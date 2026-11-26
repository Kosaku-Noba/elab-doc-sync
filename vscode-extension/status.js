const vscode = require('vscode');
const fs = require('node:fs/promises');
const path = require('node:path');

function messageItem(message, detail) {
    const item = new vscode.TreeItem(message);
    item.tooltip = detail || message;
    item.iconPath = new vscode.ThemeIcon('info');
    return item;
}

async function readStatus(folder, run) {
    const result = await run(folder, ['status', '--json']);
    if (result.code !== 0 && !(result.code === 1 && result.stdout.trim())) {
        if (result.stderr.includes('unrecognized arguments: --json')) {
            throw new Error('status --json に対応した esync CLI をインストールしてください。');
        }
        throw new Error(result.stderr.trim() || '同期状態を取得できませんでした。');
    }
    const { documents, recovery_pending } = JSON.parse(result.stdout);
    const notices = [];
    if (recovery_pending) notices.push('復旧待ちのローカル変更があります。esync backup list で確認してください。');
    if (result.stderr.trim()) notices.push(result.stderr.trim());
    return { documents, notices };
}

function documentItem(folder, doc) {
    const item = new vscode.TreeItem(doc.file);
    item.description = doc.path || doc.target;
    item.tooltip = [doc.target, doc.entity_id && '#' + doc.entity_id, doc.error,
        ...doc.remote_changes, ...doc.next_actions].filter(Boolean).join('\n');
    if (doc.path) {
        item.resourceUri = vscode.Uri.file(path.resolve(folder.uri.fsPath, doc.path));
        item.command = { command: 'vscode.open', title: '文書を開く', arguments: [item.resourceUri] };
        item.contextValue = 'esync.document';
        item.folder = folder;
        item.doc = doc;
    }
    return item;
}

function field(label, value) {
    const item = new vscode.TreeItem(label);
    item.description = value;
    item.tooltip = value;
    return item;
}

function detailItems(folder, doc) {
    const source = documentItem(folder, doc);
    const entity = doc.entity === 'items' ? 'リソース' : '実験ノート';
    const action = new vscode.TreeItem('差分を確認');
    action.iconPath = new vscode.ThemeIcon('diff');
    action.command = { command: 'esync.previewFromPanel', title: '差分を確認', arguments: [source] };
    const rows = [
        field('同期状態（保存時点）', doc.state), field('送信先', doc.target + ' / ' + entity),
        field('記事 ID', doc.entity_id == null ? '未割り当て' : '#' + doc.entity_id),
    ];
    if (doc.error) rows.push(messageItem(doc.error));
    rows.push(action);
    return rows;
}

class StatusProvider {
    constructor(projects, run, events) {
        this.projects = projects;
        this.run = run;
        this.onDidChangeTreeData = events.event;
        this.cache = new Map();
    }

    // 二つのビューで同じ取得結果を使い、文書を切り替えても全件を再照会しない。
    status(folder) {
        const key = folder.uri.toString();
        if (!this.cache.has(key)) {
            const entry = { loading: true };
            entry.promise = this.readLatest(folder, entry);
            this.cache.set(key, entry);
        }
        return this.cache.get(key).promise;
    }

    async readLatest(folder, entry) {
        try {
            do {
                entry.stale = false;
                try {
                    const result = await readStatus(folder, this.run);
                    if (!entry.stale) return result;
                } catch (error) {
                    if (!entry.stale) throw error;
                }
            } while (entry.stale);
        } finally {
            entry.loading = false;
        }
    }

    invalidate() {
        for (const [key, entry] of this.cache) {
            if (entry.loading) entry.stale = true;
            else this.cache.delete(key);
        }
    }

    getTreeItem(item) { return item; }

    async getChildren(item) {
        if (item?.children) return item.children;
        if (item && !item.projectRoot) return [];
        const folders = this.projects();
        if (!item && folders.length > 1) {
            return folders.map(folder => {
                const root = new vscode.TreeItem(folder.name, vscode.TreeItemCollapsibleState.Collapsed);
                root.projectRoot = folder;
                return root;
            });
        }
        const folder = item ? item.projectRoot : folders[0];
        if (!folder) return [];
        try {
            const { documents, notices } = await this.status(folder);
            const rows = notices.map(notice => messageItem(notice));
            const groups = new Map();
            for (const doc of documents) {
                if (!groups.has(doc.state)) {
                    const group = new vscode.TreeItem(doc.state, vscode.TreeItemCollapsibleState.Expanded);
                    group.children = [];
                    groups.set(doc.state, group);
                    rows.push(group);
                }
                const group = groups.get(doc.state);
                group.children.push(documentItem(folder, doc));
                group.description = String(group.children.length);
            }
            return rows.length ? rows : [messageItem('同期対象の文書はありません')];
        } catch (error) {
            return [messageItem(error.message)];
        }
    }
}

class CurrentDocumentProvider {
    constructor(status, activeFile, events) {
        this.status = status;
        this.activeFile = activeFile;
        this.onDidChangeTreeData = events.event;
    }

    getTreeItem(item) { return item; }

    async getChildren(item) {
        if (item) return item.children || [];
        const active = this.activeFile();
        if (!active) return [messageItem('同期対象の Markdown を開いてください。')];
        const { file, folder: previewFolder } = active;
        const realPath = await fs.realpath(file.fsPath).catch(() => file.fsPath);
        const folders = this.status.projects();
        const matches = [];
        const notices = [];
        // docs_dir が他のワークスペースフォルダーを指す場合も、その設定の送信先を表示する。
        const relevant = previewFolder ? folders.filter(f => f.uri.toString() === previewFolder.uri.toString()) : folders;
        const results = await Promise.allSettled(relevant.map(folder => this.status.status(folder)));
        for (const [index, result] of results.entries()) {
            const folder = relevant[index];
            if (result.status === 'rejected') {
                notices.push(messageItem(folder.name + ' — ' + result.reason.message));
                continue;
            }
            notices.push(...result.value.notices.map(notice => messageItem(notice)));
            for (const doc of result.value.documents) {
                if (doc.path && path.relative(realPath, path.resolve(folder.uri.fsPath, doc.path)) === '') {
                    matches.push({ folder, doc });
                }
            }
        }
        const name = new vscode.TreeItem(path.basename(file.fsPath));
        name.resourceUri = file;
        name.tooltip = file.fsPath;
        name.command = { command: 'vscode.open', title: '文書を開く', arguments: [file] };
        const rows = [name, ...notices];
        if (!matches.length && results.every(r => r.status === 'fulfilled')) {
            rows.push(messageItem('この文書は同期対象に含まれていません。'));
        }
        for (const { folder, doc } of matches) {
            const details = detailItems(folder, doc);
            if (matches.length === 1) rows.push(...details);
            else {
                const group = new vscode.TreeItem(doc.target, vscode.TreeItemCollapsibleState.Expanded);
                group.description = folder.name + ' / ' + doc.entity;
                group.children = details;
                rows.push(group);
            }
        }
        return rows;
    }
}

module.exports = { StatusProvider, CurrentDocumentProvider };
