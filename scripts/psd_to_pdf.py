import io
import re
import sys
from pathlib import Path
import pymupdf
from psd_tools import PSDImage

def localizar_psds(directorio: Path) -> list[Path]:
    return sorted(p for p in directorio.rglob("*") if p.is_file() and p.suffix.lower() == ".psd")

def sanitizar_nombre(nombre: str) -> str:
    """Elimina caracteres inválidos para rutas de archivos."""
    limpio = re.sub(r'[\\/*?:"<>|]', "", nombre).strip()
    return limpio if limpio else "sin_nombre"

def obtener_ruta_relativa_capa(layer) -> Path:
    """Recrea la ruta de carpetas/grupos del PSD."""
    partes = []
    actual = layer.parent
    while actual and hasattr(actual, "parent") and actual.parent is not None:
        if actual.name:
            partes.append(sanitizar_nombre(actual.name))
        actual = actual.parent
    partes.reverse()
    return Path(*partes) if partes else Path()

def exportar_todas_las_capas_template(
    ruta_psd: str, 
    carpeta_base: str | None = None, 
    mantener_lienzo: bool = True,
    solo_visibles: bool = False  # False para extraer también lands/nonlands ocultos
) -> None:
    path_origen = Path(ruta_psd)
    if path_origen.is_dir():
        for psd in localizar_psds(path_origen):
            exportar_todas_las_capas_template(
                str(psd), carpeta_base, mantener_lienzo, solo_visibles
            )
        return

    if not path_origen.exists():
        raise FileNotFoundError(f"No existe: {ruta_psd}")

    nombre_carpeta = path_origen.stem
    carpeta_destino = Path(carpeta_base) / nombre_carpeta if carpeta_base else path_origen.parent / nombre_carpeta
    carpeta_destino.mkdir(parents=True, exist_ok=True)

    print(f"Leyendo plantilla '{path_origen.name}'...")
    psd = PSDImage.open(path_origen)

    dpi = getattr(psd, "resolution", 72) or 72
    if isinstance(dpi, tuple):
        dpi = dpi[0]
    factor_escala = 72.0 / float(dpi)

    pdf_w = psd.width * factor_escala
    pdf_h = psd.height * factor_escala

    total_exportadas = 0

    # Recorremos todos los elementos descendientes
    for idx, layer in enumerate(psd.descendants(), start=1):
        # Omitir carpetas/grupos en sí (solo procesamos capas de contenido)
        if layer.is_group():
            continue

        if solo_visibles and not layer.is_visible():
            continue

        # Intentar obtener la imagen:
        # composite() funciona si la capa está activa; topil() extrae los píxeles directos
        # incluso si la capa o su carpeta padre están ocultas.
        try:
            img_capa = layer.topil()
        except Exception:
            try:
                img_capa = layer.composite()
            except Exception:
                img_capa = None

        if img_capa is None or img_capa.width == 0 or img_capa.height == 0:
            continue

        # Validar coordenadas
        bbox = layer.bbox
        if not bbox or layer.width <= 0 or layer.height <= 0:
            continue

        x1, y1, x2, y2 = bbox

        # Recrear la subcarpeta según el grupo de Photoshop (ej. Lands/...)
        subcarpeta = carpeta_destino / obtener_ruta_relativa_capa(layer)
        subcarpeta.mkdir(parents=True, exist_ok=True)

        buffer = io.BytesIO()
        img_capa.save(buffer, format="PNG")
        img_bytes = buffer.getvalue()

        doc_capa = pymupdf.open()

        if mantener_lienzo:
            page = doc_capa.new_page(width=pdf_w, height=pdf_h)
            rect = pymupdf.Rect(
                x1 * factor_escala,
                y1 * factor_escala,
                x2 * factor_escala,
                y2 * factor_escala,
            )
        else:
            ancho_capa = (x2 - x1) * factor_escala
            alto_capa = (y2 - y1) * factor_escala
            page = doc_capa.new_page(width=ancho_capa, height=alto_capa)
            rect = pymupdf.Rect(0, 0, ancho_capa, alto_capa)

        if not rect.is_empty and rect.is_valid:
            page.insert_image(rect, stream=img_bytes)
            
            nombre_limpio = sanitizar_nombre(layer.name or f"capa_{idx}")
            estado_ojo = "" if layer.is_visible() else "_[oculta]"
            archivo_pdf = subcarpeta / f"{idx:03d}_{nombre_limpio}{estado_ojo}.pdf"

            doc_capa.save(archivo_pdf)
            total_exportadas += 1
            print(f"  [✓] {archivo_pdf.relative_to(carpeta_destino)}")

        doc_capa.close()

    print(f"\nFinalizado: {total_exportadas} capas (incluyendo ocultas) exportadas en '{carpeta_destino}'.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python psd_to_pdf.py <archivo.psd|directorio>")
    else:
        exportar_todas_las_capas_template(sys.argv[1], carpeta_base=None, mantener_lienzo=True, solo_visibles=False)