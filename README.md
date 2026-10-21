# <img src="icon.svg" alt="" width="40" height="40" align="middle"> ent9-mibfix

[日本語](README.ja.md)

A script that turns the `v2/` directory of Cisco's official MIB repository,
[cisco/cisco-mibs](https://github.com/cisco/cisco-mibs), into a set of MIBs that
**has all its dependencies and loads without errors**.

Loaded as is, `v2/` produces a large number of errors: some imported modules are
missing, file names do not match module names, and some MIBs have syntax errors.
This is a long-known problem and is still not fixed upstream.

**This repository does not contain any Cisco MIBs.** You clone Cisco's repository
yourself and convert it locally.

This project is not affiliated with or endorsed by Cisco Systems.

## What it fixes

The numbers are for upstream commit `c9ab98c` (2026-09-29).

1. **Dependencies missing from `v2/`** (17 modules added)
   Some modules, such as `TOKEN-RING-RMON-MIB`, exist only in `v1/`. Without them
   `RMON2-MIB` breaks, and so do the 126 modules that import it. The script takes
   them from `v1/`, and takes standard MIBs that Cisco does not ship from
   directories you specify.
2. **OLD-CISCO-\* modules that exist only in `v1/`** (15 modules added)
   These define `enterprises.9.2` (`local`), such as `OLD-CISCO-INTERFACES-MIB`
   and `OLD-CISCO-CPU-MIB`. Current IOS and IOS-XE still answer them: a Catalyst
   3850 returned about 16,000 OIDs there. They are copied from `v1/` as they are.
3. **File names that do not match module names, and duplicate modules**
   (15 files renamed, 13 duplicates resolved)
   Every module is written as `<module name>.my`. When several files define the same
   module, the one with the newest `LAST-UPDATED` is kept.
4. **Missing imports** (37 imports added to 27 modules)
   For example, modules that use `TruthValue` or `Counter32` without importing them.
5. **Errors in the MIB text** (35 fixes)
   Unclosed strings, `END` written twice, trailing commas, misspelled type names,
   duplicate names, and so on.

Every change is logged in `CHANGES.md` (English), `CHANGES.ja.md` (Japanese) and
`changes.json`. Fixes for specific spots that no longer match are logged as
"Fixes not applied", so you can see when Cisco has fixed something upstream.

## Requirements

- Python 3.8 or later (standard library only)
- git
- Standard MIBs that `v2/` imports but Cisco does not ship. The `mibs/` directories
  of Net-SNMP and LibreNMS cover all of them (see below).

On Windows, see [Windows](#windows).

## Usage

```sh
# Cisco MIBs
git clone --depth 1 https://github.com/cisco/cisco-mibs.git

# Standard MIBs: only the mibs/ directory of Net-SNMP and LibreNMS
git clone --depth 1 --filter=blob:none --sparse https://github.com/net-snmp/net-snmp.git
git -C net-snmp sparse-checkout set mibs
git clone --depth 1 --filter=blob:none --sparse https://github.com/librenms/librenms.git
git -C librenms sparse-checkout set --no-cone '/mibs/*' '!/mibs/*/'

# Convert
python3 fix_cisco_mibs.py cisco-mibs out net-snmp/mibs librenms/mibs
```

```
fix_cisco_mibs.py CISCO_MIBS_REPO OUT_DIR [EXTRA_MIB_DIR ...] [-q]
```

| Argument | Meaning |
|---|---|
| `CISCO_MIBS_REPO` | Your clone of cisco/cisco-mibs. It is never modified |
| `OUT_DIR` | Output directory. It must not exist yet |
| `EXTRA_MIB_DIR` | Directories to search for standard MIBs that are not in the repository. May be repeated. `v1/` is searched first, then these in the given order |
| `-q`, `--quiet` | Don't show progress |

The output:

| Path | Contents |
|---|---|
| `OUT_DIR/mibs/` | The fixed MIBs, one module per file, named `<module name>.my` |
| `OUT_DIR/CHANGES.md` | Every change, in English |
| `OUT_DIR/CHANGES.ja.md` | The same, in Japanese |
| `OUT_DIR/changes.json` | The same, machine-readable (`detail` in English, `detail_ja` in Japanese) |

Modules that could not be found are listed under "Unresolved dependencies" in `CHANGES.md`.

The conversion takes a few minutes. Progress goes to stderr: on a terminal, one line
rewritten in place (step and percentage, like `[3/8] adding missing dependencies (pass 2): 47% (790/1667)`);
otherwise, such as when redirected to a log file, one line per step. At the end, the
number of changes of each kind is printed to stdout as JSON.

### Where the standard MIBs come from

At commit `c9ab98c`, these 7 modules are needed from outside the repository.

| Module | Found in |
|---|---|
| RFC1155-SMI, RFC-1215 | Net-SNMP `mibs/` |
| RFC-1212, RFC1271-MIB, DNS-SERVER-MIB, IANA-PRINTER-MIB, IANA-CHARSET-MIB | LibreNMS `mibs/` |

Any other directory that has these modules works too. Only the top level of each
directory is searched, and files are identified by their module name, not by their
file name.

### Using the output with Net-SNMP

```sh
snmpwalk -M +/path/to/out/mibs -m +CISCO-PROCESS-MIB -v2c -c public HOST cpmCPUTotalTable
```

To use it all the time, add this to `~/.snmp/snmp.conf`:

```
mibdirs +/path/to/out/mibs
```

`out/mibs/` also contains modules with the same names as the standard MIBs that come
with Net-SNMP (IF-MIB and others). If both are loaded, `-Pw` may warn about the
duplicates, but they are not errors.

Net-SNMP 5.9 does not accept `_` in names by default, and some Cisco MIBs use it in
enumeration labels (for example `dot11_6ghz` in CISCO-LWAPP-TC-MIB). Add `-Pu`, or
`mibAllowUnderline yes` in `snmp.conf`.

## Extracting only the MIBs a device needs

`out/mibs/` has about 1,700 modules, but a single device needs only a small part of
them. `extract_mibs.py` reads an `snmpwalk` of a real device and lists the MIB files
needed to name its Cisco OIDs, including every module they import.

```sh
# Walk from enterprises, not from enterprises.9 (see below). -On is required
snmpbulkwalk -On -v2c -c public HOST 1.3.6.1.4.1 > walk.txt

python3 extract_mibs.py out/mibs < walk.txt
python3 extract_mibs.py out/mibs --exclude-dir /usr/share/snmp/mibs --archive c3850.zip < walk.txt
python3 extract_mibs.py out/mibs --load-order < walk.txt
python3 extract_mibs.py out/mibs --verify < walk.txt
```

```
extract_mibs.py MIB_DIR [MIB_DIR ...] [-i FILE] [--prefix OID] [--exclude-dir DIR] [--archive FILE] [--load-order] [--no-notifications] [--verify] [-q]
```

| Argument | Meaning |
|---|---|
| `MIB_DIR` | Directory of MIBs, normally `out/mibs`. May be repeated (for example, to add MIBs that Cisco distributes elsewhere). If several define the same module, the first one wins |
| `-i`, `--input FILE` | Read the walk from `FILE` instead of stdin. UTF-8, Latin-1, and UTF-16 with a BOM are accepted |
| `--prefix OID` | Only look at OIDs under this prefix. May be repeated. Default: `1.3.6.1.4.1.9` and `1.3.6.1.4.1.14179` |
| `--exclude-dir DIR` | Leave out modules that already exist in `DIR` or its subdirectories, such as the standard MIBs that come with Net-SNMP. May be repeated |
| `--archive FILE` | Also pack the files into `FILE` (`.zip`, `.tar.gz`, `.tgz` or `.tar`), in a folder named after the file |
| `--load-order` | List the files so that each one comes after the modules it imports, instead of by name. For managers and MIB browsers that load MIBs one at a time. `--archive` stores them in the same order |
| `--no-notifications` | Don't add modules for notifications (see below) |
| `--verify` | Check with Net-SNMP that the listed files are enough (see below). Exits with status 1 if they are not |
| `-q`, `--quiet` | Don't show progress (shown only on a terminal) |

The walk is read from stdin, or from `--input FILE`. The paths of the needed files go to stdout, one per
line. A summary, and the OIDs that no MIB defines, go to stderr.

- **Use `-On`.** Only numeric OIDs are read. If the input has symbolic OIDs
  (`SNMPv2-SMI::enterprises.9...`), the tool tells you to run the walk again with `-On`.
- **Walk from `1.3.6.1.4.1`.** Some Cisco devices also answer under
  `1.3.6.1.4.1.14179` (Airespace, now Cisco's wireless MIBs). For example, the
  Catalyst 3850 has a built-in wireless controller that answers with its default
  settings even when it is not used. A walk of only `1.3.6.1.4.1.9` misses these.
- **OIDs that no MIB defines** are listed by subtree. Some devices answer objects that
  are not in any public MIB, so a few such OIDs are normal. Cisco Small Business
  devices (`1.3.6.1.4.1.9.6.1.101`, CISCOSB-* MIBs) are not covered by cisco-mibs; add
  their MIBs as another `MIB_DIR`.
- **Traps do not appear in a walk.** Most Cisco MIBs define their notifications next
  to the objects they carry, so those MIBs are listed anyway. In addition, a module is
  listed if one of its notifications (NOTIFICATION-TYPE, or TRAP-TYPE of SMIv1) carries
  an object of the walk, even if the walk has none of its own objects. Such a device
  may or may not send that notification: for example, CISCO-WAN-OPTIMIZATION-MIB is
  added because one of its notifications carries a CPU load object of
  CISCO-PROCESS-MIB. `--no-notifications` turns this off. Notifications that carry only
  objects outside `--prefix` (standard MIBs such as IF-MIB), or no objects at all, are
  not found.
- **With `--load-order`, modules that import each other** can't be put in an order
  that suits every tool. They are listed next to each other, sorted by name, with a
  warning on stderr. In the current cisco-mibs this happens only with
  `CISCO-LWAPP-AP-MIB` and `CISCO-LWAPP-DOT11-MIB`. Their order by name, AP first, is
  also the one that works: DOT11 uses objects from AP in its table indexes, while AP
  uses one object from DOT11 only in a notification.

### Checking the result (`--verify`)

`--verify` needs `snmptranslate` (Net-SNMP). It loads only the listed files (plus
`--exclude-dir`) and checks that every OID of the walk gets the same name as with all
of `MIB_DIR` loaded. No second walk is needed. It fails if:

- an OID gets a different name, for example `ciscoMgmt.13.1.4.1.3` instead of
  `ciscoEnvMonFanState`. The result is listed by object, with the name you would get
  instead; or
- Net-SNMP prints a warning with only the listed files that it does not print with all
  of `MIB_DIR`, such as `Cannot find module`.

The notifications of the listed modules that carry an object of the walk are checked
the same way, so traps can be decoded with the listed files too.

OIDs that no MIB defines are skipped. The check runs at the same time as the
extraction, so it adds little time. On a terminal, progress is shown on one line.

### Example results

Walks of two real switches, with upstream commit `c9ab98c`. The percentages are of the
1,669 files in `out/mibs/`. (cisco-mibs itself has 2,796 files, 1,142 in `v1/` and
1,654 in `v2/`, but most of `v1/` are SMIv1 copies of `v2/`, so `out/mibs/` is the fair
base.)

| Device | OIDs in the walk | Files listed | With `--exclude-dir /usr/share/snmp/mibs` |
|---|---|---|---|
| Catalyst 3850 (IOS-XE 03.07.04E) | 62,838 | **146** (8.7%) | **121** (7.2%) |
| Catalyst 2960-X (IOS 15.2(6)E) | 29,088 | **94** (5.6%) | **69** (4.1%) |

`/usr/share/snmp/mibs` is the Net-SNMP 5.9.4 package of Ubuntu 24.04. `--verify`
passes for both. Of the 57 files that the 3850 needs and the 2960-X does not, 22 are
for its built-in wireless controller (AIRESPACE-\*, CISCO-LWAPP-\*).

## Finding which MIB defines an OID

`lookup_mib.py` tells which module and file define an OID or a name. It needs no
Net-SNMP.

```sh
python3 lookup_mib.py out/mibs 1.3.6.1.4.1.9.9.13.1.4.1.3.1
python3 lookup_mib.py out/mibs ifDescr IF-MIB::ifDescr.1 SNMPv2-SMI::enterprises.9.9.13
python3 lookup_mib.py out/mibs ciscoEnvMonFanState --detail
python3 lookup_mib.py out/mibs ciscoEnvMonFanState --deps
python3 lookup_mib.py out/mibs ciscoEnvMonFanState --deps --exclude-dir /usr/share/snmp/mibs
python3 lookup_mib.py out/mibs ciscoEnvMonFanState --deps --load-order
python3 lookup_mib.py out/mibs < oids.txt
python3 lookup_mib.py out/mibs --input oids.txt
```

```
lookup_mib.py MIB_DIR [MIB_DIR ...] [QUERY ... | -i FILE] [--deps [--exclude-dir DIR] [--load-order] | --detail] [-q]
```

| Argument | Meaning |
|---|---|
| `MIB_DIR` | Directory of MIBs, normally `out/mibs`. The leading arguments that are directories are `MIB_DIR`s; the rest are queries |
| `QUERY` | A numeric OID, a name (`ifDescr`), a module-qualified name (`IF-MIB::ifDescr`), or either with an instance (`ifDescr.1`). With no `QUERY`, one is read per line from stdin (the first word of each line, so `snmpwalk -On` output works too) |
| `-i`, `--input FILE` | Read the queries from `FILE` instead of stdin, in the same way. Not together with `QUERY` |
| `--detail` | Also print each definition (`SYNTAX`, `MAX-ACCESS`, `DESCRIPTION` and so on) |
| `--deps` | Instead of the matches, print the files needed to name them, including the modules they import |
| `--exclude-dir DIR` | With `--deps`, leave out modules that already exist in `DIR` or its subdirectories, such as the standard MIBs that come with Net-SNMP. May be repeated |
| `--load-order` | With `--deps`, list the files so that each one comes after the modules it imports, instead of by name |
| `-q`, `--quiet` | Don't show progress (shown only on a terminal) |

Each match is one tab-separated line:

```
1.3.6.1.4.1.9.9.13.1.4.1.3.1	CISCO-ENVMON-MIB::ciscoEnvMonFanState.1	OBJECT-TYPE	out/mibs/CISCO-ENVMON-MIB.my
```

The name is the deepest node that a MIB defines, followed by the arcs below it. A name
or OID defined by several modules (for example `ifDescr` in `IF-MIB` and
`RFC1213-MIB`) gives one line for each. Queries that match nothing go to stderr, and
the exit status is then 1.

### Cache

`extract_mibs.py` and `lookup_mib.py` keep what they read from the MIB files in
`~/.cache/ent9-mibfix/` (or `$XDG_CACHE_HOME/ent9-mibfix/`; on Windows,
`%LOCALAPPDATA%\ent9-mibfix\`). The next run reads only
the files whose size or time changed. Deleting the folder is always safe.

## Windows

### With WSL (recommended)

Everything in this README works as written in
[WSL](https://learn.microsoft.com/windows/wsl/install), including `snmpbulkwalk` and
`--verify`:

```sh
# In PowerShell: wsl --install, then in Ubuntu:
sudo apt install python3 git snmp
```

WSL reads files under `/mnt/c` slowly, so keep the clones and `out/` in your WSL home
directory. To use the results in Windows, write the archive to a Windows folder, for
example `--archive /mnt/c/Users/YOU/Desktop/c3850.zip`, or open
`\\wsl$\Ubuntu\home\YOU` in Explorer.

### Without WSL

With [Python for Windows](https://www.python.org/downloads/windows/), the three
scripts also run in PowerShell or the Command Prompt, with these differences:

- Run them with `py` instead of `python3`, and get the repositories with
  [Git for Windows](https://git-scm.com/download/win) (the same `git` commands work).
- PowerShell has no `<`. Give the walk with `--input FILE` instead, or pipe it.
  A file saved with `>` in Windows PowerShell 5.1 is UTF-16; it is read as is.
- `--verify` does not work, because it needs Net-SNMP's `snmptranslate`. Net-SNMP has
  no recent official build for Windows, so take the walk itself on WSL or a Linux host,
  and copy the file.

```powershell
py fix_cisco_mibs.py cisco-mibs out net-snmp\mibs librenms\mibs
py extract_mibs.py out\mibs --input walk.txt --load-order --archive c3850.zip
py lookup_mib.py out\mibs ciscoEnvMonFanState --deps
```

Checked with Python 3.12 for Windows in Windows PowerShell 5.1 and PowerShell 7: the
output is the same as on Linux, and `fix_cisco_mibs.py` writes byte-identical files.
WSL is still the main supported environment.

## Test results

Tested with upstream commit `c9ab98c`, using Net-SNMP 5.10.pre3 (development version
built from GitHub) and pysmi 1.6.3.

| Check | Before (original `v2/`) | After |
|---|---|---|
| Net-SNMP: errors when loading each module on its own | 135 modules / 1,318 lines | **0** |
| Net-SNMP: errors with `-m ALL` | 96 lines | **0** |
| pysmi: modules that fail to compile | 55 | **0** |
| pysmi: modules not found by name | 25 | 1 (DOCS-PNM-MIB, see below) |
| Label → OID mappings of the original (`snmptranslate -Tz`) | 151,741 labels | **0** lost or changed, 1,356 newly resolved |

The last row checks that the fixes do not change the meaning of any existing OID.
The OLD-CISCO-\* modules (item 2 above) were added after these tests. They were
checked only with Net-SNMP 5.9.4: each loads on its own without errors, and the
`-m ALL` output is unchanged.
Running the script twice on the same input gives identical output.

With Net-SNMP 5.9.4 (the Ubuntu 24.04 package) and `-Pu`, `-m ALL` still prints about
100 lines (262 before the fixes). Almost all of them are in AGENT-CAPABILITIES
statements (`*-CAPABILITY` modules) that name objects or groups missing from the MIB
they describe. These statements describe what an agent supports, and do not affect
name ↔ OID translation. The rest are in MODULE-COMPLIANCE statements
(CISCO-FC-FE-MIB, CISCO-SIP-UA-MIB), a malformed date in a REVISION clause
(DOCS-CABLE-DEVICE-TRAP-MIB), and the missing DOCS-PNM-MIB.

## Judgment calls

For these fixes, the intent could not be determined from the original MIB alone.
They are marked "judgment call" in `CHANGES.md`. None of them changes the OID of an
object that you would poll.

- **`SYNTAX BITS` with no named bits** → `OCTET STRING` (3 objects in CISCO-FIREPOWER-*).
  BITS is sent as OCTET STRING on the wire, so getting values is not affected, but the
  value cannot be shown as bit names.
- **CISCO-ATM-PVCTRAP-EXTN-CAPABILITY**: the AGENT-CAPABILITIES statement had 12 `::=`
  clauses. They were reduced to one.
- **CISCO-FC-FE-MIB**: a REVISION description with no date was joined to the description
  before it. No date was guessed.
- **Duplicate enumeration labels** (such as `byte(0)` to `byte(5)` in CISCO-LWAPP-SI-MIB)
  → the second and later ones are renamed, for example to `byte1`.
- **An AGENT-CAPABILITIES statement with the same name as the MODULE-IDENTITY**
  (3 modules) → `Stmt` is added to the name of the AGENT-CAPABILITIES statement.

## Known limitations

### DOCS-PNM-MIB (CableLabs)

`CISCO-CABLE-PNM-MIB` imports one symbol (`docsPnmCmtsUtscCfgIndex`) from it. It is
distributed by CableLabs and is not in Net-SNMP or LibreNMS. Net-SNMP and pysmi load
`CISCO-CABLE-PNM-MIB` without it, but strict tools report an error. If you need it,
get it from CableLabs and pass its directory as an `EXTRA_MIB_DIR`.

### OID collisions between Cisco MIBs

Some modules use the same OID as another module. Only Cisco knows the correct numbers,
so they are not changed. **Only when both modules are loaded**, translating an OID to a
name may return the name from the other module.

- **MIBs published with placeholder numbers** (`ciscoMgmt.9999` / `.99999`,
  `ciscoExperiment.999`, `ciscoAgentCapability.999` / `.9999` / `.99999`):
  CISCO-AAL5-EXT-MIB, CISCO-ATM-CONN-INFO-MIB, CISCO-CPRI-MIB, CISCO-DS0-CROSS-CONNECT-MIB,
  CISCO-FC-TUNNEL-MIB, CISCO-MPOA-EXT-MIB, CISCO-WAN-ATM-CUG-MIB,
  CISCO-IETF-PPVPN-MPLS-VPN-MIB, CISCO-IETF-VRRP-MIB, CISCO-IF-MONITOR-NOTIF-MIB,
  CISCO-CABLE-DSG-IF-MIB, and many *-CAPABILITY modules
- **Real number collisions**
  - `ciscoMgmt.115`: CISCO-CABLE-PNM-MIB and CISCO-CASA-FA-MIB
  - `ciscoMgmt.510`: CISCO-ERM-MIB and CISCO-VOICE-LMR-MIB
  - `ciscoAgentCapability.102`: CISCO-RFC1406-CAPABILITY and CISCO-RFC1407-CAPABILITY
  - `axisDiagnostics.2`: BASIS-RAS-DISK-MIB and CISCO-MGX82XX-DSX3-BERT-MIB
- **Aliases in standard MIBs (harmless)**: `ccitt.0`, `iso.3`, `ieee.2`,
  `rmonConformance.8`, `intSrv.4`, and others. `transmission.32` is defined under
  different names by RFC1315-MIB (an old version, added from `v1/`) and
  FRAME-RELAY-DTE-MIB.

AWCVX-MIB (Aironet, added from `v1/`) defines an object named `snmpTrapCommunity`,
the same name as one in SNMP-COMMUNITY-MIB. When you use the name, qualify it with the
module, as in `SNMP-COMMUNITY-MIB::snmpTrapCommunity`.

### Other upstream versions

Most fixes are generic, but some target specific spots in specific MIBs. When Cisco
updates the repository, those may no longer match. They are then logged as "Fixes not
applied" in `CHANGES.md`, and new problems are not fixed automatically. Check
`CHANGES.md` after each run.

`smiscan.py` is not a full ASN.1 parser. It only reads as much as is needed to find
module names, imports, definitions and the symbols a module uses.

## Reporting to Cisco

According to the cisco-mibs CONTRIBUTING file, syntax errors and missing imports can
be reported to Cisco TAC together with `smilint` output, and are then filed as bugs.
`CHANGES.md` can serve as material for such reports.

## License

The scripts in this repository are licensed under the [Apache License 2.0](LICENSE).
See also [NOTICE](NOTICE).

The MIBs that the script reads and writes are Cisco's (and, for the standard MIBs,
their respective authors') and are not covered by this license. This repository does
not contain or redistribute them.

## A note to Cisco (and everyone else)

ent9-mibfix exists because many MIBs in cisco/cisco-mibs do not load cleanly as
published. I understand why they are hard to change: there are systems out there that
depend on them as they are, and changing a published MIB always has a cost. So this
project fixes them on the user's side instead. If it ever becomes unnecessary, I'll be
glad.

To everyone else using ent9-mibfix: if it saves you some trouble, buy me an ice cream. 🍦

As for Cisco, you probably get the most out of it, so yours is an It's-It, San
Francisco's own ice cream sandwich since 1928.

*This is a request, not a license term. The scripts are under Apache-2.0, with no extra
conditions.*
