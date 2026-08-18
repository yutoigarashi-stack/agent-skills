# agent-skills

CodexとClaude Codeで共用するAgent Skillsのpublic marketplaceです。

## Plugins

### anki-workflows

- `anki-add-cards`: AnkiConnectで既存構成とカードスタイルを確認し、標準英語ノートタイプへの追加・履歴を保った移行・更新・同期を行う
- `reminders-to-anki`: `reminders-cli`の未完了項目をレビューし、学習用の内容をAnkiへ追加・同期してからReminderを完了する
- `todoist-to-anki`: Todoist公式の`td` CLIでAnki関連プロジェクトの未完了タスクをレビューし、学習用の内容をAnkiへ追加・同期してからタスクを完了する

### git-workflows

- `git-pull-with-stash`: ローカルの変更とステージ状態を保持したまま、現在のブランチをfast-forward-onlyで更新する

### network-diagnostics

- `diagnose-home-network`: macOSでWi-Fi、IPv6、遅延、経路、DNS、スループット、RPMを安全に測定し、ラベル付きJSONの前後比較から自宅回線のボトルネックを切り分ける

## Install

### Codex

```bash
codex plugin marketplace add yutoigarashi-stack/agent-skills --ref main
codex plugin add anki-workflows@yutoigarashi-skills
codex plugin add git-workflows@yutoigarashi-skills
codex plugin add network-diagnostics@yutoigarashi-skills
```

### Claude Code

```bash
claude plugin marketplace add yutoigarashi-stack/agent-skills
claude plugin install anki-workflows@yutoigarashi-skills
claude plugin install git-workflows@yutoigarashi-skills
claude plugin install network-diagnostics@yutoigarashi-skills
```

インストールまたは更新後は、新しいセッションでskillを利用してください。

## Versioning

Claude Code用manifestではversionを省略し、Gitのcommit SHAによる更新検知を利用する。
Codex用manifestのversionはキャッシュ更新の判定に使われるため、pluginの内容を変更するたびに更新する。

## Security

このリポジトリにはAnkiのカード内容、note ID、deck名、ReminderやTodoistタスクの内容、認証情報、ネットワーク計測結果を保存しません。
同梱するskillは、Anki、macOS Reminders、Todoist、Gitリポジトリ、ネットワーク情報を実行時にのみ処理します。
ネットワーク診断はsudoを使わず、SSID、BSSID、MACアドレス、hostname、完全なグローバルIPv6アドレスを結果に保存しません。
