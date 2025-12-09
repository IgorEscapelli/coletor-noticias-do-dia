# app.py
from flask import Flask, render_template, redirect, url_for, send_file, flash
import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime
from urllib.parse import urljoin
import time
import xml.etree.ElementTree as ET

app = Flask(__name__)
app.secret_key = "troque_esta_chave_para_algo_secreto"

CONFIG_FILE = "config_sites.json"
OUTPUT_FILE = "noticias_do_dia.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (NewsScraperBot/1.0)"}


def carregar_config():
    if not os.path.exists(CONFIG_FILE):
        exemplo = [
            {
                "name": "Fala São João",
                "type": "html",
                "homepage": "https://falasaojoao.com.br/category/noticias/",
                "article_selector": ".td-block-span6 a, .entry-title a",
                "link_attr": "href",
                "date_selector": "time",
                "date_is_meta": False
            },
            {
                "name": "O Municipio",
                "type": "rss",
                "rss_url": "https://www.omunicipio.jor.br/feed/"
            },
            {
                "name": "SãoJoãoSP Oficial",
                "type": "rss",
                "rss_url": "https://www.saojoao.sp.gov.br/feed/"
            },
            {
                "name": "G1 São Carlos",
                "type": "rss",
                "rss_url": "https://g1.globo.com/rss/g1/sp/sao-carlos-regiao/"
            }
        ]
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(exemplo, f, ensure_ascii=False, indent=2)
        return exemplo
    else:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)


def obter_soup(url, timeout=12):
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def extrair_data_meta(soup):
    if not soup:
        return None
    for m in soup.find_all("meta"):
        prop = (m.get("property") or "").lower()
        name = (m.get("name") or "").lower()
        if prop in ("article:published_time", "og:published_time") or name in (
            "pubdate", "publishdate", "timestamp", "date", "article:published_time"):
            if m.get("content"):
                return m["content"]
    time_tag = soup.find("time")
    if time_tag and time_tag.get("datetime"):
        return time_tag["datetime"]
    if time_tag:
        return time_tag.get_text(strip=True)
    return None


def extrair_data_texto(texto):
    if not texto:
        return False
    texto = str(texto)
    hoje = datetime.now().date()
    # heurística simples: contém ano atual, ou dia/mês
    if str(hoje.year) in texto:
        return True
    if hoje.strftime("%d/%m") in texto or hoje.strftime("%d-%m") in texto:
        return True
    if hoje.strftime("%d") in texto:
        return True
    return False


def parse_article(url, site_conf=None):
    try:
        soup = obter_soup(url)
    except Exception as e:
        print(f"Erro ao baixar artigo {url}: {e}")
        return None

    titulo = soup.find("h1").get_text(strip=True) if soup.find("h1") else (soup.title.get_text(strip=True) if soup.title else None)

    data = None
    if site_conf and site_conf.get("date_selector"):
        try:
            sel = soup.select_one(site_conf["date_selector"])
            if sel:
                if site_conf.get("date_is_meta"):
                    data = sel.get("content") or sel.get("datetime") or sel.get_text(strip=True)
                else:
                    data = sel.get_text(strip=True)
        except Exception:
            data = None

    if not data:
        data = extrair_data_meta(soup)

    # conteúdo simples: article > entry-content > body
    conteudo = None
    possible = soup.select_one("article")
    if possible:
        conteudo = str(possible)
    else:
        div = soup.select_one(".entry-content") or soup.select_one(".content") or soup.body
        conteudo = str(div) if div else None

    imagem = None
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        imagem = og.get("content")

    return {
        "url": url,
        "title": titulo,
        "date_raw": data,
        "content_html": conteudo,
        "image": imagem
    }


def buscar_noticias_do_site(site_conf, limite_por_site=15):
    resultados = []
    # proteção: requer 'homepage'
    if "homepage" not in site_conf or not site_conf.get("homepage"):
        print(f"Pulando {site_conf.get('name')} — sem 'homepage' na config.")
        return resultados

    try:
        soup = obter_soup(site_conf["homepage"])
    except Exception as e:
        print(f"Erro carregando homepage {site_conf.get('homepage')}: {e}")
        return resultados

    sel = site_conf.get("article_selector") or ""
    try:
        elementos = soup.select(sel) if sel else []
    except Exception as e:
        print(f"Erro aplicando selector '{sel}' em {site_conf.get('name')}: {e}")
        elementos = []

    seen = set()
    for el in elementos:
        if len(resultados) >= limite_por_site:
            break
        link = el.get(site_conf.get("link_attr", "href")) or (el.get("href") if el.name == "a" else None)
        if not link:
            continue
        full = urljoin(site_conf["homepage"], link)
        if full in seen:
            continue
        seen.add(full)

        art = parse_article(full, site_conf)
        if not art:
            continue

        # checar se é do dia
        data_ok = False
        data_raw = art.get("date_raw")
        if data_raw and extrair_data_texto(str(data_raw)):
            data_ok = True
        else:
            # fallback: título ou url contendo dia/mês
            hoje = datetime.now()
            dia = hoje.strftime("%d")
            mes = hoje.strftime("%m")
            tit = (art.get("title") or "").lower()
            if dia in tit or f"{dia}/{mes}" in tit or f"{dia}-{mes}" in tit:
                data_ok = True

        if data_ok:
            art["site"] = site_conf.get("name")
            resultados.append(art)

        time.sleep(0.6)

    return resultados


def buscar_g1_api(api_url):
    try:
        resp = requests.get(api_url, headers=HEADERS, timeout=12)
        resp.raise_for_status()
        data = resp.json()
        noticias = []
        hoje = datetime.now().date()
        for item in data.get("items", []):
            published = item.get("published")
            if not published:
                continue
            try:
                dt = datetime.fromisoformat(published.replace("Z", "+00:00")).date()
            except:
                continue
            if dt == hoje:
                noticias.append({
                    "title": item.get("title"),
                    "url": item.get("contentUrl"),
                    "image": item.get("image"),
                    "date_raw": published,
                    "content_html": None,
                    "site": "G1 (API)"
                })
        return noticias
    except Exception as e:
        print(f"Erro ao acessar API do G1: {e}")
        return []


def buscar_rss(rss_url, site_nome):
    noticias = []
    hoje = datetime.now().date()
    try:
        resp = requests.get(rss_url, headers=HEADERS, timeout=12)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        for item in root.findall(".//item"):
            title = item.findtext("title")
            link = item.findtext("link")
            pub_date = item.findtext("pubDate")
            dt = None
            if pub_date:
                try:
                    dt = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %z").date()
                except Exception:
                    # fallback heurística: se contém o ano atual, assume hoje (não ideal)
                    if str(hoje.year) in pub_date:
                        dt = hoje
            if dt == hoje:
                noticias.append({
                    "title": title,
                    "url": link,
                    "date_raw": pub_date,
                    "content_html": None,
                    "site": site_nome
                })
        return noticias
    except Exception as e:
        print(f"Erro ao acessar RSS {rss_url}: {e}")
        return []


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/buscar")
def buscar():
    config = carregar_config()
    todas = []

    for site in config:
        tipo = site.get("type", "html")

        if tipo == "rss":
            noticias = buscar_rss(site.get("rss_url"), site.get("name"))
            print(f"{site.get('name')}: {len(noticias)} (rss)")

        elif tipo == "g1_api":
            noticias = buscar_g1_api(site.get("api_url"))
            print(f"{site.get('name')}: {len(noticias)} (g1_api)")

        elif tipo == "html":
            noticias = buscar_noticias_do_site(site, limite_por_site=20)
            print(f"{site.get('name')}: {len(noticias)} (html)")

        else:
            print(f"Tipo desconhecido para {site.get('name')}: {tipo}")
            noticias = []

        # dedupe por URL e adicionar
        for n in noticias:
            if not any(existing.get("url") == n.get("url") for existing in todas):
                todas.append(n)

    # limitar (opcional)
    todas = todas[:200]

    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(todas, f, ensure_ascii=False, indent=2)
        flash(f"Busca concluída: {len(todas)} notícias salvas em {OUTPUT_FILE}")
    except Exception as e:
        flash(f"Erro ao salvar arquivo: {e}")

    return redirect(url_for("index"))


@app.route("/download")
def download():
    if os.path.exists(OUTPUT_FILE):
        return send_file(OUTPUT_FILE, as_attachment=True)
    else:
        flash("Nenhum arquivo gerado ainda. Clique em 'Buscar notícias do dia' primeiro.")
        return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
