# vibe-speak-proxy

Vibe Speak News 用の YouTube 字幕プロキシ（Cloudflare Workers）。

## セットアップ

```bash
cd workers/vibe-speak-proxy
npm install
```

## ローカル開発

```bash
npm run dev
```

ブラウザまたは curl で確認:

```bash
curl "http://127.0.0.1:8787/?id=dQw4w9WgXcQ"
```

## デプロイ

初回のみ Cloudflare にログイン:

```bash
npx wrangler login
```

デプロイ:

```bash
npm run deploy
# または
npx wrangler deploy
```

デプロイ後の URL 例:

```
https://vibe-speak-proxy.<your-subdomain>.workers.dev/?id=VIDEO_ID
```

## 設定ファイル

| ファイル | 内容 |
|---------|------|
| `wrangler.toml` | Worker 名・エントリポイント・compatibility_date |
| `package.json` | `youtube-transcript` と `wrangler` |
| `src/index.js` | HTTP ルーティング / CORS |
| `src/transcript.js` | `youtube-transcript` で字幕取得・JSON 正規化 |

## レスポンス形式

```json
{
  "language_code": "en",
  "is_generated": true,
  "snippets": [
    { "start": 0.92, "duration": 1.52, "text": "hello and welcome" }
  ]
}
```

## トラブルシューティング

- **`Could not resolve "youtube-transcript"`** → `npm install` を実行
- **認証エラー** → `npx wrangler login`
- **Worker 名を変更したい** → `wrangler.toml` の `name` を編集
