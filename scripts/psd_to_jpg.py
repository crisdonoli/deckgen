import re
import sys
from pathlib import Path
from PIL import Image
from psd_tools import PSDImage

def localizar_psds(directorio: Path) -> list[Path]:
    return sorted(p for p in directorio.rglob("*") if p.is_file() and p.suffix.lower() == ".psd")

def sanitizar_nombre(nombre: str) -> str:
    """Elimina caracteres inválidos para rutas de archivos."""
    limpio = re.sub(r'[\\/*?:"<>|]', "", nombre).strip()
    return limpio if limpio else "sin_nombre"

def obtener_ruta_relativa_capa(layer) -> Path:
    """Recrea la ruta de carpetas/grupos del PSD de forma idéntica al exportador PDF."""
    partes = []
    actual = layer.parent
    while actual and hasattr(actual, "parent") and actual.parent is not None:
        if actual.name:
            partes.append(sanitizar_nombre(actual.name))
        actual = actual.parent
    partes.reverse()
    return Path(*partes) if partes else Path()

def capa_a_jpeg_rgb(img_capa: Image.Image, color_fondo: tuple = (0, 0, 0)) -> Image.Image:
    """Convierte una imagen (RGBA/LA/P) a RGB plano sobre fondo para compatibilidad con JPEG."""
    if img_capa.mode in ("RGBA", "LA"):
        fondo = Image.new("RGB", img_capa.size, color_fondo)
        # Usa el canal alfa como máscara de composición
        canal_alfa = img_capa.split()[-1]
        fondo.paste(img_capa.convert("RGB"), mask=canal_alfa)
        return fondo
    elif img_capa.mode != "RGB":
        return img_capa.convert("RGB")
    return img_capa

def exportar_todas_las_capas_jpg(
    ruta_psd: str,
    carpeta_base: str | None = None,
    mantener_lienzo: bool = True,
    solo_visibles: bool = False,
    calidad: int = 80,
    color_fondo: tuple = (0, 0, 0)  # Fondo negro para componer transparencias
) -> None:
    path_origen = Path(ruta_psd)
    if path_origen.is_dir():
        for psd in localizar_psds(path_origen):
            exportar_todas_las_capas_jpg(
                str(psd), carpeta_base, mantener_lienzo, solo_visibles, calidad, color_fondo
            )
        return

    if not path_origen.exists():
        raise FileNotFoundError(f"No existe: {ruta_psd}")

    nombre_carpeta = path_origen.stem
    carpeta_destino = Path(carpeta_base) / nombre_carpeta if carpeta_base else path_origen.parent / nombre_carpeta
    carpeta_destino.mkdir(parents=True, exist_ok=True)

    print(f"Leyendo plantilla '{path_origen.name}'...")
    psd = PSDImage.open(path_origen)

    ancho_lienzo, alto_lienzo = psd.width, psd.height
    total_exportadas = 0

    for idx, layer in enumerate(psd.descendants(), start=1):
        if layer.is_group():
            continue

        if solo_visibles and not layer.is_visible():
            continue

        # Extraer imagen de la capa (incluso si está en un grupo oculto)
        try:
            img_capa = layer.topil()
        except Exception:
            try:
                img_capa = layer.composite()
            except Exception:
                img_capa = None

        if img_capa is None or img_capa.width == 0 or img_capa.height == 0:
            continue

        bbox = layer.bbox
        if not bbox or layer.width <= 0 or layer.height <= 0:
            continue

        x1, y1, x2, y2 = bbox

        # Recrear estructura de subdirectorios
        subcarpeta = carpeta_destino / obtener_ruta_relativa_capa(layer)
        subcarpeta.mkdir(parents=True, exist_ok=True)

        # Generar imagen final para la capa
        if mantener_lienzo:
            # Crea un lienzo completo y pega la capa en sus coordenadas exactas
            lienzo = Image.new("RGB", (ancho_lienzo, alto_lienzo), color_fondo)
            img_rgb = capa_a_jpeg_rgb(img_capa, color_fondo=color_fondo)
            lienzo.paste(img_rgb, (x1, y1))
            img_final = lienzo
        else:
            # Recortada a las dimensiones de la capa
            img_final = capa_a_jpeg_rgb(img_capa, color_fondo=color_fondo)

        # Mismo patrón de nombre idéntico al PDF
        nombre_limpio = sanitizar_nombre(layer.name or f"capa_{idx}")
        estado_ojo = "" if layer.is_visible() else "_[oculta]"
        archivo_jpg = subcarpeta / f"{idx:03d}_{nombre_limpio}{estado_ojo}.jpg"

        # Guardado optimizado y progresivo para carga rápida
        img_final.save(
            archivo_jpg,
            "JPEG",
            quality=calidad,
            optimize=True,
            progressive=True,
            subsampling=2  # 4:2:0 chroma subsampling: reduce drásticamente el peso
        )
        total_exportadas += 1
        print(f"  [✓] {archivo_jpg.relative_to(carpeta_destino)}")

    print(f"\nFinalizado: {total_exportadas} capas JPG generadas en '{carpeta_destino}'.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python psd_to_jpg.py <archivo.psd|directorio>")
    else:
        exportar_todas_las_capas_jpg(
            sys.argv[1],
            carpeta_base=None,
            mantener_lienzo=True,
            solo_visibles=False,
            calidad=80
        )
