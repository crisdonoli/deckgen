# deckgen

Printable A3/A4 sheets with full-bleed cut lines from MPC Autofill PDF exports.

`make-deck.sh` takes a deck folder (card images + order XML), runs the
MPC Autofill desktop exporter, and builds print-ready sheets:
16 cards per A3 sheet (4x4) or 9 per A4 sheet (3x3), at exact card size
with black cut lines running edge to edge. Output parts are capped in
size for upload to sites like Canva.

## Workflow

1. Download your card images from [mpcfill.com/editor](https://mpcfill.com/editor).
2. Export your order XML from the MPC Autofill frontend.
3. Put the images (and usually the XML) together in one deck folder.
4. Run `make-deck.sh` (details below). When the exporter asks, answer
   **Yes** to separate face PDFs.
5. Print the sheets at 100% (actual size) — never fit-to-page.

## Requirements

- The MPC Autofill desktop binary in the working folder:
  `autofill-linux.bin` on Linux, or the matching macOS `.command`
  file passed via `--bin`.
- `bash`, `awk`, poppler tools (`pdfunite`, `pdfinfo`, `pdfseparate`),
  and `pdflatex` with the `geometry` and `pgf`/`tikz` packages.

Linux (Debian/Ubuntu):

```sh
sudo apt install poppler-utils texlive-latex-recommended texlive-pictures
```

macOS (stock `bash` works, no extra shell needed):

```sh
brew install poppler
brew install --cask mactex   # provides pdflatex + tikz
```

NixOS (example):

```sh
nix-shell -p poppler_utils texlive.combined.scheme-medium
```

## Usage

```sh
./make-deck.sh --cards DIR [--xml FILE] --print-size a3|a4 [--pdf-size MB] [--fronts-only|--backs-only] [--bin PATH]
```

| Flag | Description |
| ---- | ----------- |
| `--cards DIR` | Deck folder with card images (and usually the `.xml`). |
| `--xml FILE` | Order XML. Defaults to the single `.xml` in `DIR` or `DIR/images/`. |
| `--print-size a3\|a4` | Sheet paper size. Required. |
| `--pdf-size MB` | Max size per output part in MB (default 300). |
| `--fronts-only` / `--backs-only` | Build sheets for one face only (mutually exclusive). |
| `--bin PATH` | Autofill binary (default `./autofill-linux.bin`). |
| `-h`, `--help` | Show help. |

Example:

```sh
./make-deck.sh --cards ./decks/galazeth-cris/ --print-size a3
```

What the script does:

1. Moves loose top-level images into `DIR/images/`.
2. Unless `DIR/export/` already holds a complete export, it links
   `./cards` and `./deck.xml` as needed and runs the autofill
   exporter into `DIR/export/fronts|backs/`. Re-running skips this
   step and goes straight to sheet building.
3. Builds `DIR/sheets/a3_fronts.pdf` and `a3_backs.pdf` (or `a4_*`),
   then splits each into parts under `--pdf-size` MB
   (`a3_fronts_p1.pdf`, …). A sheet that fits is kept as a single file.
4. Removes the temporary links. On success it also deletes
   `autofill_crash_log.txt` / `autofill_logs.txt` (kept on failure
   for debugging).

Final layout — everything stays inside the deck folder:

```text
my-deck/
  cards.xml
  images/    # card images
  export/    # autofill single-card PDFs (fronts/, backs/)
  sheets/    # print sheets + size-capped parts
```

Notes:

- Cards print at exact size (poker + bleed, 2.73" x 3.71"); trim along
  the black lines to standard 2.5" x 3.5".
- On A4 the outer cut lines sit ~1mm from the paper edge — use
  borderless printing or they may be clipped.
