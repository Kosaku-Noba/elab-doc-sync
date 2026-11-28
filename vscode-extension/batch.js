// 同期一覧で選んだ文書だけを、確認時の送信先と方向で順に処理する。
const vscode = require('vscode');
const path = require('node:path');

const { sendStates, assetActions } = require('./status');

async function batchSync(folder, run, loadDiff, confirm, refresh, output) {
    if (!folder) return;
    async function json(args, write = false) {
        const result = await run(folder, args, write ? { timeout: 0 } : {});
        if (result.code) throw new Error(result.stderr.trim() || '同期結果を確認できません。');
        return JSON.parse(result.stdout);
    }
    function clean(file) {
        if (vscode.workspace.textDocuments.some(d => d.uri.toString() === file.toString() && d.isDirty)) {
            throw new Error(path.basename(file.fsPath) + ' に未保存の編集があります。');
        }
    }
    const { documents } = await json(['status', '--json']);
    /** @type {(vscode.QuickPickItem & { doc: any, pull: boolean })[]} */
    const choices = documents.filter(doc => doc.path && doc.selector && !doc.error &&
        (sendStates.includes(doc.state) || doc.state === '取得待ち')).map(doc => {
        const pull = doc.state === '取得待ち';
        return { label: (pull ? '$(cloud-download) ' : '$(cloud-upload) ') + doc.path,
            description: (pull ? '取得' : '送信') + ' · ' + doc.target, detail: doc.state + ' · ' + (doc.entity === 'items' ? 'リソース' : '実験ノート')
                + (doc.entity_id == null ? '' : ' #' + doc.entity_id), doc, pull };
    });
    if (!choices.length) {
        await vscode.window.showInformationMessage('まとめて送信・取得できる文書はありません。競合は個別に解消してください。');
        return;
    }
    const selected = await vscode.window.showQuickPick(choices, { canPickMany: true,
        placeHolder: '送信・取得する文書にチェックを付けてください（競合は個別に解決）' });
    if (!selected?.length) return;
    const plans = [];
    for (const { doc, pull } of selected) {
        const file = vscode.Uri.file(path.resolve(folder.uri.fsPath, doc.path));
        clean(file);
        const target = '--target=' + doc.selector;
        const { documents: diff } = await loadDiff(folder, file, [target]);
        const [review] = diff;
        // 未追跡の文書は、diff で既存記事の改名と判明することがある。
        const rename = doc.state === '未追跡' && review?.state === 'リネーム予定';
        if (diff.length !== 1 || review.error || review.selector !== doc.selector || review.entity !== doc.entity
                || (!rename && (review.state !== doc.state || review.entity_id !== doc.entity_id)) || !review.preview_token) {
            throw new Error(doc.path + ' の同期状態が変わりました。個別に差分を確認してください。');
        }
        const args = pull ? ['pull', '--json', '--incoming-only', target, '--expect-id=' + review.entity_id,
            '--expect-entity=' + review.entity, '--expect-server=' + review.server] : ['push', target, '--expect-preview', review.preview_token];
        let dest = doc.path;
        if (pull) {
            const preview = await json([...args, '--dry-run', '--', file.fsPath]);
            const incoming = preview.documents.find(d => d.entity_id === review.entity_id && d.result === 'would_pull');
            if (!incoming?.path) throw new Error(doc.path + ' の取り込み予定が変わりました。');
            dest = incoming.path;
            args.push('--expect-path=' + dest);
        }
        const article = review.server + ' / ' + doc.selector + ' / ' + (doc.entity === 'items' ? 'リソース' : '実験ノート')
            + (review.entity_id == null ? '（新規作成）' : ' #' + review.entity_id);
        const label = pull ? '取得　' + article + ' → ' + dest : '送信　' + doc.path + ' → ' + article;
        const assets = pull ? [] : (review.asset_changes || []);
        const missing = assets.find(a => a.action === 'missing');
        if (missing) throw new Error(doc.path + ' から参照するファイルが見つかりません: ' + missing.path);
        const detail = [label, ...assets.map(a => '　' + (assetActions[a.action] || a.action) + '　' + a.path)].join('\n');
        plans.push({ detail, pull, file, dest: vscode.Uri.file(path.resolve(folder.uri.fsPath, dest)), args, label, review, target });
    }
    const pulls = plans.filter(p => p.pull).length;
    const counts = '送信 ' + (plans.length - pulls) + ' 件・取得 ' + pulls + ' 件';
    if (!await confirm(counts + '\n\n' + plans.map(p => p.detail).join('\n'), 'まとめて実行')) return;
    let completed = 0;
    try {
        for (const plan of plans) {
            const latest = await loadDiff(folder, plan.file, [plan.target]);
            clean(plan.file);
            clean(plan.dest);
            if (latest.documents.length !== 1 || JSON.stringify(latest.documents[0]) !== JSON.stringify(plan.review)) {
                throw new Error('確認後に変更がありました。差分を確認し直してください。');
            }
            const args = [...plan.args, '--', plan.file.fsPath];
            if (plan.pull) {
                const data = await json(args, true);
                if (data.documents.length !== 1 || data.documents[0].result !== 'pulled' || data.documents[0].conflict) {
                    throw new Error('取り込み結果を個別に確認してください。');
                }
            } else {
                const result = await run(folder, args, { timeout: 0 });
                if (result.stdout.trim()) output.appendLine(result.stdout.trimEnd());
                if (result.code) throw new Error(result.stderr.trim() || '送信に失敗しました。');
            }
            output.appendLine('完了　' + plan.label);
            completed++;
        }
        vscode.window.showInformationMessage(counts + ' が完了しました。');
    } catch (error) {
        const message = completed + '/' + plans.length + ' 件完了。' + plans[completed].label + ' で停止しました。' + error.message;
        output.appendLine(message);
        throw new Error(message);
    } finally {
        refresh();
    }
}

module.exports = { batchSync };
