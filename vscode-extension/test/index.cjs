// 拡張ホストで各テストを順に実行する。
exports.run = async function () {
    for (const name of ['panel.cjs', 'cli.cjs', 'commands.cjs', 'articles.cjs']) {
        await require('./' + name).run();
    }
};
