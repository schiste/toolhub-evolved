<!-- Reviewed release notes. tools/generate_marketing_changelog.py drafts these when a changelog provider is configured. -->
<!-- None was available on this push, so these were written by hand and checked against the commits. -->
<!-- Release id: traces-left-behind -->
<!-- Release title: Traces Left Behind -->
<!-- Source range: e647ce66..17f0b52f (3 commits) -->

# What's New for Users

- The repository scanner now notes whether a tool's code shows traces of a coding assistant: a `CLAUDE.md` or `AGENTS.md` file, a `.codex` or `.claude` directory, a commit signed by Claude Code or Codex.
- Only traces the tooling left behind itself count. Nothing is guessed from how the code reads, and no file's contents are interpreted — a path and a commit signature are the whole of the evidence.
- Where none are found, what is recorded is "not known", never "no". An assistant driven from an editor commits nothing about itself, so a blank here would be misread as proof that a person typed every line.
- The vendor is filled in only when the evidence names one and does not disagree with itself — a bare `AGENTS.md` names none, and a repository configured for two assistants is recorded as both rather than as either. The model is filled in only where it is actually written down, which today means Claude Code's commit trailer.
- Even a clear answer says a tool was built _with_ an assistant, not _by_ one. A configuration file proves the tooling was set up; it does not measure how much of the code came through it.
- None of this scores anything. It counts neither for nor against a tool's health grade, and no tool page displays it yet.
- Every repository analyzed before this existed is being read once more, so the record covers the catalogue rather than only the tools scanned from here on.
