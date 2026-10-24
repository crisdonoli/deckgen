#!/bin/bash
# Full deck pipeline inside a single deck folder:
#   <deck>/*.xml          order XML (stays)
#   <deck>/images/        card images (loose top-level images are moved here)
#   <deck>/export/fronts|backs/  autofill single-card PDFs
#   <deck>/sheets/        full-bleed cut-line sheets + size-capped parts
# Flow:
#   1. Organize loose top-level images into <deck>/images/.
#   2. Unless <deck>/export/ is complete: link ./cards and ./deck.xml
#      as needed, then run autofill-linux.bin --exportpdf.
#   3. Build sheets (--print-size a3|a4), split into parts <= --pdf-size MB.
#   4. Remove temp links; on success also remove autofill logs.
# Usage: ./make-deck.sh --cards DIR [--xml FILE] --print-size a3|a4|a4-3 [--tight] [--landscape] [--pdf-size MB] [--fronts-only|--backs-only]
set -euo pipefail

usage() {
    cat >&2 <<EOF
Usage: $0 --cards DIR [--xml FILE] --print-size a3|a4|a4-3 [--tight] [--landscape] [--pdf-size MB] [--fronts-only|--backs-only]

  --cards DIR        deck folder with card images (and usually the .xml).
  --xml FILE         order XML. Defaults to the single .xml in DIR or DIR/images/.
  --print-size a3|a4|a4-3 sheet paper size. a3 fits 4x4 cards, a4 fits 3x3,
                     a4-3 fits 4x2 on A4 landscape (= half an A3, two A4-3 per A3).
  --tight            cards touch with no bleed; 1pt white cut lines on shared edges.
  --landscape        landscape orientation for a3/a4 (a3: 6x3, a4: 4x2).
  --pdf-size MB      optional; max size per output part in MB. If omitted the PDF is not split.
  --bin PATH         autofill binary (default: ./autofill-linux.bin on Linux,
                     ./autofill-macos-<arch>.command on macOS; downloaded
                     automatically from upstream releases if missing).
  --fronts-only      build sheets for card fronts only.
  --backs-only       build sheets for card backs only.
  -h, --help         show this help.

Layout produced inside DIR: images/ (cards), export/fronts|backs/ (autofill
PDFs), sheets/ (print sheets + parts). Re-running skips autofill when
export/ is already complete.
EOF
}

CARDS=""; XML=""; PRINTSIZE=""; PDF_SIZE=""; FRONTS_ONLY=0; BACKS_ONLY=0; TIGHT=0; LANDSCAPE=0; BIN=""; BIN_GIVEN=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --cards) CARDS="${2:?}"; shift 2;;
        --xml) XML="${2:?}"; shift 2;;
        --print-size) PRINTSIZE="${2:?}"; shift 2;;
        --pdf-size) PDF_SIZE="${2:?}"; shift 2;;
        --bin) BIN="${2:?}"; BIN_GIVEN=1; shift 2;;
        --tight) TIGHT=1; shift;;
        --landscape) LANDSCAPE=1; shift;;
        --fronts-only) FRONTS_ONLY=1; shift;;
        --backs-only) BACKS_ONLY=1; shift;;
        -h|--help) usage; exit 0;;
        *) echo "Unknown argument: $1" >&2; usage; exit 1;;
    esac
done
if [[ -z "$CARDS" || -z "$PRINTSIZE" ]]; then
    usage; exit 1
fi
if [[ "$PRINTSIZE" != a3 && "$PRINTSIZE" != a4 && "$PRINTSIZE" != a4-3 ]]; then
    echo "--print-size must be a3, a4 or a4-3" >&2; exit 1
fi
if [[ $TIGHT == 1 && "$PRINTSIZE" == a4-3 ]]; then
    echo "--tight is not supported with a4-3" >&2; exit 1
fi
if [[ -n "$PDF_SIZE" && ! "$PDF_SIZE" =~ ^[0-9]+$ ]]; then
    echo "--pdf-size must be a number (MB)" >&2; exit 1
fi
if [[ $FRONTS_ONLY == 1 && $BACKS_ONLY == 1 ]]; then
    echo "--fronts-only and --backs-only are mutually exclusive" >&2; exit 1
fi
if [[ -z "$BIN" ]]; then
    if [[ "$(uname -s)" == Darwin ]]; then
        if [[ "$(uname -m)" == arm64 ]]; then
            BIN="./autofill-macos-arm.command"
        else
            BIN="./autofill-macos-intel.command"
        fi
    else
        BIN="./autofill-linux.bin"
    fi
fi

ensure_autofill() {
    # Uses the existing binary, or downloads it from the upstream releases.
    if [[ -x "$BIN" ]]; then
        return 0
    fi
    if [[ $BIN_GIVEN == 1 ]]; then
        echo "Autofill binary not found or not executable: $BIN" >&2; exit 1
    fi
    for cmd in curl unzip; do
        command -v "$cmd" >/dev/null 2>&1 || { echo "Need $cmd to download the autofill binary." >&2; exit 1; }
    done
    local os arch asset inner
    os="$(uname -s)"; arch="$(uname -m)"
    if [[ "$os" == Linux ]]; then
        asset="autofill-linux.zip"; inner="autofill-linux.bin"
    elif [[ "$os" == Darwin && "$arch" == arm64 ]]; then
        asset="autofill-macos-arm.zip"; inner="autofill-macos-arm.command"
    elif [[ "$os" == Darwin ]]; then
        asset="autofill-macos-intel.zip"; inner="autofill-macos-intel.command"
    else
        echo "Unsupported platform ($os/$arch) — download the desktop tool manually" >&2
        echo "from https://github.com/chilli-axe/mpc-autofill/releases and pass --bin PATH." >&2
        exit 1
    fi
    echo "Downloading $asset from the MPC Autofill releases..."
    curl -fL --retry 3 -o "$WORKDIR/autofill.zip" "https://github.com/chilli-axe/mpc-autofill/releases/latest/download/$asset"
    unzip -o -j "$WORKDIR/autofill.zip" "$inner" -d . >/dev/null
    if [[ "$inner" != "$(basename "$BIN")" ]]; then
        mv "$inner" "$BIN"
    fi
    chmod +x "$BIN"
    echo "Saved to $BIN"
}

# Portable helpers (macOS lacks realpath(1) and GNU stat).
abspath() { # $1 = existing path -> absolute path
    (cd "$(dirname "$1")" >/dev/null 2>&1 && printf '%s/%s\n' "$PWD" "$(basename "$1")")
}
fsize() { # $1 = file -> size in bytes
    stat -c%s "$1" 2>/dev/null || stat -f%z "$1"
}

# Base sheet dimensions and LaTeX paper option.
if [[ "$PRINTSIZE" == a3 ]]; then
    PAPER=a3paper; PW=297; PH=420; GEOM="a3paper"
elif [[ "$PRINTSIZE" == a4 ]]; then
    PAPER=a4paper; PW=210; PH=297; GEOM="a4paper"
else # a4-3: A4 landscape, 4x2 = half an A3 (297x210). Two a4-3 sheets == one A3 (297x420).
    PAPER=a4paper; PW=297; PH=210; GEOM="a4paper,landscape"
fi

# Landscape orientation swaps width/height.
if [[ $LANDSCAPE == 1 && "$PRINTSIZE" != a4-3 ]]; then
    tmp=$PW; PW=$PH; PH=$tmp
    GEOM="$PAPER,landscape"
fi

CARDS_ABS=""; XML_ABS=""
LINKED_CARDS=0; LINKED_XML=0

restore() {
    if [[ $LINKED_CARDS == 1 ]]; then
        rm -f ./cards
    fi
    if [[ $LINKED_XML == 1 ]]; then
        rm -f ./deck.xml
    fi
    LINKED_CARDS=0; LINKED_XML=0
}

has_export() { # $1 = dir -> true if fronts/ + backs/ hold PDFs
    [[ -d "$1/fronts" && -d "$1/backs" ]] \
        && compgen -G "$1/fronts/*.pdf" >/dev/null \
        && compgen -G "$1/backs/*.pdf" >/dev/null
}

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"; restore' EXIT
trap 'rm -rf "$WORKDIR"; restore; exit 130' INT TERM

if [[ -n "$PDF_SIZE" ]]; then
    LIMIT=$((PDF_SIZE * 1024 * 1024))
fi

# Cut cell size: standard poker.
CARD_W=63.5 # mm
CARD_H=88.9 # mm
# Full-bleed source page size in mm (196.56 x 267.12 pt). The grid pitch
# equals the full-bleed size so neighbouring images never overlap.
IMG_W=69.34 # mm
IMG_H=94.22 # mm
BLEED_X=$(awk -v i="$IMG_W" -v c="$CARD_W" 'BEGIN{printf "%.2f", (i-c)/2}')
BLEED_Y=$(awk -v i="$IMG_H" -v c="$CARD_H" 'BEGIN{printf "%.2f", (i-c)/2}')

# Cell pitch and image size on the sheet.
if [[ $TIGHT == 1 ]]; then
    CW=$CARD_W; CH=$CARD_H
else
    CW=$IMG_W; CH=$IMG_H
fi

# Cards per sheet by floor fit.
COLS=$(awk -v pw="$PW" -v cw="$CW" 'BEGIN{print int(pw/cw)}')
ROWS=$(awk -v ph="$PH" -v ch="$CH" 'BEGIN{print int(ph/ch)}')

# Grid corners (image cells), centred on the sheet.
XS=()
while IFS= read -r line; do XS+=("$line"); done < <(awk -v cw="$CW" -v n="$COLS" -v pw="$PW" 'BEGIN{mx=(pw-n*cw)/2; for(k=0;k<=n;k++) printf "%.2f\n", mx+k*cw}')
YS=()
while IFS= read -r line; do YS+=("$line"); done < <(awk -v ch="$CH" -v n="$ROWS" -v ph="$PH" 'BEGIN{my=(ph-n*ch)/2; for(k=0;k<=n;k++) printf "%.2f\n", my+k*ch}')

# Cut lines.
DRAW_XS=(); DRAW_YS=()
if [[ $TIGHT == 1 ]]; then
    # One white line per shared vertical/horizontal boundary.
    for ((c = 1; c < COLS; c++)); do DRAW_XS+=("${XS[$c]}"); done
    for ((r = 1; r < ROWS; r++)); do DRAW_YS+=("${YS[$r]}"); done
else
    # Two lines per card edge (left/right, bottom/top) at the trimmed edge.
    for ((c = 0; c < COLS; c++)); do
        x=${XS[$c]}
        DRAW_XS+=("$(awk -v x="$x" -v b="$BLEED_X" 'BEGIN{printf "%.2f", x+b}')")
        DRAW_XS+=("$(awk -v x="$x" -v i="$IMG_W" -v b="$BLEED_X" 'BEGIN{printf "%.2f", x+i-b}')")
    done
    for ((r = 0; r < ROWS; r++)); do
        y=${YS[$r]}
        DRAW_YS+=("$(awk -v y="$y" -v b="$BLEED_Y" 'BEGIN{printf "%.2f", y+b}')")
        DRAW_YS+=("$(awk -v y="$y" -v i="$IMG_H" -v b="$BLEED_Y" 'BEGIN{printf "%.2f", y+i-b}')")
    done
fi

# a4-3 uses two A4 landscape sheets per A3: odd pages are the bottom half,
# even pages are the top half. Vertical positions reuse the A3 grid.
if [[ "$PRINTSIZE" == a4-3 ]]; then
    A43_LOWER_ROW_YS=()
    while IFS= read -r line; do A43_LOWER_ROW_YS+=("$line"); done < <(awk -v ch="$IMG_H" 'BEGIN{my=(420-4*ch)/2; for(k=0;k<2;k++) printf "%.2f\n", my+k*ch}')
    A43_UPPER_ROW_YS=()
    while IFS= read -r line; do A43_UPPER_ROW_YS+=("$line"); done < <(awk -v ch="$IMG_H" 'BEGIN{my=(420-4*ch)/2; for(k=2;k<4;k++) printf "%.2f\n", my+k*ch-210}')
    A43_LOWER_LINE_YS=()
    while IFS= read -r line; do A43_LOWER_LINE_YS+=("$line"); done < <(awk -v ch="$IMG_H" -v b="$BLEED_Y" 'BEGIN{my=(420-4*ch)/2; for(k=0;k<2;k++){y=my+k*ch; printf "%.2f\n%.2f\n", y+b, y+ch-b}}')
    A43_UPPER_LINE_YS=()
    while IFS= read -r line; do A43_UPPER_LINE_YS+=("$line"); done < <(awk -v ch="$IMG_H" -v b="$BLEED_Y" 'BEGIN{my=(420-4*ch)/2; for(k=2;k<4;k++){y=my+k*ch-210; printf "%.2f\n%.2f\n", y+b, y+ch-b}}')
fi

split_pdf() {
    local file="$1" prefix="$2" # e.g. <deck>/sheets/a3_fronts.pdf, .../a3_fronts
    local total
    total="$(pdfinfo "$file" | awk '/^Pages:/ {print $2}')"
    pdfseparate "$file" "$WORKDIR/part-%d.pdf"
    # Greedy grouping: accumulate pages until the next one would exceed LIMIT.
    local -a gstart=() gend=()
    local gs=1 acc=0 p s
    for ((p = 1; p <= total; p++)); do
        s=$(fsize "$WORKDIR/part-$p.pdf")
        if (( acc > 0 && acc + s > LIMIT )); then
            gstart+=($gs); gend+=($((p - 1))); gs=$p; acc=0
        fi
        acc=$((acc + s))
    done
    gstart+=($gs); gend+=($total)
    local n=${#gstart[@]} i start end
    if (( n == 1 )); then
        local fullsize
        fullsize=$(fsize "$file")
        echo "$(basename "$file"): $((fullsize / 1024 / 1024)) MB (fits in one part)"
    else
        for ((i = 0; i < n; i++)); do
            start=${gstart[$i]}; end=${gend[$i]}
            local pages=()
            for ((p = start; p <= end; p++)); do pages+=("$WORKDIR/part-$p.pdf"); done
            pdfunite "${pages[@]}" "${prefix}_p$((i + 1)).pdf"
            local size
            size=$(fsize "${prefix}_p$((i + 1)).pdf")
            echo "${prefix}_p$((i + 1)).pdf: $((size / 1024 / 1024)) MB (pages $start-$end)"
            if (( size > LIMIT )); then
                echo "WARNING: ${prefix}_p$((i + 1)).pdf exceeds the limit (one page alone is too large?)" >&2
            fi
        done
    fi
    rm -f "$WORKDIR"/part-*.pdf
}

build_sheets_tex() {
    local -n sheet_files="$1"
    local tex="$2" total="$3" # e.g. files array, fronts.tex, 100
    local line_spec="line width=0.4pt"
    [[ $TIGHT == 1 ]] && line_spec="line width=1pt,white"
    {
        printf '%s\n' "\documentclass[$PAPER]{article}" "\usepackage[$GEOM,margin=0pt]{geometry}" '\usepackage{graphicx,tikz}' '\pagestyle{empty}' '\begin{document}'
        local p=1 page=0
        while [[ $p -le $total ]]; do
            page=$((page + 1))
            local -a PLACE_YS=() CUT_YS=()
            if [[ "$PRINTSIZE" == a4-3 ]]; then
                if (( page % 2 == 1 )); then
                    PLACE_YS=("${A43_LOWER_ROW_YS[@]}")
                    CUT_YS=("${A43_LOWER_LINE_YS[@]}")
                else
                    PLACE_YS=("${A43_UPPER_ROW_YS[@]}")
                    CUT_YS=("${A43_UPPER_LINE_YS[@]}")
                fi
            else
                PLACE_YS=("${YS[@]}")
                CUT_YS=("${DRAW_YS[@]}")
            fi

            printf '%s\n' '\begin{tikzpicture}[remember picture,overlay]'
            local r c
            for ((r = 0; r < ROWS && p <= total; r++)); do
                for ((c = 0; c < COLS && p <= total; c++)); do
                    printf '%s\n' "\node[anchor=south west,inner sep=0pt] at ([xshift=${XS[$c]}mm,yshift=${PLACE_YS[$r]}mm]current page.south west) {\\includegraphics[width=${CW}mm,height=${CH}mm]{${sheet_files[$p-1]}}};"
                    p=$((p + 1))
                done
            done
            local x
            for x in "${DRAW_XS[@]}"; do
                printf '%s\n' "\draw[$line_spec] ([xshift=${x}mm]current page.south west) -- ([xshift=${x}mm]current page.north west);"
            done
            local y
            for y in "${CUT_YS[@]}"; do
                printf '%s\n' "\draw[$line_spec] ([yshift=${y}mm]current page.south west) -- ([yshift=${y}mm]current page.south east);"
            done
            printf '%s\n' '\end{tikzpicture}'
            if [[ $p -le $total ]]; then
                printf '%s\n' '\newpage'
            fi
        done
        printf '%s\n' '\end{document}'
    } > "$tex"
}

build_face() {
    local face="$1" src_dir="$2" out_prefix="$3" # e.g. fronts, <deck>/export, <deck>/sheets/a3_fronts
    local files=()
    while IFS= read -r f; do files+=("$src_dir/$face/$f"); done < <(ls "$src_dir/$face" | sort -t. -k1,1n)
    local pages=${#files[@]}
    echo "$face: $pages cards"
    build_sheets_tex files "$WORKDIR/$face.tex" "$pages"
    # NOTE: -jobname keeps the output name different from the input PDF.
    # pdflatex destroys the input file when both names match.
    # NOTE: two runs — tikz 'remember picture' positions settle on the second pass.
    # NOTE: log to file, show tail on failure instead of silent /dev/null.
    local log="$WORKDIR/$(basename "$out_prefix").log"
    (cd "$WORKDIR" && pdflatex -interaction=nonstopmode -jobname "$(basename "$out_prefix")" "$face.tex" >"$log" 2>&1 && pdflatex -interaction=nonstopmode -jobname "$(basename "$out_prefix")" "$face.tex" >"$log" 2>&1) || { echo "pdflatex failed, tail of $log:" >&2; tail -n 50 "$log" >&2; return 1; }
    mv "$WORKDIR/$(basename "$out_prefix").pdf" "${out_prefix}.pdf"
    echo "$face -> ${out_prefix}.pdf"
    if [[ -n "$PDF_SIZE" ]]; then
        split_pdf "${out_prefix}.pdf" "$out_prefix"
    fi
}

# ---- main ----
if [[ ! -d "$CARDS" ]]; then
    echo "Cards folder not found: $CARDS" >&2; exit 1
fi
CARDS_ABS="$(abspath "$CARDS")"
IMAGES="$CARDS_ABS/images"
EXPORT="$CARDS_ABS/export"
SHEETS="$CARDS_ABS/sheets"

# 1. Organize: loose top-level images -> images/
shopt -s nullglob
loose=( "$CARDS_ABS"/*.jpg "$CARDS_ABS"/*.jpeg "$CARDS_ABS"/*.png "$CARDS_ABS"/*.JPG "$CARDS_ABS"/*.JPEG "$CARDS_ABS"/*.PNG )
shopt -u nullglob
if [[ ! -d "$IMAGES" && ${#loose[@]} -gt 0 ]]; then
    mkdir -p "$IMAGES"
    mv "${loose[@]}" "$IMAGES/"
    echo "Moved ${#loose[@]} images to $IMAGES/"
fi
mkdir -p "$IMAGES" "$EXPORT" "$SHEETS"
shopt -s nullglob
have_images=( "$IMAGES"/* )
shopt -u nullglob
if [[ ${#have_images[@]} == 0 ]]; then
    echo "No local images in $IMAGES/ — autofill will download them." >&2
fi

# 2. XML: explicit flag or auto-detect (deck root, then images/).
if [[ -z "$XML" ]]; then
    shopt -s nullglob
    cands=( "$CARDS_ABS"/*.xml "$IMAGES"/*.xml )
    shopt -u nullglob
    if [[ ${#cands[@]} != 1 ]]; then
        echo "Found ${#cands[@]} .xml files — pass the right one with --xml." >&2; exit 1
    fi
    XML="${cands[0]}"
    echo "Auto-detected XML: $XML"
fi
if [[ ! -f "$XML" ]]; then
    echo "XML file not found: $XML" >&2; exit 1
fi
XML_ABS="$(abspath "$XML")"

# 3. Autofill export, unless already complete.
if has_export "$EXPORT"; then
    echo "Found complete export in $EXPORT — skipping autofill, building $PRINTSIZE sheets."
else
    EXPORT_NAME="deck"
    if [[ ! -e ./cards ]]; then
        ln -s "$IMAGES" ./cards
        LINKED_CARDS=1
    else
        echo "./cards already in place — using it as-is."
    fi
    shopt -s nullglob
    xmls=(./*.xml)
    shopt -u nullglob
    if [[ ${#xmls[@]} == 0 ]]; then
        ln -s "$XML_ABS" ./deck.xml
        LINKED_XML=1
    elif [[ ${#xmls[@]} == 1 ]]; then
        EXPORT_NAME="$(basename "${xmls[0]}" .xml)"
        echo "Using ${xmls[0]} as-is."
    else
        echo "Multiple XML files in this folder — move all but one away first." >&2
        exit 1
    fi
    ensure_autofill
    rm -rf "export/$EXPORT_NAME"
    echo "Running autofill export — answer 'Yes' when asked for separate face PDFs."
    "$BIN" --allowsleep --exportpdf
    if ! has_export "export/$EXPORT_NAME"; then
        echo "Autofill did not produce export/$EXPORT_NAME/{fronts,backs} — aborting." >&2
        exit 1
    fi
    rm -rf "$EXPORT/fronts" "$EXPORT/backs"
    mv "export/$EXPORT_NAME/fronts" "export/$EXPORT_NAME/backs" "$EXPORT/"
    rmdir "export/$EXPORT_NAME" 2>/dev/null || true
    rmdir export 2>/dev/null || true
    echo "Export stored in $EXPORT/"
fi

# 4. Sheets.
if [[ $BACKS_ONLY == 0 ]]; then
    build_face fronts "$EXPORT" "$SHEETS/${PRINTSIZE}_fronts"
fi
if [[ $FRONTS_ONLY == 0 ]]; then
    build_face backs "$EXPORT" "$SHEETS/${PRINTSIZE}_backs"
fi

# 5. Success: drop autofill logs (kept on failure for debugging).
rm -f ./autofill_crash_log.txt ./autofill_logs.txt
echo "Done. Everything is inside $CARDS_ABS/ — print at 100% (actual size), not fit-to-page."
