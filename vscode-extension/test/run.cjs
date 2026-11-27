// 拡張ホストでテストを実行する。VSCODE_EXECUTABLE があればその VS Code を使い、なければ取得する。
const path = require('node:path');
const { runTests } = require('@vscode/test-electron');

runTests({
    vscodeExecutablePath: process.env.VSCODE_EXECUTABLE || undefined,
    extensionDevelopmentPath: path.resolve(__dirname, '..'),
    extensionTestsPath: path.resolve(__dirname, 'index.cjs'),
    launchArgs: ['--disable-extensions', '--no-sandbox'],
}).catch(error => {
    console.error(error);
    process.exit(1);
});
