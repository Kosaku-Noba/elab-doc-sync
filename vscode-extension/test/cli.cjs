// esync の実行（打ち切り・取り消し・stderr の記録）と版の確認。実際の CLI の代わりにシェルスクリプトを使う。
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const vscode = require('vscode');
const { createRunner, checkVersion, parseVersion, compareVersions } = require('../cli');

exports.run = async function () {
    assert.deepEqual(parseVersion('esync 1.5.0'), [1, 5, 0]);
    assert.equal(parseVersion('esync unknown'), undefined);
    assert.ok(compareVersions([1, 10, 0], [1, 5, 0]) > 0, 'compare numerically, not as text');
    if (process.platform === 'win32') return;

    const root = await fs.mkdtemp(path.join(os.tmpdir(), 'esync-cli-'));
    try {
        const script = path.join(root, 'esync');
        const folder = { uri: vscode.Uri.file(root) };
        const logs = [];
        let version = '1.5.1';
        const run = createRunner(() => script, line => logs.push(line), () => 1000);
        const write = body => fs.writeFile(script, '#!/bin/sh\n' + body + '\n', { mode: 0o755 });

        await write('echo out; echo warn >&2; exit 1');
        assert.deepEqual(await run(folder, ['status', '--json']), { code: 1, stdout: 'out\n', stderr: 'warn\n' });
        assert.deepEqual(logs, ['esync status --json\nwarn'], 'record stderr in the output channel');
        await run(folder, ['search', '未公開の研究名', '--json']);
        assert.equal(logs.at(-1), 'esync search\nwarn');

        // 終了シグナルを無視する子孫がパイプを持ち続けても、呼び出しはその終了を待たずに戻る。
        await write("echo slow >&2; (trap '' TERM; sleep 3); echo done");
        logs.length = 0;
        let started = Date.now();
        await assert.rejects(run(folder, ['diff']), (/** @type {any} */ error) => error.timedOut
            && /esync diff が 1 秒以内に終わらなかった/.test(error.message), 'stop a command that runs too long');
        assert.ok(Date.now() - started < 2500, 'return on timeout without waiting for child processes');
        assert.deepEqual(logs, ['esync diff\nslow'], 'record stderr received before the timeout');
        await write('sleep 2');
        assert.equal((await run(folder, ['push'], { timeout: 0 })).code, 0, 'timeout 0 waits for the command');

        await write("(trap '' TERM; sleep 3); echo done");
        const source = new vscode.CancellationTokenSource();
        started = Date.now();
        const cancelled = run(folder, ['diff'], { token: source.token, timeout: 0 });
        setTimeout(() => source.cancel(), 200);
        await assert.rejects(cancelled, error => error instanceof vscode.CancellationError);
        assert.ok(Date.now() - started < 1500, 'return on cancel without waiting for child processes');
        await assert.rejects(run(folder, ['diff'], { token: source.token }), error => error instanceof vscode.CancellationError,
            'do not start when already cancelled');

        const versionRun = (folder, args) => {
            assert.deepEqual(args, ['--version']);
            return Promise.resolve({ code: 0, stdout: 'esync ' + version + '\n', stderr: '' });
        };
        assert.equal(await checkVersion(versionRun, folder), undefined);
        version = '1.4.0';
        assert.match(await checkVersion(versionRun, folder), /1\.4\.0 は古い.*1\.5\.1 以降/);
        version = 'dev';
        assert.match(await checkVersion(versionRun, folder), /版を確認できませんでした/);
        const slow = () => Promise.reject(Object.assign(new Error('timeout'), { timedOut: true }));
        const slowMessage = await checkVersion(slow, folder);
        assert.match(slowMessage, /30 秒以内に応答しませんでした.*esync\.executable/);
        assert.doesNotMatch(slowMessage, /timeoutSeconds/, 'the version check ignores esync.timeoutSeconds');

        const missing = createRunner(() => path.join(root, 'missing'), () => {}, () => 0);
        await assert.rejects(missing(folder, ['--version']), /esync\.executable/);
        console.log('PASS: stderr log, timeout and cancel without waiting for children, version check, missing executable');
    } finally {
        await fs.rm(root, { recursive: true, force: true });
    }
};
