# Repository instructions

## Plugin versioning

### Claude Code

- Gitで配布するpluginでは、`.claude-plugin/plugin.json` と
  `.claude-plugin/marketplace.json` のplugin entryに `version` を設定しない。
- versionを省略してGitのcommit SHAによる更新検知を利用する。意図的に特定版へ
  固定する要件がない限り、versionを再導入しない。
- 第三者marketplaceを自動更新する環境では `autoUpdate: true` を設定する。
- 手動セットアップではmarketplaceを更新してから、対象pluginに
  `claude plugin update <plugin>@yutoigarashi-skills --scope user` を実行する。

### Codex

- `.codex-plugin/plugin.json` の `version` は必須とし、strict semverで管理する。
- skill、manifest、その他Codexが読み込むplugin内容を変更したら、同じPRで
  versionを更新する。
- バグ修正や既存skillの変更ではpatch、新しいskillや後方互換な機能追加では
  minor、破壊的変更ではmajorを上げる。
- marketplace更新後は
  `codex plugin add <plugin>@yutoigarashi-skills` を再実行し、更新版をcacheへ
  反映する。

## Validation

- Claude Code側は `claude plugin validate .` でmarketplace全体を検証する。
- Codex側はplugin validatorで変更対象pluginを検証する。
- JSON validationと `git diff --check` を実行する。
- インストールまたは更新後は、新しいセッションでpluginを確認する。
