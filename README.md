# agent-skills

CodexとClaude Codeで共用するAgent Skillsのpublic marketplaceです。

## Plugins

### anki-workflows

- `anki-add-cards`: AnkiConnectで既存構成を確認し、重複を避けて任意言語・任意分野のカードを追加して同期する
- `reminders-to-anki`: `reminders-cli`の未完了項目をレビューし、学習用の内容をAnkiへ追加・同期してからReminderを完了する

## Install

### Codex

```bash
codex plugin marketplace add yutoigarashi-stack/agent-skills --ref main
codex plugin add anki-workflows@yutoigarashi-skills
```

### Claude Code

```bash
claude plugin marketplace add yutoigarashi-stack/agent-skills
claude plugin install anki-workflows@yutoigarashi-skills
```

インストールまたは更新後は、新しいセッションでskillを利用してください。

## Security

このリポジトリにはAnkiのカード内容、note ID、deck名、Reminderの内容、認証情報を保存しません。
同梱するskillは、AnkiとmacOS Remindersのデータをローカルで処理します。
