const vscode = require('vscode');
const { spawn } = require('node:child_process');

// 拡張が使う --json と --expect-preview は 1.5.0 で入った。
const minimumVersion = '1.5.0';

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
 * @typedef {{ token?: vscode.CancellationToken, timeout?: number }} RunOptions
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
            const child = spawn(executable(), args, {
                cwd: folder.uri.fsPath,
                env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
                stdio: ['ignore', 'pipe', 'pipe'],
                windowsHide: true,
            });
            let stdout = '';
            let stderr = '';
            /** @type {Error | undefined} */
            let stopped;
            const stop = (/** @type {Error} */ error) => {
                if (stopped) return;
                stopped = error;
                child.kill();
            };
            const timer = timeout > 0 ? setTimeout(() => stop(new Error(
                'esync ' + args[0] + ' が ' + Math.round(timeout / 1000) + ' 秒以内に終わらなかったため中止しました。'
                + '設定 esync.timeoutSeconds で待ち時間を変更できます。')), timeout) : undefined;
            const cancel = token?.onCancellationRequested(() => stop(new vscode.CancellationError()));
            child.stdout.setEncoding('utf8').on('data', data => { stdout += data; });
            child.stderr.setEncoding('utf8').on('data', data => { stderr += data; });
            const finish = () => {
                clearTimeout(timer);
                cancel?.dispose();
            };
            child.on('error', (/** @type {NodeJS.ErrnoException} */ error) => {
                finish();
                reject(error.code === 'ENOENT'
                    ? new Error('esync を起動できません。設定 esync.executable で実行ファイルを指定してください。')
                    : error);
            });
            child.on('close', (code, signal) => {
                finish();
                if (stderr.trim()) log('esync ' + args.join(' ') + '\n' + stderr.trimEnd());
                if (stopped) reject(stopped);
                else if (signal) reject(new Error('esync が中断されました (' + signal + ')'));
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
    const result = await run(folder, ['--version'], { timeout: 30000 });
    const text = (result.stdout + result.stderr).trim();
    const version = result.code === 0 ? parseVersion(text) : undefined;
    if (!version) return 'esync CLI の版を確認できませんでした（' + (text || '出力なし') + '）。';
    if (compareVersions(version, /** @type {number[]} */ (parseVersion(minimumVersion))) < 0) {
        return 'esync CLI ' + version.join('.') + ' は古いため、この拡張では使えません。'
            + minimumVersion + ' 以降に更新してください。';
    }
}

module.exports = { createRunner, checkVersion, parseVersion, compareVersions, minimumVersion };
