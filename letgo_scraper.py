# -*- coding: utf-8 -*-
"""
Letgo.com Araç Fotoğraf İndirici
=================================
Infinite scroll ile ilanları toplar, tüm fotoğrafları otomatik indirir.

Kullanım:
    python letgo_scraper.py
"""

import os
import sys
import time
import random
import logging
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests as std_requests
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    InvalidSessionIdException,
)

# ============================================================
# AYARLAR
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DIR = os.path.join(BASE_DIR, "dataset_letgo")
LOG_FILE = os.path.join(BASE_DIR, "letgo.log")

HEDEF_URL = "https://www.letgo.com/arabalar_c15706?filter=kasa-tipi:van"
KLASOR_ADI = "van"

# Scroll
SCROLL_BEKLEME = 2.0        # Her scroll sonrası bekleme (sn)
SCROLL_MAKS_BOS = 5         # Ardışık kaç scroll yeni ilan gelmezse dur
MAKS_ILAN = 0               # 0 = sınırsız

# İlan detay
ILAN_MIN_BEKLEME = 1.0
ILAN_MAKS_BEKLEME = 2.0

# Tarayıcı
HEADLESS = False
PENCERE_GENISLIK = 1920
PENCERE_YUKSEKLIK = 1080
SAYFA_TIMEOUT = 30
YENIDEN_DENEME = 3

# ============================================================
# LOGGING
# ============================================================

def logger_kur() -> logging.Logger:
    logger = logging.getLogger("LetgoScraper")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)

    konsol = logging.StreamHandler(sys.stdout)
    konsol.setLevel(logging.INFO)
    konsol.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(message)s", datefmt="%H:%M:%S"
    ))

    dosya = logging.FileHandler(LOG_FILE, encoding="utf-8")
    dosya.setLevel(logging.DEBUG)
    dosya.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)-8s [%(funcName)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    logger.addHandler(konsol)
    logger.addHandler(dosya)
    return logger


log = logger_kur()

# ============================================================
# YARDIMCI
# ============================================================

def bekle(min_sn: float, maks_sn: float) -> None:
    time.sleep(random.uniform(min_sn, maks_sn))


def klasor_olustur(yol: str) -> None:
    Path(yol).mkdir(parents=True, exist_ok=True)


def ilan_id_cikar(url: str) -> str:
    """Letgo URL'sinden ilan ID'si çıkar.
    Örnek: /item/hyundai-h-100-iid-1727160138 -> 1727160138
    """
    eslesen = re.search(r'iid-(\d+)', url)
    if eslesen:
        return eslesen.group(1)
    parca = url.rstrip("/").split("/")[-1]
    return re.sub(r'[^\w-]', '', parca)[-30:]


def foto_indir(url: str, kayit_yolu: str) -> bool:
    """Tek bir fotoğrafı indir."""
    for d in range(YENIDEN_DENEME):
        try:
            r = std_requests.get(url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/146.0",
                "Referer": "https://www.letgo.com/",
            })
            if r.status_code == 200 and len(r.content) > 1000:
                with open(kayit_yolu, "wb") as f:
                    f.write(r.content)
                return True
        except Exception:
            if d < YENIDEN_DENEME - 1:
                bekle(0.5, 1)
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
        options.add_argument(f"--window-size={PENCERE_GENISLIK},{PENCERE_YUKSEKLIK}")
        if HEADLESS:
            options.add_argument("--headless=new")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--lang=tr-TR")

        self.driver = uc.Chrome(options=options, version_main=146)
        self.driver.set_page_load_timeout(SAYFA_TIMEOUT)
        self.driver.implicitly_wait(5)
        log.info("Chrome hazır.")

    def git(self, url: str) -> bool:
        for i in range(YENIDEN_DENEME):
            try:
                if not self._oturum_ok():
                    self._yeniden_baslat()
                self.driver.get(url)
                bekle(1, 2)
                return True
            except TimeoutException:
                log.warning(f"Zaman aşımı ({i+1}/{YENIDEN_DENEME})")
                if i < YENIDEN_DENEME - 1:
                    bekle(3, 5)
            except (InvalidSessionIdException, WebDriverException) as h:
                log.error(f"Tarayıcı hatası ({i+1}/{YENIDEN_DENEME}): {type(h).__name__}")
                if i < YENIDEN_DENEME - 1:
                    self._yeniden_baslat()
                    bekle(2, 4)
        return False

    def _oturum_ok(self) -> bool:
        try:
            _ = self.driver.current_url
            return True
        except Exception:
            return False

    def _yeniden_baslat(self):
        log.warning("Tarayıcı yeniden başlatılıyor...")
        self.kapat()
        time.sleep(2)
        self.baslat()

    def kapat(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None


# ============================================================
# İLAN TOPLAYICI (Infinite Scroll)
# ============================================================

def ilan_linklerini_topla(driver) -> list[str]:
    """Sayfadaki tüm ilan linklerini çıkar.
    Pattern: /item/...-iid-NUMARA
    """
    js = """
    var links = [];
    var seen = new Set();
    document.querySelectorAll('a[href*="/item/"]').forEach(function(a) {
        var href = a.href;
        if (href && href.indexOf('iid-') > -1 && !seen.has(href)) {
            seen.add(href);
            links.push(href);
        }
    });
    return links;
    """
    try:
        return driver.execute_script(js) or []
    except Exception as h:
        log.debug(f"Link toplama hatası: {h}")
        return []


def scroll_ile_topla(tarayici: Tarayici) -> list[str]:
    """Infinite scroll ile tüm ilanları topla."""
    driver = tarayici.driver
    gorulen = set()
    tum_linkler = []
    ardisik_bos = 0

    log.info("Infinite scroll başlıyor...")

    while True:
        # Mevcut linkleri al
        linkler = ilan_linklerini_topla(driver)
        yeni = [l for l in linkler if l not in gorulen]

        for l in yeni:
            gorulen.add(l)
            tum_linkler.append(l)

        if yeni:
            ardisik_bos = 0
            log.info(f"  +{len(yeni)} yeni ilan, toplam {len(tum_linkler)}")
        else:
            ardisik_bos += 1

        # Limit kontrolü
        if MAKS_ILAN > 0 and len(tum_linkler) >= MAKS_ILAN:
            log.info(f"Maks ilan limitine ulaşıldı ({MAKS_ILAN}).")
            break

        if ardisik_bos >= SCROLL_MAKS_BOS:
            log.info(f"Ardışık {SCROLL_MAKS_BOS} scroll'da yeni ilan yok, durduruluyor.")
            break

        # Aşağı scroll
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        bekle(SCROLL_BEKLEME, SCROLL_BEKLEME + 1)

    log.info(f"Toplam {len(tum_linkler)} ilan toplandı.")
    return tum_linkler


# ============================================================
# FOTOĞRAF BULUCU
# ============================================================

def fotolari_bul(driver) -> list[str]:
    """İlan detay sayfasındaki galeri fotoğraf URL'lerini çıkar.
    Galeri resimleri: class içinde 'cursor-pointer' ve 'object-contain',
    URL pattern: imvm.letgo.com/v1/files/{id}-OLXAUTOTR/image;s=780x780
    Boyutu 1024x1024'e yükselt.
    """
    js = """
    var urls = [];
    var seen = new Set();
    // Galeri resimleri — 780x780 boyutlu, cursor-pointer class'lı
    document.querySelectorAll('img.cursor-pointer[src*="OLXAUTOTR"]').forEach(function(img) {
        var src = img.src || '';
        if (src && !seen.has(src) && src.indexOf('v1/files') > -1) {
            // thumbnail'ları (100x100) atla
            if (src.indexOf('s=100x100') > -1) return;
            seen.add(src);
            // 780x780 -> 1024x1024 yükselt
            src = src.replace(/;s=\\d+x\\d+/, ';s=1024x1024');
            urls.push(src);
        }
    });
    // Fallback: tüm OLXAUTOTR resimleri (thumbnail hariç)
    if (urls.length === 0) {
        document.querySelectorAll('img[src*="OLXAUTOTR"]').forEach(function(img) {
            var src = img.src || '';
            if (src && src.indexOf('v1/files') > -1 && src.indexOf('s=100x100') === -1 && !seen.has(src)) {
                seen.add(src);
                src = src.replace(/;s=\\d+x\\d+/, ';s=1024x1024');
                urls.push(src);
            }
        });
    }
    return urls;
    """
    try:
        urls = driver.execute_script(js) or []
        # Deduplicate by file ID
        temiz = []
        gorulen_id = set()
        for u in urls:
            # /v1/files/ABCD-OLXAUTOTR/ -> ABCD
            eslesen = re.search(r'/files/([a-f0-9]+)-', u)
            fid = eslesen.group(1) if eslesen else u
            if fid not in gorulen_id:
                gorulen_id.add(fid)
                temiz.append(u)
        log.info(f"İlanda {len(temiz)} fotoğraf bulundu.")
        return temiz
    except Exception as h:
        log.error(f"Fotoğraf bulma hatası: {h}")
        return []


# ============================================================
# ANA İŞLEM
# ============================================================

def calistir():
    klasor_olustur(DATASET_DIR)
    kayit_dir = os.path.join(DATASET_DIR, KLASOR_ADI)
    klasor_olustur(kayit_dir)

    tarayici = Tarayici()
    tarayici.baslat()

    # Sayfaya git
    log.info(f"Hedef: {HEDEF_URL}")
    if not tarayici.git(HEDEF_URL):
        log.error("Sayfa açılamadı!")
        tarayici.kapat()
        return

    bekle(3, 5)  # Sayfa tam yüklensin

    # Popup/modal kapat
    try:
        tarayici.driver.execute_script("""
        document.querySelectorAll('[class*="close"], [class*="dismiss"], [aria-label="Close"], [class*="popup"] button').forEach(function(b) { b.click(); });
        """)
        bekle(1, 2)
    except Exception:
        pass

    # Scroll ile ilanları topla
    linkler = scroll_ile_topla(tarayici)

    if not linkler:
        log.error("Hiç ilan bulunamadı!")
        tarayici.kapat()
        return

    print("=" * 60)
    log.info(f"{len(linkler)} ilan işlenecek. İndirme başlıyor...")

    indirilen_toplam = 0
    islenen = 0

    for sira, ilan_url in enumerate(linkler):
        ilan_id = ilan_id_cikar(ilan_url)
        ilan_klasoru = os.path.join(kayit_dir, ilan_id)

        # Zaten var mı?
        if os.path.exists(ilan_klasoru):
            mevcut = len([f for f in os.listdir(ilan_klasoru)
                          if f.endswith(('.jpg', '.png', '.webp'))])
            if mevcut >= 1:
                islenen += 1
                continue

        log.info(f"[{sira+1}/{len(linkler)}] {ilan_id}")

        if not tarayici.git(ilan_url):
            log.warning(f"  Sayfa yüklenemedi, atlıyorum.")
            continue

        bekle(ILAN_MIN_BEKLEME, ILAN_MAKS_BEKLEME)

        # Popup kapat
        try:
            tarayici.driver.execute_script("""
            document.querySelectorAll('[class*="close"], [class*="dismiss"], [aria-label="Close"]').forEach(function(b) { b.click(); });
            """)
        except Exception:
            pass

        fotolar = fotolari_bul(tarayici.driver)
        if not fotolar:
            log.info(f"  Fotoğraf yok, atlıyorum.")
            continue

        klasor_olustur(ilan_klasoru)
        indirilen = 0
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {}
            for i, foto_url in enumerate(fotolar):
                uzanti = ".jpg"
                if ".png" in foto_url.lower():
                    uzanti = ".png"
                elif ".webp" in foto_url.lower():
                    uzanti = ".webp"
                dosya = os.path.join(ilan_klasoru, f"foto_{i+1}{uzanti}")
                futures[pool.submit(foto_indir, foto_url, dosya)] = dosya
            for f in as_completed(futures):
                if f.result():
                    indirilen += 1

        indirilen_toplam += indirilen
        islenen += 1
        log.info(f"  {indirilen}/{len(fotolar)} foto indirildi. [Toplam: {indirilen_toplam}]")

    tarayici.kapat()
    print("=" * 60)
    log.info(f"BİTTİ! {islenen} ilan işlendi, {indirilen_toplam} fotoğraf indirildi.")
    log.info(f"Klasör: {os.path.abspath(kayit_dir)}")


if __name__ == "__main__":
    calistir()
