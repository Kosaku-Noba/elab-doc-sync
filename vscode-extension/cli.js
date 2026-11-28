const vscode = require('vscode');
const { spawn } = require('node:child_process');

// 記事の取り込み先の照合と一括取得の競合チェックを使う。
const minimumVersion = '1.5.1';
// 版の確認は esync.timeoutSeconds によらず、この時間で打ち切る。
const versionTimeout = 30000;

/** @param {string} text */
function parseVersion(text) {
    const match = /(\d+)\.(\d+)\.(\d+)/.exec(text);
    return match ? match.slice(1).map(Number) : undefined;
}

/** @param {number[]} a @param {number[]} b */
function compareVersions(a, b) {
    for (let i = 0; i < 3; i++) {
        if (a[i] !== b[i]) return a[i] - b[i];
    }
    return 0;
}

/**
 * @typedef {{ code: number | null, stdout: string, stderr: string }} RunResult
 * @typedef {{ token?: vscode.CancellationToken, timeout?: number, input?: string }} RunOptions
 */

/**
 * esync を実行する関数を作る。
 * timeout はミリ秒で、0 なら打ち切らない。送信中の push を途中で止めないよう、push では 0 を渡す。
 * @param {() => string} executable
 * @param {(line: string) => void} log
 * @param {() => number} defaultTimeout
 */
function createRunner(executable, log, defaultTimeout) {
    /**
     * @param {{ uri: vscode.Uri }} folder
     * @param {string[]} args
     * @param {RunOptions} [options]
     * @returns {Promise<RunResult>}
     */
    return function run(folder, args, options = {}) {
        const { token, timeout = defaultTimeout() } = options;
        return new Promise((resolve, reject) => {
            if (token?.isCancellationRequested) {
                reject(new vscode.CancellationError());
                return;
            }
            // POSIX では新しいプロセスグループで起動し、止めるときはそのグループに終了シグナルを送る。
            const group = process.platform !== 'win32';
            const child = spawn(executable(), args, {
                cwd: folder.uri.fsPath,
                env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
                stdio: [options.input === undefined ? 'ignore' : 'pipe', 'pipe', 'pipe'],
                windowsHide: true,
                detached: group,
            });
            let stdout = '';
            let stderr = '';
            let settled = false;
            const finish = () => {
                settled = true;
                clearTimeout(timer);
                cancel?.dispose();
                if (stderr.trim()) {
                    const command = ['metadata', 'tag', 'new', 'search'].includes(args[0]) ? args[0] : args.join(' ');
                    log('esync ' + command + '\n' + stderr.trimEnd());
                }
            };
            // 子孫がパイプを持ったまま残っても、終了を待たずに呼び出し元へ返す。
            const stop = (/** @type {Error} */ error) => {
                if (settled) return;
                finish();
                try {
                    if (group && child.pid) process.kill(-child.pid);
                    else child.kill();
                } catch {
                    child.kill();
                }
                child.stdout.destroy();
                child.stderr.destroy();
                reject(error);
            };
            const timer = timeout > 0 ? setTimeout(() => stop(Object.assign(new Error(
                'esync ' + args[0] + ' が ' + Math.round(timeout / 1000) + ' 秒以内に終わらなかったため中止しました。'
                + '設定 esync.timeoutSeconds で待ち時間を変更できます。'), { timedOut: true })), timeout) : undefined;
            const cancel = token?.onCancellationRequested(() => stop(new vscode.CancellationError()));
            child.stdout.setEncoding('utf8').on('data', data => { stdout += data; });
            child.stderr.setEncoding('utf8').on('data', data => { stderr += data; });
            child.on('error', (/** @type {NodeJS.ErrnoException} */ error) => {
                if (settled) return;
                finish();
                reject(error.code === 'ENOENT'
                    ? new Error('esync を起動できません。設定 esync.executable で実行ファイルを指定してください。')
                    : error);
            });
            if (options.input !== undefined) {
                child.stdin.on('error', (/** @type {NodeJS.ErrnoException} */ error) => {
                    if (error.code !== 'EPIPE') stop(error);
                });
                child.stdin.end(options.input, 'utf8');
            }
            child.on('close', (code, signal) => {
                if (settled) return;
                finish();
                if (signal) reject(new Error('esync が中断されました (' + signal + ')'));
                else resolve({ code, stdout, stderr });
            });
        });
    };
}

/**
 * CLI の版を確かめ、古ければ理由を返す。問題がなければ undefined。
 * @param {ReturnType<typeof createRunner>} run
 * @param {{ uri: vscode.Uri }} folder
 */
async function checkVersion(run, folder) {
    let result;
    try {
        result = await run(folder, ['--version'], { timeout: versionTimeout });
    } catch (error) {
        if (!error.timedOut) throw error;
        return 'esync --version が ' + versionTimeout / 1000 + ' 秒以内に応答しませんでした。'
            + '設定 esync.executable の実行ファイルをターミナルで `--version` を付けて実行し、応答するか確認してください。';
    }
    const text = (result.stdout + result.stderr).trim();
    const version = result.code === 0 ? parseVersion(text) : undefined;
    if (!version) return 'esync CLI の版を確認できませんでした（' + (text || '出力なし') + '）。';
    if (compareVersions(version, /** @type {number[]} */ (parseVersion(minimumVersion))) < 0) {
        return 'esync CLI ' + version.join('.') + ' は古いため、この拡張では使えません。'
            + minimumVersion + ' 以降に更新してください。';
    }
}

module.exports = { createRunner, checkVersion, parseVersion, compareVersions, minimumVersion };
