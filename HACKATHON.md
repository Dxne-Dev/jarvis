# O-jarvis Shell: Meta Global AI Developer Hackathon

O-jarvis existed before the hackathon. This file separates what was built during the build period (October 27 to November 4, 2026, ET) from what was already there.

## Starting point

Everything built before the event is frozen under the tag [`avant-hackathon`](https://github.com/octavebahoun/O-jarvis/tree/avant-hackathon) (October 26, 2026): release v1.1.0 plus one dependency security fix. All hackathon work lands on the `hackathon` branch, whose history cannot be rewritten (no force push, no deletion).

To see exactly what was built during the hackathon:

- on GitHub: [compare `avant-hackathon...hackathon`](https://github.com/octavebahoun/O-jarvis/compare/avant-hackathon...hackathon)
- locally: `git diff avant-hackathon..hackathon`

## Built during the hackathon

Each feature has an issue labeled `hackathon`.

### All-Meta profile ([#47](https://github.com/octavebahoun/O-jarvis/issues/47)), in progress

- **Meta provider**: Muse Spark 1.3 and Muse Wonder 1.0 through the Meta Model API, with their prices so every call shows its cost.
  - Muse Spark always reasons before answering. Jarvis asks for `minimal` effort on quick tasks (first word in 0.8 s instead of 1.6 s, measured on October 26), and `high` effort on reasoning tasks.
  - The hidden reasoning counts toward the token limit. Jarvis adds headroom, so a short answer (a 30-token title) never comes back empty.
  - Contributor model IDs (`-contributor`), where Meta trains on your requests, are refused.
- **"All Meta" profile in Settings**: Muse Spark answers every task first (chat, voice, reasoning, screen reading), and the other providers stay as fallback. It is off by default and needs a Meta key, and the key has its own "Test" button. A model forced by hand, or a privacy rule (sensitive data stays on a local model), still wins.
- **Speech to text with Muse Voice Transcribe**: with the profile on, each spoken sentence is transcribed by Meta, with a French hint and the keyword "Jarvis". "Local Whisper only" stays local.

## Already there before (not part of the submission)

The desktop app (Tauri + React), the Python engine, voice ("Hey Jarvis"), memory, the permission gate, the browser agent, skills, MCP servers, agents and Telegram. See the [README](./README.md).

## Contributors

- Octave BAHOUN-HOUTOUKPE
