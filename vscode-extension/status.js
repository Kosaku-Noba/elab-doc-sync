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
    return { documents, notices, root: await fs.realpath(folder.uri.fsPath) };
}

// 改名元の候補（ローカルにない記事）の集合。変わると改名先の判定も変わりうる。
function candidateSet(documents) {
    return JSON.stringify(documents.filter(doc => !doc.path && doc.entity_id != null)
        .map(doc => [doc.target, doc.entity, doc.entity_id]).sort());
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
    const id = doc.entity_id == null ? '未割り当て' : '#' + doc.entity_id;
    const rows = [
        field('同期状態（保存時点）', doc.state), field('送信先', doc.target + ' / ' + entity),
        field('記事 ID', doc.idMessage || id),
    ];
    if (doc.error) rows.push(messageItem(doc.error));
    rows.push(action);
    return rows;
}

class StatusProvider {
    constructor(projects, run, events, currentEvents) {
        this.projects = projects;
        this.run = run;
        this.events = events;
        this.currentEvents = currentEvents;
        this.onDidChangeTreeData = events.event;
        this.cache = new Map();
    }

    // 取得中も直近の結果を表示する。連続した更新は同じ再取得にまとめる。
    status(folder) {
        const key = folder.uri.toString();
        if (!this.cache.has(key)) this.cache.set(key, { dirty: true, details: new Map() });
        const entry = this.cache.get(key);
        if (entry.dirty && !entry.loading) {
            entry.dirty = false;
            entry.loading = true;
            readStatus(folder, this.run).then(value => {
                entry.value = value;
                entry.error = undefined;
                const unassigned = new Set(value.documents.filter(doc => doc.path && doc.entity_id == null)
                    .map(doc => path.resolve(value.root, doc.path)));
                const candidates = candidateSet(value.documents);
                for (const [name, detail] of entry.details) {
                    if (!unassigned.has(name)) {
                        entry.details.delete(name);
                        continue;
                    }
                    detail.dirty = true;
                    // 照会を始めた後に候補が変わった場合、その結果は送信先として使えない。
                    if (detail.candidates !== candidates) {
                        detail.generation += 1;
                        detail.documents = undefined;
                        detail.error = undefined;
                    }
                }
            }, error => {
                entry.error = error.message;
            }).finally(() => {
                entry.loading = false;
                if (this.cache.get(key) === entry) {
                    this.events.fire();
                    this.currentEvents.fire();
                }
            });
        }
        return entry;
    }

    invalidate() {
        const projects = new Set(this.projects().map(folder => folder.uri.toString()));
        for (const [key, entry] of this.cache) {
            if (projects.has(key)) entry.dirty = true;
            else this.cache.delete(key);
        }
    }

    // 旧名の追跡記録や未完了の作成がある場合、実際の送信先は diff の判定に従う。
    effectiveDocument(entry, folder, file, doc, loadDiff) {
        if (doc.entity_id != null) return doc;
        const missing = entry.value.documents.some(other => !other.path && other.entity_id != null
            && other.target === doc.target && other.entity === doc.entity);
        if (!missing && doc.state !== '同期未完了') return doc;
        const key = path.resolve(entry.value.root, doc.path);
        const details = entry.details;
        if (!details.has(key)) details.set(key, { dirty: true, generation: 0 });
        const detail = details.get(key);
        if (detail.dirty && !detail.loading) {
            detail.dirty = false;
            detail.loading = true;
            const generation = detail.generation;
            detail.candidates = candidateSet(entry.value.documents);
            loadDiff(folder, file, []).then(result => {
                if (detail.generation !== generation) return;
                detail.documents = result.documents.map(({ target, entity, entity_id, renamed_from, state, error }) =>
                    ({ target, entity, entity_id, renamed_from, state, error }));
                detail.error = undefined;
            }, error => {
                if (detail.generation === generation) detail.error = error.message;
            }).finally(() => {
                detail.loading = false;
                if (details.get(key) === detail && this.cache.get(folder.uri.toString()) === entry) this.currentEvents.fire();
            });
        }
        if (detail.error) return { ...doc, idMessage: '確認できません', error: detail.error };
        if (!detail.documents) return { ...doc, idMessage: '確認中…' };
        const matches = detail.documents.filter(d => d.target === doc.target && d.entity === doc.entity);
        if (matches.length !== 1) return { ...doc, idMessage: '確認できません', error: '送信先ごとの記事 ID は差分で確認してください。' };
        const [match] = matches;
        // CLI は送信先 ID を決めた後に記事の取得に失敗すると、ID とエラーを両方返す。
        if (match.error && match.entity_id == null) return { ...doc, idMessage: '確認できません', error: match.error };
        return { ...doc, entity_id: match.entity_id, state: match.renamed_from && match.state ? match.state : doc.state,
            error: match.error || doc.error };
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
        const entry = this.status(folder);
        const rows = entry.error ? [messageItem(entry.error)] : [];
        if (!entry.value) return rows.length ? rows : [messageItem('同期状態を取得中…')];
        const { documents, notices } = entry.value;
        rows.push(...notices.map(notice => messageItem(notice)));
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
    }
}

class CurrentDocumentProvider {
    constructor(status, activeFile, events, loadDiff) {
        this.status = status;
        this.activeFile = activeFile;
        this.loadDiff = loadDiff;
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
        let waiting = false;
        let failed = false;
        for (const folder of relevant) {
            const entry = this.status.status(folder);
            if (entry.error) {
                notices.push(messageItem(folder.name + ' — ' + entry.error));
                failed = true;
            }
            if (!entry.value) {
                waiting ||= entry.loading;
                continue;
            }
            const { root, notices: warnings, documents } = entry.value;
            notices.push(...warnings.map(notice => messageItem(notice)));
            for (const doc of documents) {
                if (doc.path && path.relative(realPath, path.resolve(root, doc.path)) === '') {
                    const effective = this.status.effectiveDocument(entry, folder, file, doc, this.loadDiff);
                    matches.push({ folder, doc: effective });
                }
            }
        }
        const name = new vscode.TreeItem(path.basename(file.fsPath));
        name.resourceUri = file;
        name.tooltip = file.fsPath;
        name.command = { command: 'vscode.open', title: '文書を開く', arguments: [file] };
        const rows = [name, ...notices];
        if (waiting) rows.push(messageItem('同期状態を取得中…'));
        if (!matches.length && !waiting && !failed) {
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
