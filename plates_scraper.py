# -*- coding: utf-8 -*-
"""
PlatesMania.com TR Galeri Scraper (HIZLI)
==========================================
Selenium ile 1 kez captcha bypass → cookie'lerle requests ile paralel tarama.
Her galeri sayfasından tek seferde tüm bilgiler çekilir (detay sayfasına girmez).

Klasör yapısı:
    dataset_plates/{id}/
        foto.jpg          (araç fotoğrafı)
        plaka.png         (plaka resmi)
        bilgi.txt         (araç bilgileri)

Kullanım:
    python plates_scraper.py
"""

import os
import sys
import time
import random
import logging
import re
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from bs4 import BeautifulSoup
import undetected_chromedriver as uc

# ============================================================
# AYARLAR
# ============================================================

DATASET_DIR = "dataset_plates"
GALERI_URL = "https://platesmania.com/tr/gallery"

# Hız ayarları
SAYFA_PARALEL = 4          # Aynı anda kaç sayfa çekilsin
INDIRME_PARALEL = 12       # Aynı anda kaç dosya indirilsin
SAYFA_BEKLEME = 0.3        # Sayfalar arası bekleme (sn)
COOLDOWN_HER = 200         # Her 200 sayfada mola
COOLDOWN_SURE = 10         # 10 sn mola
INDIRME_TIMEOUT = 15
MAKS_SAYFA = 0             # 0 = tümü

# ============================================================
# LOG
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("plates")

# ============================================================
# YARDIMCILAR
# ============================================================

def klasor_olustur(yol: str) -> None:
    Path(yol).mkdir(parents=True, exist_ok=True)


# ============================================================
# CAPTCHA BYPASS — Selenium ile cookie al
# ============================================================

def cookie_al() -> tuple[dict, str]:
    """Selenium ile captcha bypass edip cookie ve user-agent al."""
    log.info("Chrome ile captcha bypass ediliyor...")
    options = uc.ChromeOptions()
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--lang=tr-TR")

    driver = uc.Chrome(options=options)
    driver.get(GALERI_URL)
    time.sleep(12)  # Captcha çözülmesini bekle

    # Cookie ve UA al
    cookies = {c["name"]: c["value"] for c in driver.get_cookies()}
    ua = driver.execute_script("return navigator.userAgent")

    # Doğrulama — gerçek içerik yüklendi mi?
    has_data = driver.execute_script("return document.querySelectorAll('.panel').length > 0")
    driver.quit()

    if not has_data:
        log.error("Captcha geçilemedi! Chrome'da manuel olarak sayfayı açıp tekrar deneyin.")
        sys.exit(1)

    log.info(f"Captcha geçildi! {len(cookies)} cookie alındı.")
    return cookies, ua


def session_olustur(cookies: dict, ua: str) -> requests.Session:
    """Cookie'lerle requests session oluştur."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
        "Referer": "https://platesmania.com/tr/gallery",
    })
    for k, v in cookies.items():
        session.cookies.set(k, v, domain=".platesmania.com")
    return session


# ============================================================
# GALERİ SAYFASINDAN VERİ ÇEK (BeautifulSoup)
# ============================================================

def galeri_sayfasi_cek(session: requests.Session, sayfa_no: int) -> list[dict]:
    """Tek bir galeri sayfasını requests ile çek ve parse et."""
    if sayfa_no == 0:
        url = GALERI_URL
    else:
        url = f"{GALERI_URL}-{sayfa_no}"

    try:
        r = session.get(url, timeout=15)
        if r.status_code != 200:
            return []
    except Exception:
        return []

    soup = BeautifulSoup(r.text, "lxml")
    items = []

    for panel in soup.select(".panel"):
        item = {}

        # Ana fotoğraf
        img = panel.select_one('img[src*="/m/"]')
        if not img:
            continue
        item["img_url"] = img.get("src", "")
        item["alt"] = img.get("alt", "")

        # Link ve ID
        a = panel.select_one('a[href*="/nomer"]')
        if not a:
            continue
        item["url"] = a.get("href", "")
        if not item["url"].startswith("http"):
            item["url"] = "https://platesmania.com" + item["url"]
        m = re.search(r"nomer(\d+)", item["url"])
        if not m:
            continue
        item["id"] = m.group(1)

        # Plaka resmi
        plate_img = panel.select_one('img[src*="inf"]')
        item["plaka_img_url"] = plate_img.get("src", "") if plate_img else ""
        item["plaka"] = plate_img.get("alt", "") if plate_img else ""

        # Tüm metin
        item["text"] = " ".join(panel.get_text().split())[:300]

        items.append(item)

    return items


def bilgi_parse(item: dict) -> dict:
    """Ham text'ten araç bilgilerini ayıkla."""
    text = item.get("text", "")
    bilgi = {
        "id": item.get("id", ""),
        "plaka": item.get("plaka", ""),
        "url": item.get("url", ""),
    }

    # Text pattern: "Türkiye {Araç Modeli} Spotted in {Konum} {Tarih} {Kullanıcı} {TarihSaat} {Beğeni} {Yorum}"
    # veya: "Türkiye {Araç Modeli} {Ek Bilgi} {Kullanıcı} {TarihSaat} ..."

    # Araç modelini çıkar
    # Genelde "Türkiye" ile başlıyor, sonra araç modeli
    parts = text.split("Spotted in")
    if len(parts) >= 2:
        # İlk kısım: "Türkiye {Model}"
        model_part = parts[0].replace("Türkiye", "").strip()
        bilgi["model"] = model_part

        # İkinci kısım: "{Konum} {Tarih} ..."
        loc_part = parts[1].strip()
        # Tarih pattern: DD.MM.YYYY
        tarih_match = re.search(r'(\d{2}\.\d{2}\.\d{4})', loc_part)
        if tarih_match:
            konum = loc_part[:tarih_match.start()].strip()
            bilgi["konum"] = konum
            bilgi["tarih"] = tarih_match.group(1)
        else:
            bilgi["konum"] = loc_part[:50]
    else:
        # "Spotted in" yoksa kullanıcı adı/tarih saat'ten önceki kısmı al
        model_part = text.replace("Türkiye", "").strip()
        # Tarih-saat pattern ile kes: "2026-04-13 17:19:29"
        dt_match = re.search(r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}', model_part)
        if dt_match:
            # Kullanıcı adı tarihten hemen önce gelir
            before = model_part[:dt_match.start()].strip()
            # Son kelime kullanıcı adı, ondan öncesi model
            words = before.rsplit(" ", 1)
            bilgi["model"] = words[0] if len(words) > 1 else before
        else:
            bilgi["model"] = model_part[:100]

    return bilgi


def bilgi_txt_yaz(klasor: str, bilgi: dict) -> None:
    """Bilgileri txt dosyasına yaz."""
    dosya = os.path.join(klasor, "bilgi.txt")
    with open(dosya, "w", encoding="utf-8") as f:
        f.write(f"ID: {bilgi.get('id', '')}\n")
        f.write(f"Plaka: {bilgi.get('plaka', '')}\n")
        if bilgi.get("model"):
            f.write(f"Araç: {bilgi['model']}\n")
        if bilgi.get("konum"):
            f.write(f"Konum: {bilgi['konum']}\n")
        if bilgi.get("tarih"):
            f.write(f"Tarih: {bilgi['tarih']}\n")
        f.write(f"URL: {bilgi.get('url', '')}\n")


# ============================================================
# TEK KAYIT İŞLE
# ============================================================

def kayit_isle(item: dict, session: requests.Session) -> tuple[str, bool]:
    """Tek bir galeri kaydını işle: fotoğraf indir + bilgi yaz."""
    item_id = item["id"]
    klasor = os.path.join(DATASET_DIR, item_id)

    # Zaten var mı?
    bilgi_yol = os.path.join(klasor, "bilgi.txt")
    if os.path.exists(bilgi_yol):
        return (item_id, True)

    klasor_olustur(klasor)

    # Bilgi yaz
    bilgi = bilgi_parse(item)
    bilgi_txt_yaz(klasor, bilgi)

    # Fotoğraf indir
    foto_yol = os.path.join(klasor, "foto.jpg")
    if not os.path.exists(foto_yol) and item.get("img_url"):
        # /m/ -> /o/ (orijinal boyut)
        orijinal_url = item["img_url"].replace("/m/", "/o/")
        try:
            r = session.get(orijinal_url, timeout=INDIRME_TIMEOUT, headers=HEADERS)
            if r.status_code == 200 and len(r.content) > 1000:
                with open(foto_yol, "wb") as f:
                    f.write(r.content)
            else:
                # Orijinal yoksa medium kullan
                r = session.get(item["img_url"], timeout=INDIRME_TIMEOUT, headers=HEADERS)
                if r.status_code == 200 and len(r.content) > 1000:
                    with open(foto_yol, "wb") as f:
                        f.write(r.content)
        except Exception:
            pass

    # Plaka resmi indir
    plaka_yol = os.path.join(klasor, "plaka.png")
    if not os.path.exists(plaka_yol) and item.get("plaka_img_url"):
        try:
            r = session.get(item["plaka_img_url"], timeout=INDIRME_TIMEOUT, headers=HEADERS)
            if r.status_code == 200 and len(r.content) > 500:
                with open(plaka_yol, "wb") as f:
                    f.write(r.content)
        except Exception:
            pass

    return (item_id, True)


# ============================================================
# ANA İŞLEM
# ============================================================

def batch_sayfa_cek(session: requests.Session, sayfa_numaralari: list[int]) -> list[dict]:
    """Birden fazla galeri sayfasını paralel çek."""
    tum_items = []
    with ThreadPoolExecutor(max_workers=SAYFA_PARALEL) as pool:
        futures = {pool.submit(galeri_sayfasi_cek, session, no): no for no in sayfa_numaralari}
        for f in as_completed(futures):
            items = f.result()
            tum_items.extend(items)
    return tum_items


def batch_kayit_isle(items: list[dict], session: requests.Session) -> int:
    """Birden fazla kaydı paralel indir + kaydet."""
    yeni = 0
    with ThreadPoolExecutor(max_workers=INDIRME_PARALEL) as pool:
        futures = {pool.submit(kayit_isle, item, session): item["id"] for item in items}
        for f in as_completed(futures):
            _, ok = f.result()
            if ok:
                yeni += 1
    return yeni


def calistir():
    klasor_olustur(DATASET_DIR)

    # 1. Selenium ile captcha bypass
    cookies, ua = cookie_al()
    session = session_olustur(cookies, ua)

    # 2. İlk sayfayı test et
    test = galeri_sayfasi_cek(session, 1)
    if not test:
        log.error("Cookie'ler çalışmıyor! Tekrar deneyin.")
        return
    log.info(f"Test başarılı: {len(test)} kayıt bulundu.")

    toplam_kayit = 0
    toplam_yeni = 0
    sayfa_no = 0
    ardisik_bos = 0
    batch_boyut = 10  # Her turda 10 sayfa paralel çek

    baslangic = time.time()

    while True:
        # Batch oluştur
        sayfa_listesi = list(range(sayfa_no, sayfa_no + batch_boyut))

        # Paralel sayfa çek
        items = batch_sayfa_cek(session, sayfa_listesi)

        if not items:
            ardisik_bos += 1
            if ardisik_bos >= 3:
                log.info("Ardışık 3 boş batch, galeri sonu.")
                break
            sayfa_no += batch_boyut
            continue

        ardisik_bos = 0

        # Paralel indir + kaydet
        yeni = batch_kayit_isle(items, session)

        toplam_kayit += len(items)
        toplam_yeni += yeni
        sayfa_no += batch_boyut

        gecen = time.time() - baslangic
        hiz = toplam_kayit / gecen if gecen > 0 else 0
        log.info(f"Sayfa {sayfa_no}: {len(items)} kayıt, {yeni} yeni | "
                 f"Toplam: {toplam_kayit} kayıt, {toplam_yeni} yeni | "
                 f"Hız: {hiz:.0f} kayıt/sn")

        # Maks sayfa kontrolü
        if MAKS_SAYFA > 0 and sayfa_no >= MAKS_SAYFA:
            log.info(f"Maks sayfa limitine ulaşıldı ({MAKS_SAYFA}).")
            break

        # Mola
        if sayfa_no % COOLDOWN_HER == 0:
            log.info(f"  Mola ({COOLDOWN_SURE}sn)...")
            time.sleep(COOLDOWN_SURE)

        time.sleep(SAYFA_BEKLEME)

    gecen_toplam = time.time() - baslangic
    print("=" * 60)
    log.info(f"BİTTİ! {toplam_kayit} kayıt tarandı, {toplam_yeni} yeni işlendi.")
    log.info(f"Süre: {gecen_toplam/60:.1f} dakika | Hız: {toplam_kayit/gecen_toplam:.0f} kayıt/sn")
    log.info(f"Klasör: {os.path.abspath(DATASET_DIR)}")


if __name__ == "__main__":
    calistir()
