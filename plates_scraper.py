# -*- coding: utf-8 -*-
"""
PlatesMania.com TR Galeri Scraper
=================================
https://platesmania.com/tr/gallery sayfalarını tarayarak
araç fotoğrafı, plaka resmi ve bilgileri toplar.

Her galeri sayfasından tek seferde tüm bilgiler çekilir (detay sayfasına girmez).
Fotoğraflar + plaka resmi + bilgi txt dosyası kaydedilir.

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

import undetected_chromedriver as uc
from selenium.common.exceptions import TimeoutException, WebDriverException

# ============================================================
# AYARLAR
# ============================================================

DATASET_DIR = "dataset_plates"
GALERI_URL = "https://platesmania.com/tr/gallery"
# gallery, gallery-1, gallery-2, ...

# Tarayıcı
HEADLESS = False
PENCERE_GENISLIK = 1920
PENCERE_YUKSEKLIK = 1080
SAYFA_TIMEOUT = 30

# Hız ayarları
SAYFA_BEKLEME_MIN = 3.0   # Sayfa yüklenmesi
SAYFA_BEKLEME_MAKS = 5.0
COOLDOWN_HER = 20          # Her 20 sayfada mola
COOLDOWN_SURE = 10         # 10 sn mola

# Kaç sayfa taranacak (0 = tümü)
MAKS_SAYFA = 0

# İndirme
INDIRME_PARALEL = 8
INDIRME_TIMEOUT = 15

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Referer": "https://platesmania.com/",
}

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

def bekle(min_sn: float, maks_sn: float) -> None:
    time.sleep(random.uniform(min_sn, maks_sn))


def klasor_olustur(yol: str) -> None:
    Path(yol).mkdir(parents=True, exist_ok=True)


def dosya_indir(url: str, kayit_yolu: str) -> bool:
    """URL'den dosya indir."""
    try:
        r = requests.get(url, timeout=INDIRME_TIMEOUT, headers=HEADERS)
        if r.status_code == 200 and len(r.content) > 500:
            with open(kayit_yolu, "wb") as f:
                f.write(r.content)
            return True
    except Exception:
        pass
    return False


# ============================================================
# TARAYICI
# ============================================================

class Tarayici:
    def __init__(self):
        self.driver = None

    def baslat(self):
        log.info("Chrome başlatılıyor...")
        options = uc.ChromeOptions()
        if HEADLESS:
            options.add_argument("--headless=new")
        options.add_argument(f"--window-size={PENCERE_GENISLIK},{PENCERE_YUKSEKLIK}")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--lang=tr-TR")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")

        self.driver = uc.Chrome(options=options)
        self.driver.set_page_load_timeout(SAYFA_TIMEOUT)
        self.driver.implicitly_wait(5)
        log.info("Chrome hazır.")

    def git(self, url: str) -> bool:
        for deneme in range(3):
            try:
                self.driver.get(url)
                return True
            except TimeoutException:
                log.warning(f"  Timeout ({deneme+1}/3)")
            except WebDriverException as e:
                log.warning(f"  Hata ({deneme+1}/3): {str(e)[:80]}")
            bekle(2, 3)
        return False

    def kapat(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None


# ============================================================
# GALERİ SAYFASINDAN VERİ ÇEK
# ============================================================

def galeri_verisi_cek(driver) -> list[dict]:
    """Galeri sayfasındaki tüm panellerden veri çek."""
    try:
        items = driver.execute_script("""
        var items = [];
        var panels = document.querySelectorAll('.panel');
        for(var i=0; i<panels.length; i++){
            var p = panels[i];
            var item = {};
            // Ana fotoğraf
            var img = p.querySelector('img[src*="/m/"]');
            if(!img) continue;
            item.img_url = img.src;
            item.alt = img.alt || '';
            // Link ve ID
            var a = p.querySelector('a[href*="/nomer"]');
            if(!a) continue;
            item.url = a.href;
            var m = item.url.match(/nomer(\\d+)/);
            item.id = m ? m[1] : '';
            if(!item.id) continue;
            // Plaka resmi
            var plateImg = p.querySelector('img[src*="inf"]');
            item.plaka_img_url = plateImg ? plateImg.src : '';
            item.plaka = plateImg ? (plateImg.alt || '') : '';
            // Tüm metin (araç bilgisi, konum, tarih)
            item.text = p.innerText.trim().replace(/\\s+/g, ' ').substring(0, 300);
            items.push(item);
        }
        return items;
        """)
        return items or []
    except Exception as h:
        log.error(f"Veri çekme hatası: {h}")
        return []


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

def calistir():
    klasor_olustur(DATASET_DIR)

    tarayici = Tarayici()
    tarayici.baslat()

    session = requests.Session()
    session.headers.update(HEADERS)

    toplam_kayit = 0
    toplam_yeni = 0
    sayfa_no = 0
    ardisik_bos = 0

    while True:
        # URL oluştur
        if sayfa_no == 0:
            url = GALERI_URL
        else:
            url = f"{GALERI_URL}-{sayfa_no}"

        log.info(f"Sayfa {sayfa_no + 1}: {url}")

        if not tarayici.git(url):
            log.warning(f"Sayfa açılamadı, atlıyorum.")
            ardisik_bos += 1
            if ardisik_bos >= 5:
                log.error("Ardışık 5 sayfa açılamadı, durduruluyor.")
                break
            sayfa_no += 1
            continue

        bekle(SAYFA_BEKLEME_MIN, SAYFA_BEKLEME_MAKS)

        # Galeri verisi çek
        items = galeri_verisi_cek(tarayici.driver)

        if not items:
            ardisik_bos += 1
            log.warning(f"  Veri yok (ardışık boş: {ardisik_bos})")
            if ardisik_bos >= 5:
                log.info("Ardışık 5 boş sayfa, galeri sonu.")
                break
            sayfa_no += 1
            continue

        ardisik_bos = 0
        log.info(f"  {len(items)} kayıt bulundu.")

        # Paralel indir + kaydet
        yeni = 0
        with ThreadPoolExecutor(max_workers=INDIRME_PARALEL) as pool:
            futures = {pool.submit(kayit_isle, item, session): item["id"] for item in items}
            for f in as_completed(futures):
                item_id, ok = f.result()
                if ok:
                    yeni += 1

        toplam_kayit += len(items)
        toplam_yeni += yeni
        log.info(f"  {yeni} kayıt işlendi. [Toplam: {toplam_kayit} kayıt, {toplam_yeni} yeni]")

        sayfa_no += 1

        # Maks sayfa kontrolü
        if MAKS_SAYFA > 0 and sayfa_no >= MAKS_SAYFA:
            log.info(f"Maks sayfa limitine ulaşıldı ({MAKS_SAYFA}).")
            break

        # Mola
        if sayfa_no % COOLDOWN_HER == 0:
            log.info(f"  Mola ({COOLDOWN_SURE}sn)...")
            time.sleep(COOLDOWN_SURE)

    tarayici.kapat()
    print("=" * 60)
    log.info(f"BİTTİ! {toplam_kayit} kayıt tarandı, {toplam_yeni} yeni işlendi.")
    log.info(f"Klasör: {os.path.abspath(DATASET_DIR)}")


if __name__ == "__main__":
    calistir()
