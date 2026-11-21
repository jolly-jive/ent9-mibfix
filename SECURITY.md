# Security policy

[日本語](SECURITY.ja.md)

## Supported versions

There are no releases. Only the latest commit on `main` gets fixes.

## What to report

The scripts read MIB directories and walks that may come from someone else, and write
files meant to be handed to others. Please report privately, for example:

- running a command or code from a crafted MIB, walk, or cisco-mibs clone
- a crafted input that makes a script hang, use huge amounts of memory, or crash
- private data that ends up in a file meant for sharing: the archive of `--archive`, or
  the report of `--report` (if a report leaks something, don't attach it anywhere)

Errors in Cisco's MIBs themselves are not security issues; open a normal issue.

## How to report

Use **Report a vulnerability** on the repository's
[Security](https://github.com/jolly-jive/ent9-mibfix/security) tab. Please don't open a
public issue. Include the steps to reproduce, with made-up data instead of real walks.

This is a personal project maintained in spare time, so replies are on a best-effort
basis. Once a fix is pushed, the report can be made public, with credit if you want it.
