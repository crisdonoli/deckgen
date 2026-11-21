import json
import re
import time
from bs4 import BeautifulSoup
import requests

ARTISTS_INDEX_URL = "https://www.artofmtg.com/mtg-artists/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"
        " Chrome/128.0.0.0 Safari/537.36"
    )
}


def get_artist_links(session: requests.Session) -> list[dict]:
  resp = session.get(ARTISTS_INDEX_URL, headers=HEADERS, timeout=15)
  resp.raise_for_status()
  soup = BeautifulSoup(resp.text, "html.parser")

  artists = []
  seen_urls = set()

  # Busca todos los enlaces dentro del contenido principal que apunten a /artist/
  for a in soup.select('a[href*="/artist/"]'):
    url = a["href"].strip()
    name = a.get_text(strip=True)
    if not name or url in seen_urls:
      continue
    seen_urls.add(url)
    artists.append({"artist": name, "url": url})

  return artists


def infer_set_from_url(card_name: str, image_url: str) -> str | None:
  """Intenta extraer el set si el archivo sigue el patrón 'Carta-Set-MtG-Art.jpg'."""
  filename = image_url.split("/")[-1]
  match = re.search(
      r"-([A-Za-z0-9-]+?)-MtG-Art(?:-\d+)?\.[a-zA-Z]+$",
      filename,
      re.IGNORECASE,
  )
  if not match:
    return None

  slug_part = match.group(1)
  card_slug = re.sub(r"[^a-zA-Z0-9]+", "-", card_name).strip("-")

  # Si el slug capturado empieza con el nombre de la carta, lo recortamos
  if slug_part.lower().startswith(card_slug.lower() + "-"):
    set_slug = slug_part[len(card_slug) + 1 :]
    return set_slug.replace("-", " ")
  return None


def scrape_artist(
    session: requests.Session, artist_name: str, base_url: str
) -> list[dict]:
  results = []
  page = 1

  while True:
    url = base_url if page == 1 else f"{base_url.rstrip('/')}/page/{page}/"
    try:
      resp = session.get(url, headers=HEADERS, timeout=15)
      if resp.status_code == 404:
        break
      resp.raise_for_status()
    except requests.RequestException as e:
      print(f"  [!] Error en {url}: {e}")
      break

    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.select(".artwork-card")
    if not cards:
      break

    for card in cards:
      title_el = card.select_one("h4")
      img_el = card.select_one("img")
      if not title_el or not img_el:
        continue

      card_name = title_el.get_text(strip=True)
      thumb_url = img_el.get("data-src") or img_el.get("src") or ""

      # Limpia sufijos como -300x300 para obtener la imagen original
      highres_url = re.sub(r"-\d+x\d+(?=\.[a-zA-Z]+$)", "", thumb_url)
      inferred_set = infer_set_from_url(card_name, highres_url)

      results.append({
          "name": card_name,
          "artist": artist_name,
          "set": inferred_set,
          "image_url": highres_url,
      })

    print(f"  -> Página {page}: {len(cards)} cartas")
    page += 1
    time.sleep(0.4)

  return results


def main():
  output_file = "artofmtg_artists_cards.json"
  all_cards = []

  with requests.Session() as session:
    print("Obteniendo lista de artistas...")
    artists = get_artist_links(session)
    print(f"Total de artistas encontrados: {len(artists)}\n")

    for idx, item in enumerate(artists, 1):
      print(f"[{idx}/{len(artists)}] Procesando: {item['artist']}")
      cards = scrape_artist(session, item["artist"], item["url"])
      all_cards.extend(cards)

      # Guardado incremental cada 25 artistas para no perder progreso si se corta la conexión
      if idx % 25 == 0:
        with open(output_file, "w", encoding="utf-8") as f:
          json.dump(all_cards, f, indent=2, ensure_ascii=False)

  with open(output_file, "w", encoding="utf-8") as f:
    json.dump(all_cards, f, indent=2, ensure_ascii=False)

  print(f"\nListo. Se guardaron {len(all_cards)} registros en '{output_file}'.")


if __name__ == "__main__":
  main()
