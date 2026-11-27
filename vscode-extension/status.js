const vscode = require('vscode');
const fs = require('node:fs/promises');
const path = require('node:path');

/**
 * ツリーの行。文書・プロジェクト・子の行を持たせる。
 * @typedef {vscode.TreeItem & { folder?: any, doc?: any, projectRoot?: any, children?: vscode.TreeItem[] }} Item
 */

/** @param {string} label @param {vscode.TreeItemCollapsibleState} [state] @returns {Item} */
function treeItem(label, state) {
    return new vscode.TreeItem(label, state);
}

function messageItem(message, detail) {
    const item = treeItem(message);
    item.tooltip = detail || message;
    item.iconPath = new vscode.ThemeIcon('info');
    if (message === recoveryNotice) {
        item.command = { command: 'esync.showBackups', title: 'バックアップの一覧を表示' };
        item.tooltip = 'クリックで esync backup list の結果を出力「esync」に表示';
    }
    return item;
}

const recoveryNotice = '復旧待ちのローカル変更があります。esync backup list で確認してください。';

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
    if (recovery_pending) notices.push(recoveryNotice);
    if (result.stderr.trim()) notices.push(result.stderr.trim());
    return { documents, notices, root: await fs.realpath(folder.uri.fsPath) };
}

/** 前回取得した値であることを示す。既に付いていれば重ねない。 @param {string} text */
function previous(text) {
    return text.endsWith('（前回取得）') ? text : text + '（前回取得）';
}

// 改名元の候補（ローカルにない記事）の集合。変わると、文書が引き継ぐ記事 ID も変わりうる。
function candidateSet(documents) {
    return JSON.stringify(documents.filter(doc => !doc.path && doc.entity_id != null)
        .map(doc => [doc.target, doc.entity, doc.entity_id]).sort());
}

// eLabFTW 側の変更を取り込める状態と、どちらかを採用して解決する状態。
const pullStates = ['取得待ち', '競合'];

/**
 * 行のメニューを出し分ける contextValue。push・diff と同じ文書なら esync.document を含む。
 * @param {string} state
 */
function documentContext(state) {
    return ['esync.document', pullStates.includes(state) && 'pull', state === '競合' && 'conflict',
        state === '競合マーカーあり' && 'markers'].filter(Boolean).join(' ');
}

function documentItem(folder, doc) {
    const item = treeItem(doc.file);
    item.description = doc.path || doc.target;
    item.tooltip = [doc.target, doc.entity_id && '#' + doc.entity_id, doc.error,
        ...doc.remote_changes, ...doc.next_actions].filter(Boolean).join('\n');
    if (doc.path) {
        item.resourceUri = vscode.Uri.file(path.resolve(folder.uri.fsPath, doc.path));
        item.command = { command: 'vscode.open', title: '文書を開く', arguments: [item.resourceUri] };
        item.contextValue = documentContext(doc.syncState || doc.state);
        item.folder = folder;
        item.doc = doc;
    }
    return item;
}

function field(label, value) {
    const item = treeItem(label);
    item.description = value;
    item.tooltip = value;
    return item;
}

function detailItems(folder, doc) {
    const source = documentItem(folder, doc);
    const entity = doc.entity === 'items' ? 'リソース' : '実験ノート';
    const action = treeItem('差分を確認');
    action.iconPath = new vscode.ThemeIcon('diff');
    action.command = { command: 'esync.previewFromPanel', title: '差分を確認', arguments: [source] };
    const id = doc.entity_id == null ? '未割り当て' : '#' + doc.entity_id;
    const rows = [
        field('同期状態（保存時点）', doc.state), field('送信先', doc.target + ' / ' + entity),
        field('記事 ID', doc.idMessage || id),
    ];
    if (doc.error) rows.push(messageItem(doc.error));
    rows.push(action);
    const state = doc.syncState || doc.state;
    const command = (label, icon, name, tooltip) => {
        const item = treeItem(label);
        item.iconPath = new vscode.ThemeIcon(icon);
        item.tooltip = tooltip;
        item.command = { command: name, title: label, arguments: [source] };
        rows.push(item);
    };
    if (pullStates.includes(state)) {
        command('eLabFTW の変更を取り込む', 'cloud-download', 'esync.pull',
            'ローカルでも編集している箇所はマージし、重なる箇所は競合マーカーで示します。');
    }
    if (state === '競合') {
        command('ローカルの内容で eLabFTW を上書き', 'arrow-up', 'esync.adoptLocal', 'push --force。eLabFTW 側の変更は失われます。');
    }
    if (state === '競合' || state === '競合マーカーあり') {
        command('eLabFTW の内容でローカルを上書き', 'arrow-down', 'esync.adoptRemote', 'pull --force。ローカルの変更は失われます。');
    }
    if (state === '競合マーカーあり') {
        rows.push(messageItem('競合マーカーを解消して保存してから、差分を確認して push してください。'));
    }
    return rows;
}

/**
 * 差分タブで確認している内容。push される内容とその前提を表示する。
 * @param {{ uri: string, selected: any, warnings: string, remote: boolean }} preview
 */
function previewItem(preview) {
    const doc = preview.selected;
    const group = treeItem('差分タブで確認中の内容', vscode.TreeItemCollapsibleState.Expanded);
    group.description = doc.state;
    const rows = [field('送信先サーバー', doc.server), field('比較の基準（左側）', doc.base_label || '前回の同期')];
    if (doc.renamed_from) rows.push(field('改名前の文書', doc.renamed_from));
    if (doc.local_changed) rows.push(messageItem('画像・添付ファイルまたは設定に変更があります。push で送信されます。'));
    if (doc.remote_changes?.length || preview.remote) {
        const remote = treeItem('eLabFTW 側の変更');
        remote.description = (doc.remote_changes || []).join('、');
        remote.tooltip = '同期状態が「競合」「取得待ち」の文書は、通常の push では送信されません。'
            + 'CLI で eLabFTW 側の変更を取り込むか、どちらかを採用してから差分を開き直してください（README「競合を確認・復旧する」）。';
        remote.iconPath = new vscode.ThemeIcon('warning');
        if (preview.remote) {
            remote.command = { command: 'esync.showRemoteChanges', title: 'eLabFTW 側の変更を表示', arguments: [preview.uri] };
        }
        rows.push(remote);
    }
    if (preview.warnings) rows.push(messageItem(preview.warnings));
    group.children = rows;
    return group;
}

// 状態ごとの表示。並び順は、複数の送信先がある文書で代表として示す優先度（先頭ほど注意が必要）。
const stateStyles = [
    ['競合', 'warning', '!', 'gitDecoration.conflictingResourceForeground'],
    ['競合マーカーあり', 'warning', '!', 'gitDecoration.conflictingResourceForeground'],
    ['リモート削除', 'trash', 'D', 'gitDecoration.deletedResourceForeground'],
    ['ローカル削除', 'trash', 'D', 'gitDecoration.deletedResourceForeground'],
    ['作成結果不明', 'question', '?', 'list.warningForeground'],
    ['同期未完了', 'sync', '!', 'list.warningForeground'],
    ['確認失敗', 'error', '?', 'list.warningForeground'],
    ['基準情報なし', 'question', '?', 'list.warningForeground'],
    ['取得待ち', 'cloud-download', '↓', 'gitDecoration.renamedResourceForeground'],
    ['送信待ち', 'cloud-upload', 'M', 'gitDecoration.modifiedResourceForeground'],
    ['リネーム予定', 'arrow-right', 'R', 'gitDecoration.modifiedResourceForeground'],
    ['未追跡', 'new-file', 'U', 'gitDecoration.untrackedResourceForeground'],
    ['最新', 'check'],
];

/** @param {string[]} states 最も注意が必要な状態とその表示 */
function leadingState(states) {
    const known = stateStyles.find(([state]) => state !== '最新' && states.includes(state));
    // CLI が新しい状態を返しても「最新」に埋もれないよう、未知の状態は「最新」より先に示す。
    const unknown = states.find(state => !stateStyles.some(([style]) => style === state));
    const style = known || (unknown && [unknown, 'question', '?', 'list.warningForeground'])
        || stateStyles.find(([state]) => states.includes(state));
    return style && { state: style[0], icon: style[1], badge: style[2], color: style[3] };
}

/**
 * ステータスバーの表示。送信先がなく、取得の失敗もなければ undefined。
 * 今回取得できた送信先の状態を優先し、取得に失敗したプロジェクトの結果は「前回」として区別する。
 * @param {{ doc: any, stale?: boolean }[]} matches
 * @param {string[]} [errors] 同期状態を取得できなかったプロジェクト
 */
function statusBarView(matches, errors = []) {
    const line = ({ doc, stale }) => doc.target + ' ' + (doc.entity_id == null ? '未割り当て' : '#' + doc.entity_id)
        + ' — ' + doc.state + (stale ? '（前回取得）' : '');
    const fresh = matches.filter(match => !match.stale);
    const lead = leadingState(fresh.map(({ doc }) => doc.state));
    const failure = errors.length ? ['同期状態を取得できなかったプロジェクト:', ...errors] : [];
    if (!lead) {
        const previous = leadingState(matches.map(({ doc }) => doc.state));
        if (!errors.length) {
            return previous && {
                text: '$(sync~spin) esync: ' + previous.state + '（更新中）',
                tooltip: [...matches.map(line), 'クリックで差分を確認'].join('\n'),
            };
        }
        return {
            text: '$(error) esync: 同期状態を取得できません' + (previous ? '（前回: ' + previous.state + '）' : ''),
            tooltip: [...failure, ...matches.map(line)].join('\n'),
        };
    }
    const more = matches.length > 1 ? '（送信先 ' + matches.length + ' 件）' : '';
    const partial = errors.length ? ' $(warning)' : '';
    return {
        text: '$(' + lead.icon + ') esync: ' + lead.state + more + partial,
        tooltip: [...matches.map(line), ...failure, 'クリックで差分を確認'].join('\n'),
    };
}

/**
 * Explorer のバッジ。代表の状態が「最新」なら付けない。未知の状態が代表なら ? を付ける。
 * @param {string[]} states
 * @returns {vscode.FileDecoration | undefined}
 */
function fileDecoration(states) {
    const lead = leadingState(states);
    if (!lead?.badge) return;
    const decoration = new vscode.FileDecoration(lead.badge, 'esync: ' + [...new Set(states)].join('・'),
        new vscode.ThemeColor(lead.color));
    decoration.propagate = false;
    return decoration;
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
            // 取り直している間は前回の失敗を今回の失敗として示さない。今回も失敗したら改めて記録する。
            entry.error = undefined;
            readStatus(folder, this.run).then(value => {
                entry.value = value;
                // Explorer の装飾用。シンボリックリンク経由のパスでも引けるよう、両方の起点で登録する。
                entry.files = new Map();
                for (const doc of value.documents.filter(doc => doc.path)) {
                    for (const base of new Set([value.root, folder.uri.fsPath])) {
                        const name = path.resolve(base, doc.path);
                        entry.files.set(name, [...(entry.files.get(name) || []), doc]);
                    }
                }
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
        const key = path.resolve(entry.value.root, doc.path);
        const details = entry.details;
        // loadDiff がなければ照会せず、最新の同期状態に対して照会し終えた結果だけを使う。
        // 再照会が必要な間（dirty）や照会中は、改名判定が変わりうるので status の結果のまま返す。
        if (!loadDiff) {
            const detail = details.get(key);
            if (!detail || detail.dirty || detail.loading) return doc;
            const resolved = this.resolveDocument(detail, doc);
            return resolved.idMessage ? doc : resolved;
        }
        const missing = entry.value.documents.some(other => !other.path && other.entity_id != null
            && other.target === doc.target && other.entity === doc.entity);
        if (!missing && doc.state !== '同期未完了') return doc;
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
        const resolved = this.resolveDocument(detail, doc);
        // 照会し直している間、前回の照会で得たエラーは今回の結果ではない。前回「確認できません」だった ID 欄は「確認中…」に戻す。
        if ((detail.loading || detail.dirty) && resolved.error && resolved.error !== doc.error) {
            const idMessage = resolved.idMessage === '確認できません' ? '確認中…' : resolved.idMessage;
            return { ...resolved, idMessage, error: previous(resolved.error) };
        }
        return resolved;
    }

    /** 照会結果から記事 ID と状態を補う。確定できなければ idMessage を付ける。 */
    resolveDocument(detail, doc) {
        if (detail.error) return { ...doc, idMessage: '確認できません', error: detail.error };
        if (!detail.documents) return { ...doc, idMessage: '確認中…' };
        const matches = detail.documents.filter(d => d.target === doc.target && d.entity === doc.entity);
        if (matches.length !== 1) return { ...doc, idMessage: '確認できません', error: '送信先ごとの記事 ID は差分で確認してください。' };
        const [match] = matches;
        // CLI は送信先 ID を決めた後に記事の取得に失敗すると、ID とエラーを両方返す。
        if (match.error && match.entity_id == null) return { ...doc, idMessage: '確認できません', error: match.error };
        return { ...doc, entity_id: match.entity_id, state: match.renamed_from && match.state ? match.state : doc.state,
            renamed_from: match.renamed_from, error: match.error || doc.error };
    }

    /**
     * 取得済みの同期状態から、ファイルの状態を返す（取得はしない）。
     * @param {vscode.Uri} uri
     * @returns {string[]}
     */
    statesOf(uri) {
        const states = [];
        for (const entry of this.cache.values()) {
            for (const doc of entry.files?.get(uri.fsPath) || []) {
                states.push(this.effectiveDocument(entry, undefined, uri, doc).state);
            }
        }
        return states;
    }

    /**
     * 開いている文書に対応する送信先を、取得済みの同期状態から探す。未取得のプロジェクトは取得を始める。
     * loadDiff を渡すと、改名中などで記事 ID が未確定の文書は差分を照会して ID を補う。
     * @param {vscode.Uri} file
     * @param {{ uri: vscode.Uri } | undefined} previewFolder 差分タブで確認中のプロジェクト
     * @param {Function} [loadDiff]
     */
    async documentsFor(file, previewFolder, loadDiff) {
        const realPath = await fs.realpath(file.fsPath).catch(() => file.fsPath);
        const folders = this.projects();
        const matches = [];
        const errors = [];
        const warnings = [];
        // docs_dir が他のワークスペースフォルダーを指す場合も、その設定の送信先を表示する。
        const relevant = previewFolder ? folders.filter(f => f.uri.toString() === previewFolder.uri.toString()) : folders;
        let waiting = false;
        for (const folder of relevant) {
            const entry = this.status(folder);
            // 取得に失敗した、または取り直している間の結果は前回のもの。
            const stale = Boolean(entry.error || entry.loading);
            if (entry.error) errors.push(folder.name + ' — ' + entry.error);
            if (!entry.value) {
                waiting ||= entry.loading;
                continue;
            }
            const { root, notices, documents } = entry.value;
            warnings.push(...notices);
            const found = matches.length;
            for (const doc of documents) {
                if (doc.path && path.relative(realPath, path.resolve(root, doc.path)) === '') {
                    matches.push({ folder, stale, doc: this.effectiveDocument(entry, folder, file, doc, loadDiff) });
                }
            }
            // 取り直し中は「取得中」と示す。新しく作った・改名した文書は前回の一覧にないので、同期対象外とも決めない。
            if (entry.loading) waiting = true;
        }
        return { matches, errors, warnings, waiting };
    }

    getTreeItem(item) { return item; }

    async getChildren(item) {
        if (item?.children) return item.children;
        if (item && !item.projectRoot) return [];
        const folders = this.projects();
        if (!item && folders.length > 1) {
            return folders.map(folder => {
                const root = treeItem(folder.name, vscode.TreeItemCollapsibleState.Collapsed);
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
                const group = treeItem(doc.state, vscode.TreeItemCollapsibleState.Expanded);
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
        const { file, folder: previewFolder, preview } = active;
        const { matches, errors, warnings, waiting } = await this.status.documentsFor(file, previewFolder, this.loadDiff);
        const notices = [...errors, ...warnings].map(notice => messageItem(notice));
        const failed = errors.length > 0;
        const name = treeItem(path.basename(file.fsPath));
        name.resourceUri = file;
        name.tooltip = file.fsPath;
        name.command = { command: 'vscode.open', title: '文書を開く', arguments: [file] };
        const rows = [name, ...(preview ? [previewItem(preview)] : []), ...notices];
        if (waiting) rows.push(messageItem('同期状態を取得中…'));
        if (!matches.length && !waiting && !failed) {
            rows.push(messageItem('この文書は同期対象に含まれていません。'));
        }
        for (const { folder, stale, doc: current } of matches) {
            // 取り直し中・取得失敗時の状態やエラーは前回のもの。今回の結果と取り違えないよう明示する。
            const doc = stale ? { ...current, syncState: current.state, state: previous(current.state),
                error: current.error && previous(current.error) } : current;
            const details = detailItems(folder, doc);
            if (matches.length === 1) rows.push(...details);
            else {
                const group = treeItem(doc.target, vscode.TreeItemCollapsibleState.Expanded);
                group.description = folder.name + ' / ' + doc.entity;
                group.children = details;
                rows.push(group);
            }
        }
        return rows;
    }
}

module.exports = { StatusProvider, CurrentDocumentProvider, statusBarView, fileDecoration };
