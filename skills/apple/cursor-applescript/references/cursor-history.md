# Reading Cursor Composer/Agent history from local SQLite

Cursor stores all Composer and Agent conversations on disk in SQLite databases.
Use this reference to retrieve what Cursor has been working on — useful when the
user asks "what did Cursor just do?" or "latest task in window X".

## Database locations

### Global data (all workspaces)

```
~/Library/Application Support/Cursor/User/globalStorage/state.vscdb
```

Contains `ItemTable` and `cursorDiskKV` tables. Key entries:

| Key | Content |
|-----|---------|
| `composer.composerHeaders` | JSON blob with `allComposers` array listing every Composer session across all workspaces. Each entry has `composerId`, `name`, `lastUpdatedAt`, `createdAt`, `subtitle` (edited files summary), `totalLinesAdded`, `filesChangedCount`, `trackedGitRepos`. |
| `cursorDiskKV` table, `bubbleId:<composerId>:<bubbleId>` keys | Individual chat turns within a composer session. |
| `cursorDiskKV` table, `agentKv:blob:<hash>` keys | Agent conversation data (blobs). |

### Per-workspace data

```
~/Library/Application Support/Cursor/User/workspaceStorage/<workspaceHash>/state.vscdb
```

Each workspace hash maps to a project folder via `workspace.json`. Key entries:

| Key | Content |
|-----|---------|
| `composer.composerData` | Lightweight metadata for the workspace's Composer sessions: `selectedComposerIds`, `lastFocusedComposerIds`. |
| `aiService.generations` | JSON array of all AI generation requests in this workspace. Each entry: `unixMs`, `generationUUID`, `type` (usually `"composer"`), `textDescription` (the user's prompt text). |
| `workbench.panel.composerChatViewPane.<uuid>` | Per-session view state. |

## Finding the workspace hash for a project

```bash
for dir in ~/Library/Application\ Support/Cursor/User/workspaceStorage/*/; do
  hash=$(basename "$dir")
  json=$(cat "$dir/workspace.json" 2>/dev/null)
  if echo "$json" | grep -q "startell"; then
    echo "$hash -> $json"
  fi
done
```

## Query: List all Composer sessions (global, recent first)

```bash
sqlite3 "$HOME/Library/Application Support/Cursor/User/globalStorage/state.vscdb" \
  "SELECT value FROM ItemTable WHERE key='composer.composerHeaders';" \
  | python3 -c '
import sys, json, datetime
data = json.loads(sys.stdin.buffer.read())
composers = sorted(data.get("allComposers", []),
                   key=lambda x: x.get("lastUpdatedAt", 0), reverse=True)
for c in composers[:20]:
    ts = c.get("lastUpdatedAt", 0)
    dt = datetime.datetime.fromtimestamp(ts/1000)
    name = c.get("name", "(no name)")
    cid = c.get("composerId", "")[:12]
    subtitle = c.get("subtitle", "")
    files = c.get("filesChangedCount", 0)
    lines = c.get("totalLinesAdded", 0)
    print(f"[{dt:%m-%d %H:%M}] {name}  ({files} files, +{lines} lines)")
    if subtitle:
        print(f"  → {subtitle}")
'
```

## Query: Get recent AI prompts in a specific workspace

```bash
WORKSPACE_HASH="319a51387ff5e938fe9e395c32271bc7"  # replace with target hash
DB="$HOME/Library/Application Support/Cursor/User/workspaceStorage/${WORKSPACE_HASH}/state.vscdb"

sqlite3 "$DB" "SELECT value FROM ItemTable WHERE key='aiService.generations';" \
  | python3 -c '
import sys, json, datetime
data = json.loads(sys.stdin.buffer.read())
recent = sorted(data, key=lambda x: x.get("unixMs", 0), reverse=True)[:10]
for g in recent:
    ts = g.get("unixMs", 0)
    dt = datetime.datetime.fromtimestamp(ts/1000)
    gtype = g.get("type", "")
    desc = g.get("textDescription", "")[:160]
    print(f"[{dt:%m-%d %H:%M:%S}] [{gtype}] {desc}")
'
```

## Query: Get the full composer header detail (last updated time, files, repo)

```bash
sqlite3 "$DB" "SELECT value FROM ItemTable WHERE key='composer.composerHeaders';" \
  | python3 -c '
import sys, json
data = json.loads(sys.stdin.buffer.read())
composers = data.get("allComposers", [])
recent = sorted(composers, key=lambda x: x.get("lastUpdatedAt", 0), reverse=True)
for c in recent[:5]:
    print(json.dumps(c, indent=2, ensure_ascii=False)[:1200])
'
```

## Timestamp note

Cursor stores timestamps as Unix milliseconds (13 digits). If a timestamp shows
as `1970-01-01` or `2001-01-01`, it may be a default/sentinel value meaning
"not set" — filter those out when sorting.

## Limitations

- Only the `textDescription` field (the user's prompt) is readable from
  `aiService.generations`. The AI's responses are stored in bubble blobs
  (`bubbleId:<id>` keys) which are serialized binary — not easily decoded.
- `cursorDiskKV` values are blob-encoded and may not be human-readable JSON.
- Only works when Cursor has written data to disk (close to real-time, but
  in-flight conversations may not be flushed).
