# Kiro CLI × Codex 相互レビュー方法論

## 1. 全体像

```
ユーザー
  │ 指示
  ▼
Kiro CLI (開発エージェント)
  │ ① コード変更 + AI_discussions.md に記録
  │ ② git commit
  ▼
post-commit フック
  │ ③ codex exec review --commit HEAD
  ▼
Codex (レビューエージェント)
  │ ④ レビュー結果を AI_discussions.md に追記
  │ ⑤ git commit --amend
  ▼
Kiro CLI
  │ ⑥ Codex の指摘を読み、対応してコミット → ③に戻る
  ▼
指摘事項なし → 次の機能へ
```

2つの AI エージェントが `AI_discussions.md` を共有ノートとして非同期に対話する。人間はこのファイルを読むだけで全経緯を追える。

## 2. 各コンポーネントの役割

### Kiro CLI（開発側）

| 責務 | 詳細 |
|---|---|
| コード実装 | ユーザーの指示に基づきコードを変更する |
| 変更記録 | commit 前に AI_discussions.md へ `[Kiro]` テンプレートで変更内容・判断理由を記録する |
| 指摘対応 | Codex の指摘を読み、修正して再コミットする |
| 打ち切り判断 | Codex が堂々巡りの指摘を出した場合、人間に判断を仰ぐか、理由を明記して打ち切る |

### Codex（レビュー側）

| 責務 | 詳細 |
|---|---|
| 差分レビュー | `codex exec review --commit HEAD` で直前コミットの diff を自動レビューする |
| 指摘記録 | レビュー結果を `[Codex]` テンプレートで AI_discussions.md に追記する |
| 優先度付け | 指摘に P1（高）/ P2（中）/ P3（低）の優先度を付ける |

### AI_discussions.md（共有ノート）

| 役割 | 詳細 |
|---|---|
| 議事録 | 全ての提案・レビュー・対応を時系列で記録する |
| コンテキスト共有 | Kiro と Codex が互いの意図・判断を理解するための唯一の媒体 |
| 監査証跡 | 人間が後から「なぜこの設計になったか」を追跡できる |

## 3. 実装手順

### 3.1 前提条件

```bash
# Codex CLI がインストール済み
codex --version

# git hooks パスを設定
git config core.hooksPath .githooks
```

### 3.2 ファイル構成

```
.githooks/
  post-commit          # Codex 自動レビューフック
AGENT.md               # Kiro/Codex の行動規約・テンプレート定義
AI_discussions.md      # 相互レビューの記録（共有ノート）
```

### 3.3 post-commit フックの実装ポイント

```bash
# 1. 再帰防止（必須）
[ -n "$CODEX_REVIEW_RUNNING" ] && exit 0
export CODEX_REVIEW_RUNNING=1
# --no-verify は post-commit をスキップしないため、
# 環境変数ガードが唯一の再帰防止手段

# 2. Codex 実行
codex exec review --commit HEAD --ephemeral -o "$TMPFILE"
# --ephemeral: セッションファイルを残さない
# -o: 最終メッセージをファイルに出力
# --commit と位置引数プロンプトは併用不可

# 3. 結果の整形・追記
# Codex の出力を AGENT.md のテンプレートに合わせて整形
# AI_discussions.md に追記

# 4. amend
git add AI_discussions.md
git commit --amend --no-edit --no-verify
# post-commit 時点でインデックスは HEAD と一致しているため、
# AI_discussions.md だけ add すれば元のコミット内容は維持される
```

### 3.4 AGENT.md のテンプレート定義

Kiro と Codex が同じフォーマットで記録するためのテンプレートを定義する。

```markdown
## YYYY-MM-DDTHH:MM [Kiro] 変更内容の要約
（変更点テーブル + 所感）

## YYYY-MM-DDTHH:MM [Codex] 対象に対するレビュー
（指摘事項テーブル + 所感）
```

見出しに `[Kiro]` / `[Codex]` を含めることで、誰の発言かが一目でわかる。

## 4. 運用フロー

### 4.1 通常の開発サイクル

```
1. Kiro がコードを変更
2. Kiro が AI_discussions.md に変更内容を記録
3. git commit（Kiro のコード + AI_discussions.md）
4. post-commit フックが Codex レビューを実行
5. Codex の指摘が AI_discussions.md に追記される（amend）
6. Kiro が指摘を確認
   - 指摘あり → 修正して 1 に戻る
   - 指摘なし → 次の機能へ
```

### 4.2 堂々巡りの打ち切り

Codex が矛盾する指摘を繰り返す場合（例: 「更新しろ」→「更新するな」→「更新しろ」）：

1. AI_discussions.md に打ち切り理由を明記する
2. 現在の実装の妥当性を説明する
3. 人間に最終判断を委ねる

### 4.3 `--no-verify` の使い分け

| 場面 | コマンド |
|---|---|
| 通常コミット（レビューあり） | `git commit -m "..."` |
| レビュー不要（ドキュメントのみ等） | `git commit -m "..." --no-verify` |
| amend（フック内部） | `git commit --amend --no-edit --no-verify` |

注意: `--no-verify` は `pre-commit` / `commit-msg` のみスキップする。`post-commit` は常に発火するため、再帰防止は環境変数ガードに依存する。

## 5. 既知の制限と対策

| 制限 | 対策 |
|---|---|
| Codex の出力形式が不安定 | `grep -E '^\- \[P[0-9]\]'` でバレット行を抽出し、マッチしなければ「指摘事項なし」にフォールバック |
| `--commit` とプロンプト引数の併用不可 | カスタムプロンプトが必要な場合は `codex exec` + stdin 経由で渡す |
| Codex が利用不可（API エラー等） | フック内で `exit 0` し、commit 自体は成功させる |
| amend で元のファイルが消える | post-commit 時点でインデックスは HEAD と一致しているため、`git add AI_discussions.md` だけで十分（`xargs git add` は不要） |
| Codex が堂々巡りする | 人間が打ち切り判断。AI_discussions.md に理由を記録 |

## 6. 他プロジェクトへの導入手順

```bash
# 1. AGENT.md を作成（テンプレート定義）
# 2. AI_discussions.md を作成（空ファイル）
touch AI_discussions.md

# 3. post-commit フックを配置
mkdir -p .githooks
cp /path/to/post-commit .githooks/post-commit
chmod +x .githooks/post-commit
cp .githooks/post-commit .git/hooks/post-commit

# 4. git hooks パスを設定
git config core.hooksPath .githooks

# 5. Codex CLI の認証
codex login

# 6. 動作確認
echo "test" >> README.md
git add README.md AI_discussions.md
git commit -m "test: 相互レビュー動作確認"
# → Codex レビューが実行され、AI_discussions.md に追記される
```

## 7. 設計思想

- **非同期対話**: Kiro と Codex は直接通信しない。AI_discussions.md を介して非同期に対話する
- **人間が最終権限**: AI 同士の議論が収束しない場合、人間が判断する
- **commit = 発言**: 各 commit が「提案」であり、Codex のレビューが「応答」。git 履歴がそのまま議論の履歴になる
- **フォールバック優先**: Codex が動かなくても開発は止まらない。レビューは付加価値であり、ブロッカーにしない
