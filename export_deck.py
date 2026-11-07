import argparse
import shutil
import subprocess
import sys
from pathlib import Path


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff"}


def organize_images(cards_dir: Path, images_dir: Path) -> None:
    images_dir.mkdir(exist_ok=True)
    for path in cards_dir.iterdir():
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            destination = images_dir / path.name
            if destination.exists() or destination.is_symlink():
                destination.unlink()
            path.rename(destination)


def detect_xml(workdir: Path) -> Path:
    candidates = [p for p in workdir.iterdir() if p.is_file() and p.suffix.lower() == ".xml"]
    if len(candidates) == 1:
        return candidates[0].resolve()
    if len(candidates) > 1:
        sys.exit("multiple XML files found; use --xml")
    sys.exit("no XML file found; use --xml")


def export_is_complete(export_dir: Path) -> bool:
    fronts = export_dir / "fronts"
    backs = export_dir / "backs"
    return (
        fronts.is_dir()
        and backs.is_dir()
        and any(fronts.glob("*.pdf"))
        and any(backs.glob("*.pdf"))
    )


def find_autofill_binary(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    found = shutil.which("autofill")
    if found:
        return Path(found).resolve()
    sys.exit("autofill binary not found; use --bin")


def create_link(link_path: Path, target: Path, is_dir: bool = False) -> None:
    if link_path.exists() or link_path.is_symlink():
        link_path.unlink()
    link_path.symlink_to(target, target_is_directory=is_dir)


def run_autofill(bin_path: Path, workdir: Path) -> None:
    try:
        proc = subprocess.run(
            [str(bin_path), "--allowsleep", "--exportpdf"],
            stdin=None,
            cwd=workdir,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired:
        sys.exit("autofill timed out")
    if proc.returncode != 0:
        sys.exit(f"autofill exited with code {proc.returncode}")


def move_export_subdirs(export_dir: Path) -> None:
    if not export_dir.is_dir():
        return
    for subdir in export_dir.iterdir():
        if not subdir.is_dir():
            continue
        for name in ("fronts", "backs"):
            src = subdir / name
            dst = export_dir / name
            if not src.is_dir():
                continue
            if dst.exists() or dst.is_symlink():
                if dst.is_dir() and not dst.is_symlink():
                    shutil.rmtree(dst)
                else:
                    dst.unlink()
            src.rename(dst)
        try:
            subdir.rmdir()
        except OSError:
            pass
        break


def main() -> None:
    parser = argparse.ArgumentParser(description="Export deck via autofill")
    parser.add_argument("--cards", required=True, help="Directory with card images")
    parser.add_argument("--xml", help="Path to deck XML file")
    parser.add_argument("--bin", help="Path to autofill binary")
    args = parser.parse_args()

    workdir = Path.cwd()
    cards_dir = Path(args.cards).resolve()
    if not cards_dir.is_dir():
        sys.exit(f"cards directory not found: {cards_dir}")

    organize_images(cards_dir, workdir / "images")

    xml_file = Path(args.xml).resolve() if args.xml else detect_xml(workdir)

    export_dir = workdir / "export"
    if export_is_complete(export_dir):
        print("export/ already complete; skipping autofill.")
        return

    bin_path = find_autofill_binary(Path(args.bin).resolve() if args.bin else None)

    cards_link = workdir / "cards"
    xml_link = workdir / "deck.xml"
    create_link(cards_link, cards_dir, is_dir=True)
    create_link(xml_link, xml_file, is_dir=False)

    try:
        run_autofill(bin_path, workdir)
    finally:
        for link in (cards_link, xml_link):
            if link.exists() or link.is_symlink():
                link.unlink()

    move_export_subdirs(export_dir)


if __name__ == "__main__":
    main()
