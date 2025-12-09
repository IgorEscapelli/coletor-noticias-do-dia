# debug_integrado.py
import json
import os
import time
from urllib.parse import urljoin
from datetime import datetime
import requests
from bs4 import BeautifulSoup

CONFIG_FILE = "config_sites.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (NewsDebug/1.0)"}

def carregar_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def obter_soup(url, timeout=12):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser"), r.status_code, r.text[:1000]
    except Exception as e:
        return None, f"ERRO: {e}", None

def extrair_data_meta(soup):
    if not soup:
        return None
    for m in soup.find_all("meta"):
        prop = (m.get("property") or "").lower()
        name = (m.get("name") or "").lower()
        if prop in ("article:published_time", "og:published_time") or name in ("pubdate","publishdate","timestamp","date"):
            if m.get("content"):
                return m["content"]
    time_tag = soup.find("time")
    if time_tag and time_tag.get("datetime"):
        return time_tag["datetime"]
    if time_tag:
        return time_tag.get_text(strip=True)
    return None

def is_date_today(text):
    if not text:
        return False
    t = str(text)
    hoje = datetime.now().date()
    if str(hoje.year) in t: return True
    if hoje.strftime("%d/%m") in t or hoje.strftime("%d-%m") in t: return True
    if hoje.strftime("%d") in t: return True
    return False

def debug_html_site(conf, max_elements=8):
    print("\n" + "="*80)
    print(f"SITE HTML: {conf.get('name')}  | homepage: {conf.get('homepage')}")
    soup, status, preview = obter_soup(conf.get("homepage"))
    print(f"HTTP status / result: {status}")
    if not soup:
        print("Não foi possível obter a homepage (verificar URL, bloqueio ou JS). Preview (1k):")
        if preview:
            print(preview[:1000])
        return

    sel = conf.get("article_selector") or ""
    print(f"article_selector: {sel!r}")
    try:
        elementos = soup.select(sel) if sel else []
    except Exception as e:
        print(f"Erro aplicando selector: {e}")
        elementos = []

    print(f"Seletores encontrados: {len(elementos)} elementos")
    if len(elementos) == 0:
        # mostrar um trecho do body pra você inspecionar manualmente
        bodytxt = soup.body.get_text(separator="\n", strip=True)[:1000] if soup.body else ""
        print("Trecho do texto da homepage (1k chars):")
        print(bodytxt)
        return

    seen = set()
    count = 0
    for el in elementos:
        if count >= max_elements:
            break
        href = el.get(conf.get("link_attr", "href")) or (el.get("href") if el.name == "a" else None)
        text = el.get_text(" ", strip=True)[:200]
        print(f"\n[{count+1}] tag <{el.name}> href: {href}")
        print(f"     texto: {text}")
        print(f"     outerHTML trecho: {str(el)[:400]}")
        if href:
            full = urljoin(conf.get("homepage"), href)
            if full in seen:
                count += 1
                continue
            seen.add(full)
            art_soup, st, _ = obter_soup(full)
            print(f"     -> fetch article status: {st}  url completa: {full}")
            if art_soup:
                # tenta date_selector
                date_raw = None
                ds = conf.get("date_selector")
                if ds:
                    try:
                        node = art_soup.select_one(ds)
                        if node:
                            date_raw = node.get("content") or node.get("datetime") or node.get_text(strip=True)
                    except Exception as e:
                        print(f"     erro applying date_selector '{ds}': {e}")
                if not date_raw:
                    date_raw = extrair_data_meta(art_soup)
                print(f"     date_raw encontrado: {date_raw}")
                print(f"     heurística hoje? {is_date_today(date_raw)}")
        count += 1
        time.sleep(0.6)

def debug_g1_api(conf):
    print("\n" + "="*80)
    print(f"G1 API: {conf.get('name')}  | api_url: {conf.get('api_url')}")
    try:
        r = requests.get(conf.get("api_url"), headers=HEADERS, timeout=12)
        r.raise_for_status()
        data = r.json()
        items = data.get("items", [])
        print(f"Total items returned by API: {len(items)}")
        hoje = datetime.now().date()
        hoje_count = 0
        for i, item in enumerate(items[:20]):
            title = item.get("title")
            published = item.get("published")
            url = item.get("contentUrl")
            print(f"\n[{i+1}] title: {title}")
            print(f"     published: {published}")
            print(f"     url: {url}")
            if published:
                try:
                    dt = datetime.fromisoformat(published.replace("Z", "+00:00")).date()
                    is_today = dt == hoje
                except:
                    is_today = is_date_today(published)
                print(f"     is_today? {is_today}")
                if is_today: hoje_count += 1
        print(f"\nItems from today according to API: {hoje_count}")
    except Exception as e:
        print(f"Erro ao acessar API do G1: {e}")

def main():
    if not os.path.exists(CONFIG_FILE):
        print(f"Arquivo {CONFIG_FILE} não encontrado na pasta atual.")
        return
    confs = carregar_config()
    for conf in confs:
        tipo = conf.get("type", "html")
        if tipo == "g1_api":
            debug_g1_api(conf)
        else:
            debug_html_site(conf, max_elements=6)

if __name__ == "__main__":
    main()
