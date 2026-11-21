# Contributing

[日本語](CONTRIBUTING.ja.md)

Thanks for your interest. Issues and pull requests are welcome, in English or Japanese.

## Issues

Use the **Problem report** form. It asks for the device, the commits of cisco-mibs and
ent9-mibfix, and the command you ran.

**Don't paste a raw snmpwalk.** Its values and its OIDs hold host names, addresses and
serial numbers. Attach the file that `extract_mibs.py ... --report FILE` writes instead,
after looking through it (see "Sharing a walk in an issue" in the [README](README.md)).
Don't paste the list of files either: the paths contain your user name.

A security problem goes through [SECURITY.md](SECURITY.md), not an issue.

Errors in Cisco's MIBs that this tool does not fix yet are welcome here. To get them
fixed upstream, see "Reporting to Cisco" in the README: cisco/cisco-mibs takes no issues.

## Pull requests

- Python 3.8 or later, standard library only.
- Run the tests: `python3 -m unittest discover tests`. GitHub Actions runs them on Linux
  and Windows. Add a test for a new behavior; the tests make up small MIBs and walks
  instead of using real ones.
- GitHub Actions also runs `ruff check .` (rules in `ruff.toml`, version in
  `.github/lint-requirements.txt`). If you have ruff, run it before you push.
- If you change `fix_cisco_mibs.py` or `smiscan.py`, compare the output with
  `tools/check_fix_output.py` (see "Development" in the README) and say in the pull
  request what changed.
- Code comments and messages are in English. Documentation is in both English and
  Japanese (`README.md` and `README.ja.md`); if you can write only one, say so and the
  other will be added.
- Never commit MIB files, walks, or anything from a real network. The MIBs are Cisco's;
  `cisco-mibs/`, `out/` and `samples/` are ignored by git for this reason.

Contributions are licensed under the [Apache License 2.0](LICENSE), like the rest of
the project.
