# pbo_packer — CLI guide for agents

`pbo_packer.exe` is a native DayZ PBO packer / analyzer. No config files, no
network, no state. Everything is flags. Exit codes are the contract:
**`0` = success, `1` = runtime error, `2` = bad arguments.** Always check the
exit code, not stdout text.

## Invocation

```
pbo_packer <command> [flags]
```

Two commands: `pack`, `analyze`. Running with **no arguments** drops into an
interactive prompt — never do that from an agent; always pass a command and
flags so the process stays non-interactive.

### `pack` — folder → .pbo

```
pbo_packer pack -s <source_dir> -o <output.pbo> [flags]
```

| Flag | Meaning |
|------|---------|
| `-s, --source <dir>` | source folder (required) |
| `-o, --output <file>` | output `.pbo` path (required) |
| `-p, --prefix <name>` | override `$PBOPREFIX$` |
| `-c, --compress` | per-file LZSS compression |
| `-t, --threads <N>` | parallel body emit; `0` = sequential (default) |
| `--no-checksum` | write zero SHA1 footer (faster; dev only) |
| `-v, --verbose` | per-phase wall-time breakdown |

Prints `prefix`, `files`, `bytes`, `elapsed`, `throughput`. Watch stdout for
`WARNING:` lines — a PBO with **no config.cpp/config.bin at root** will not
load in-engine, and PBOs over 4 GiB are rejected by the 32-bit-offset engine.
Neither warning changes the exit code, so grep for `WARNING`.

### `analyze` — inspect an existing .pbo

```
pbo_packer analyze -i <pbo_file>
```

Dumps size, whether the SHA1 footer is valid, all `$PBO$` properties, and every
file entry (`data_size`, mime type, name). Use this to verify a `pack` result.
`sha1 footer valid: NO` means the PBO is corrupt or was hand-edited.

## Agent recipes

```bash
# Pack a mod addon, compressed, 8 threads, fail loudly
pbo_packer pack -s ./MyMod/Addons/gear -o ./out/gear.pbo -c -t 8 || echo "FAILED $?"

# Round-trip check: pack then confirm it reads back clean
pbo_packer pack -s ./src/data -o /tmp/data.pbo && pbo_packer analyze -i /tmp/data.pbo
```

## Gotchas

- Paths with spaces: quote them. The binary also strips surrounding quotes from
  interactive input, but from a shell just quote normally.
- `--no-checksum` produces a PBO the engine loads but that fails signature
  tooling — never use it for shipped builds.
- `-t` only parallelizes the **uncompressed** body path; with `-c` it is
  ignored.
- Unknown flag / missing required value → exit `2` and usage is printed. There
  is no partial-run: bad args mean nothing was written.
