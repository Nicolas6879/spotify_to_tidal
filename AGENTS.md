# AGENTS.md

Operating manual for AI agents working in this repo.

## What this is

Fork of spotify2tidal/spotify_to_tidal (AGPL-3.0). Copies Spotify playlists and likes to Tidal, and adds tools to build curated Spotify playlists from a JSON list and fix tracks missing on Tidal. Also ships a Claude Code plugin (`/spotify-tidal:setup`, `/spotify-tidal:playlist`).

## Layout

- `src/spotify_to_tidal/`: CLI (`__main__.py`), logins (`auth.py`), sync/matching (`sync.py`), not-found cache (`cache.py`), Tidal fixes (`tidalapi_patch.py`).
- `tools/verify_tracks.py`: check candidates exist on Spotify (`candidates.json results.json`).
- `tools/build_playlist.py`: create a Spotify playlist from JSON (`--dry-run` creates nothing).
- `tools/tidal_find.py`: search Tidal; `--add <tidal_playlist_id> <track_id> ...` adds tracks.
- `playlists/`: JSON playlists (example: `playlists/covers_cuerdas_saxo_vientos.json`).
- `plugins/spotify-tidal/`: Claude Code plugin; `.claude-plugin/marketplace.json` makes the repo its own marketplace.

## Commands

Run everything from the repo root (tools read `config.yml` from the current directory). Venv python: `.venv/Scripts/python.exe` (Windows) or `.venv/bin/python`.

```bash
python -m venv .venv && <venv python> -m pip install -e .
cp example_config.yml config.yml        # the user fills in credentials themselves
<venv python> tools/build_playlist.py playlists/x.json --dry-run
SPOTIFY_MARKET=CO <venv python> tools/build_playlist.py playlists/x.json   # prints playlist id + URL
<venv python> -m spotify_to_tidal --uri <spotify playlist id>
<venv python> tools/tidal_find.py "artist title"
<venv python> tools/tidal_find.py --add <tidal_playlist_id> <track_id> ...
<venv python> -m spotify_to_tidal --sync-favorites   # ONLY if asked: adds likes on both services
```

`SPOTIFY_MARKET` (default `US`) sets the Spotify search market.

## Playlist JSON

```json
{"name": "...", "description": "...", "public": false,
 "tracks": [{"artist": "...", "title": "..."}, {"uri": "spotify:track:..."}]}
```

## Curated workflow (summary)

Full instructions: `plugins/spotify-tidal/skills/playlist/SKILL.md`. Install guide: `plugins/spotify-tidal/skills/setup/SKILL.md`.

1. Clarify only if vague (include the user's country for `SPOTIFY_MARKET`).
2. Write `playlists/<slug>.json` and dry-run it (read-only): read every `OK`/`NO` line, drop false matches (wrong artist, karaoke, vocals when instrumental, unwanted live/remix), fix misses.
3. Propose the verified list in themed blocks; WAIT for approval. Re-run the dry-run after any change.
4. Create without `--dry-run`.
5. Copy with `--uri`.
6. For each `Could not find the track`, use `tidal_find.py`, propose a replacement, add after the user's OK.
7. Report links, counts, replacements, removals.

## Safety rules

- Never read, print or upload `config.yml`, `.session.yml`, `.cache*` (secrets; all gitignored). Users type credentials into `config.yml` themselves, never in chat.
- Never `git commit` or `git push` unless the user asks.
- Never remove tracks from user libraries or playlists. `--sync-favorites` is add-only but still changes likes: only on request.

## Known issues

- `403 Insufficient client scope`: delete `.cache-<username>` and re-authorize; never pass `market=from_token`.
- `412` on Tidal when adding to long playlists: retried automatically.
- Refresh tokens expire after about 6 months: re-authorize in the browser.
- `KeyError: 'track'` when reading playlists: upstream field rename (Feb 2026), not fixed yet.
- Spotify dev-mode apps: owner needs Premium, max 5 users.
- Hand-added Tidal tracks can be overwritten by a later re-sync.
