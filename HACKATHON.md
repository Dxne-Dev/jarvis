# O-jarvis Shell: Meta Global AI Developer Hackathon

O-jarvis existed before the hackathon. This file separates what was built during the build period (October 27 to November 4, 2026, ET) from what was already there.

## Starting point

Everything built before the event is frozen under the tag [`avant-hackathon`](https://github.com/octavebahoun/O-jarvis/tree/avant-hackathon) (October 26, 2026): release v1.1.0 plus one dependency security fix. All hackathon work lands on the `hackathon` branch, whose history cannot be rewritten (no force push, no deletion).

To see exactly what was built during the hackathon:

- on GitHub: [compare `avant-hackathon...hackathon`](https://github.com/octavebahoun/O-jarvis/compare/avant-hackathon...hackathon)
- locally: `git diff avant-hackathon..hackathon`

## Built during the hackathon

Each feature has an issue labeled `hackathon`.

### All-Meta profile ([#47](https://github.com/octavebahoun/O-jarvis/issues/47)), done

- **Meta provider**: Muse Spark 1.3 and Muse Wonder 1.0 through the Meta Model API, with their prices so every call shows its cost.
  - Muse Spark always reasons before answering. Jarvis asks for `minimal` effort on quick tasks (first word in 0.8 s instead of 1.6 s, measured on October 26), and `high` effort on reasoning tasks.
  - The hidden reasoning counts toward the token limit. Jarvis adds headroom, so a short answer (a 30-token title) never comes back empty.
  - Contributor model IDs (`-contributor`), where Meta trains on your requests, are refused.
- **"All Meta" profile in Settings**: Muse Spark answers every task first (chat, voice, reasoning, screen reading), and the other providers stay as fallback. It is off by default and needs a Meta key, and the key has its own "Test" button. A model forced by hand, or a privacy rule (sensitive data stays on a local model), still wins.
- **Speech to text with Muse Voice Transcribe**: with the profile on, each spoken sentence is transcribed by Meta, with a French hint and the keyword "Jarvis". "Local Whisper only" stays local.
- **Muse Spark Open as fallback**: if Muse Spark does not answer, Muse Spark Open, Meta's open-weight model served by Baseten, takes over for every task (text, tools, vision, code review). Real test with Muse Spark made unreachable: a text answer, a tool call and an image read all went through Muse Spark Open, for less than a tenth of a cent each.
- **Relay to Muse Wonder**: Muse Spark does the everyday work. When the same command fails twice in a row (a test still red), the next turn goes to Muse Wonder, Meta's strongest model; a success resets the count. Settings: how many failures before the relay (1 to 3, or off) and which model.
- **The Journal shows it all**: every model call records its provider, model, attempts (fallbacks included), tokens and cost, plus a "relais" line with the reason when the relay is used; every spoken sentence records its transcription model (`muse-voice-transcribe-1.0`). Screen reading follows its own privacy setting: "Online" sends it to Muse Spark, "On this PC" keeps screenshots local.

### Shell mode: Jarvis in your terminal ([#7](https://github.com/octavebahoun/O-jarvis/issues/7)), done

- **`ojarvis-shell`**: run it in any folder of your home. Jarvis works in that folder: it runs commands, reads their output, fixes and runs again, and shows you each command with the end of its output.
- **Every command is classified before it runs** (`engine/src/ojarvis/shell/commands.py`, 182 tests): reading (`ls`, `git status`, `df`) runs at once; any other action waits for your "o"; a destruction (`rm`, `docker prune`, `git reset --hard`) needs "oui" typed in full. Pipes, `;`, `&&`, `$(…)`, heredocs and `xargs` are split and each part is classified; the riskiest one wins.
- **Refused outright**: `sudo` (Jarvis shows the command, you type it), and any command that would read a secrets file (`.env`, `~/.ssh`, keyrings) or search your whole home: its output would reach the model.
- **Safe execution**: no input (a command that asks a question fails instead of hanging), a deadline that stops the whole process group, secret environment variables removed, output truncated (beginning and end kept) and given to the model as data, never as instructions.
- **Validate, then continue**: after you approve a plan, Jarvis reads the results and carries on until the task is done. In shell mode it can chain up to 16 steps per answer; actions still wait for you.
- **Same Jarvis as the app**: the terminal joins the engine the app already runs (same memory, same audit log) through a private connection file (readable by your account only, removed when the engine stops). If the app is closed, the terminal starts its own engine and stops it on exit.
- The command tool exists only in shell mode: the app chat can neither call it nor slip it into a plan.
- **"Passe en mode shell"**: said to the app (or by voice), it opens your own terminal (the system default first, Ptyxis on Ubuntu 26.04) on `ojarvis-shell`, in the folder you asked for, joined to the same Jarvis.
- **No secret leaves through a command**: commands that print a token (`gcloud auth print-access-token`, `gh auth token`, `pass`…) are refused unless used inside a substitution such as `-H "Authorization: Bearer $(…)"`; and Google tokens (even truncated), JWTs, private keys and more are masked before anything reaches the model. Found during a real test on October 26, fixed the same night.

### Coding agents in the shell ([#8](https://github.com/octavebahoun/O-jarvis/issues/8)), done

- **Targeted edits with a diff**: `modifier_fichier` replaces an exact passage; every file change shows its colored diff before you approve. An edit that would not apply goes back to the model, never to you.
- **A second model reviews every change**: Muse Spark writes, Muse Wonder reviews the diff against your request (in "All Meta" mode). Its verdict is shown with the plan and sent back to the author, who can propose a corrected plan. You still decide.
- **Tests until green**: after an edit, Jarvis runs the project's tests and fixes until they pass (real test: a failing `unittest` fixed in one 2-line edit, both tests green).
- **Jarvis looks at its own web page**: `voir_page` opens a page served on your machine in a separate, throwaway Chromium (no cookies, local network blocked), takes a screenshot and has Muse Spark's vision read it, with the HTTP status and console errors. Real test: before the fix the model saw "a broken image icon, no visible button" (white on white); after it, "a blue rounded Commander button, well contrasted", and no console error.
- The shell thinks harder (Muse Spark at `high` effort) since it writes code.
- **Fewer approvals**: answer `t` and that kind of command (`npm install`, `pytest`…) is approved for the rest of the session. Never for a destruction, a code edit, a network or cloud command, inline code, or after reading anything from outside (a web page, GitHub, an MCP server, `curl` output).
- **Budgets**: a request stops cleanly after 12 follow-ups, 20 minutes or $1, and waits for your "continue"; the cost of each request is shown, and the results of the last plan reach the model with your next message.
- **Dead-ends memory**: a fix that failed is noted per project. It never fills the context on its own: Jarvis looks it up when a test fails, so it does not try the same fix twice. Real test over two sessions: it found "returning None failed" and proposed `return 0`, tests green.

### Managing the machine ([#9](https://github.com/octavebahoun/O-jarvis/issues/9)), done

- **"Why is my disk full?"**: Jarvis measures with a 5-minute budget (a home folder takes 2 minutes here) and drills into the biggest folders, deleting nothing. Real test: Downloads 48 GB (27 GB of it Telegram), caches 47 GB, npm 17 GB, Videos 32 GB, trash 9 GB.
- **Jarvis never runs `sudo`**: refused everywhere, even hidden in `bash -c`, a substitution, `xargs` or `find -exec`, plus `sudoedit` and `machinectl shell`.
- **`sudo` in one tap**: Jarvis proposes the command, and the terminal asks "[e]xecute it myself" ("oui" typed in full for a destruction). It runs in your own terminal: `sudo` asks for your password directly, and Jarvis never sees it. The output comes back to Jarvis, masked, as data, and the command goes to the audit log. Real test: `sudo du -sh /var/lib/docker` → "Docker uses 6.8 GB".
- **Machine map**: on the first shell turn, Jarvis records the hardware, system, disks, installed tools, running services and project folders, read-only (names, sizes and versions, never file contents or secrets). It lives in Memory, where you can read, edit or delete it, and reaches the model in shell mode or when a question is about the PC. Real test: "my PC is slow, why?" → "your RAM is saturated: 4.9 GB used of 7.2 GB, 3.6 GB of swap".

### Hardening after a code review (October 27)

A review of the night's commits found 21 problems; each was checked in the code, fixed, and covered by tests. The most serious: `bash -c 'rm -rf ~/projet' --help` was classified as a read, so it would have run without asking, and `find … | xargs cat` could send secret files to the model. Also fixed: results lost when the budget stopped a request, "always" still active after reading GitHub or `curl` output, a non-UTF-8 file losing its accents on edit, and the terminal crashing on a U+2028 character.

## Already there before (not part of the submission)

The desktop app (Tauri + React), the Python engine, voice ("Hey Jarvis"), memory, the permission gate, the browser agent, skills, MCP servers, agents and Telegram. See the [README](./README.md).

## Contributors

- Octave BAHOUN-HOUTOUKPE
