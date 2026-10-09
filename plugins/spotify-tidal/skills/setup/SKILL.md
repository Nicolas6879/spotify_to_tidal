---
name: setup
description: Guided installation of spotify_to_tidal for non-developers - checks Python and git, clones the repo, creates the virtual environment, helps register a Spotify developer app and logs in to Spotify and Tidal without changing anything. Use when the user says "set up spotify to tidal", "install the spotify tidal tool", "I want to move my playlists to Tidal", "configura spotify_to_tidal", "instala la herramienta de playlists", "quiero pasar mis playlists de Spotify a Tidal". Run as /spotify-tidal:setup.
---

# Set up spotify_to_tidal (guided)

You are guiding a possibly non-technical user. Explain each step in plain language, do the technical work yourself, and ask the user to act only when unavoidable (clicking in a browser, typing secrets into a file). Go one step at a time and wait for confirmation where stated. Answer in the user's language.

## Security rules (always)

- NEVER ask the user to paste the Spotify Client secret, tokens or passwords in the chat.
- NEVER read, print, grep or upload `config.yml`, `.session.yml` or any `.cache*` file.
- NEVER run `git commit` or `git push`. NEVER delete anything from the user's accounts.
- Do NOT run `--sync-favorites` unless the user explicitly asks: it adds songs to the likes/favorites on both services.

## Steps

1. **Check prerequisites.** Run `python --version` (or `python3 --version`) and `git --version`. Python must be 3.10 or newer. If something is missing, explain how to install it for the user's OS (python.org, `winget install Python.Python.3.12`, `brew install python git`, or the distro package manager) and wait.
2. **Locate or clone the repo.**
   - If the env var `SPOTIFY_TO_TIDAL_HOME` is set, use that folder.
   - Else if `~/spotify_to_tidal` exists and contains `pyproject.toml`, use it.
   - Else clone: `git clone https://github.com/Nicolas6879/spotify_to_tidal.git ~/spotify_to_tidal`. Ask before cloning anywhere other than `~/spotify_to_tidal`.
   - All later commands run from this folder (the tools read `config.yml` from the current directory). Call it the repo root.
3. **Virtual environment.** From the repo root: `python -m venv .venv`. The venv Python is `.venv/Scripts/python.exe` on Windows and `.venv/bin/python` elsewhere; call it `<venv python>`. Then `<venv python> -m pip install -e .`.
4. **Config file.** Copy `example_config.yml` to `config.yml` (do not overwrite an existing `config.yml`; do not open it).
5. **Spotify developer app (the user clicks, you guide).** Walk through https://developer.spotify.com/dashboard :
   - Log in, click **Create app**, any name and description.
   - Redirect URI exactly `http://127.0.0.1:8888/callback`, then **Add**.
   - Check **Web API**, save.
   - The app owner needs Spotify **Premium**. A development-mode app allows at most 5 users, so each person should create their own app.
6. **Credentials, by the user.** Tell the user to open `config.yml` themselves in any text editor and fill in `client_id`, `client_secret` and `username` under `spotify`, then save and say "done". Never ask for these values in chat.
7. **Login-only first run (changes nothing).** After "done":
   - `<venv python> tools/build_playlist.py playlists/covers_cuerdas_saxo_vientos.json --dry-run` : the browser opens to authorize Spotify (the user clicks Agree). It only searches and creates nothing.
   - `<venv python> tools/tidal_find.py "test"` : a Tidal login link is printed in the terminal; the user opens it and logs in.
   Wait for the user to confirm each login.
8. **Finish.** Tell the user it is ready and that they can now run `/spotify-tidal:playlist <what you want>`. Mention that Spotify tokens can expire after about 6 months and the browser login simply repeats.

## If something fails

| Symptom | Fix |
|---|---|
| `403 Insufficient client scope` | Delete the `.cache-<username>` file (delete only, do not read it) and re-run to re-authorize. |
| Browser login fails | `redirect_uri` in `config.yml` must equal the dashboard value character for character. |
| `python` not found on Windows | Try `py -3`, or reinstall Python with "Add to PATH". |
