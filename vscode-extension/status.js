const vscode = require('vscode');
const path = require('node:path');

function messageItem(message, detail) {
    const item = new vscode.TreeItem(message);
    item.tooltip = detail || message;
    item.iconPath = new vscode.ThemeIcon('info');
    return item;
}

async function projectItems(folder, run) {
    const result = await run(folder, ['status', '--json']);
    if (result.code !== 0 && !(result.code === 1 && result.stdout.trim())) {
        if (result.stderr.includes('unrecognized arguments: --json')) {
            throw new Error('status --json に対応した esync CLI をインストールしてください。');
        }
        throw new Error(result.stderr.trim() || '同期状態を取得できませんでした。');
    }
    const { documents, recovery_pending } = JSON.parse(result.stdout);
    const rows = [];
    const groups = new Map();
    for (const doc of documents) {
        if (!groups.has(doc.state)) {
            const group = new vscode.TreeItem(doc.state, vscode.TreeItemCollapsibleState.Expanded);
            group.children = [];
            groups.set(doc.state, group);
            rows.push(group);
        }
        const item = new vscode.TreeItem(doc.file);
        item.description = doc.path || doc.target;
        item.tooltip = [doc.target, doc.entity_id && '#' + doc.entity_id, doc.error,
            ...doc.remote_changes, ...doc.next_actions].filter(Boolean).join('\n');
        if (doc.path) {
            item.resourceUri = vscode.Uri.file(path.resolve(folder.uri.fsPath, doc.path));
            item.command = { command: 'vscode.open', title: '文書を開く', arguments: [item.resourceUri] };
        }
        groups.get(doc.state).children.push(item);
    }
    if (recovery_pending) {
        rows.unshift(messageItem('復旧待ちのローカル変更があります', 'esync backup list でバックアップを確認してください。'));
    }
    for (const group of groups.values()) {
        group.description = String(group.children.length);
    }
    return rows.length ? rows : [messageItem('同期対象の文書はありません')];
}

class StatusProvider {
    constructor(projects, run, events) {
        this.projects = projects;
        this.run = run;
        this.onDidChangeTreeData = events.event;
    }

    getTreeItem(item) { return item; }

    async getChildren(item) {
        if (item?.children) return item.children;
        const folders = this.projects();
        if (!item && folders.length > 1) {
            return folders.map(folder => {
                const root = new vscode.TreeItem(folder.name, vscode.TreeItemCollapsibleState.Collapsed);
                root.folder = folder;
                return root;
            });
        }
        const folder = item ? item.folder : folders[0];
        if (!folder) return [];
        try {
            return await projectItems(folder, this.run);
        } catch (error) {
            return [messageItem(error.message, error.message)];
        }
    }
}

module.exports = { StatusProvider };
