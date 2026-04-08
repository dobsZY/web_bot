# -*- coding: utf-8 -*-
"""
Arabam.com Otomatik Fotoğraf İndirici
======================================
İlanları tarar, tüm fotoğrafları otomatik indirir.

Kullanım:
    python app.py
"""

import os
import sys
import time
import random
import logging
import re
from pathlib import Path
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests as std_requests
import undetected_chromedriver as uc
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    InvalidSessionIdException,
)
from bs4 import BeautifulSoup

import config

# ============================================================
# LOGGING
# ============================================================

def logger_kur() -> logging.Logger:
    logger = logging.getLogger("ArabamSecici")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)

    konsol = logging.StreamHandler(sys.stdout)
    konsol.setLevel(logging.INFO)
    konsol.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(message)s", datefmt="%H:%M:%S"
    ))

    dosya = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
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


def ilan_no_cikar(url: str) -> str:
    eslesen = re.search(r'/(\d{6,12})(?:\?|$)', url)
    if eslesen:
        return eslesen.group(1)
    return str(abs(hash(url)))[:10]


# ============================================================
# TARAYICI
# ============================================================

class Tarayici:
    def __init__(self):
        self.driver = None

    def baslat(self):
        log.info("Chrome başlatılıyor...")
        options = uc.ChromeOptions()
        options.add_argument(
            f"--window-size={config.PENCERE_GENISLIK},{config.PENCERE_YUKSEKLIK}"
        )
        if config.HEADLESS:
            options.add_argument("--headless=new")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--lang=tr-TR")

        self.driver = uc.Chrome(options=options, version_main=146)
        self.driver.set_page_load_timeout(config.SAYFA_TIMEOUT)
        self.driver.implicitly_wait(5)
        log.info("Chrome hazır.")
        return self.driver

    def git(self, url: str, deneme: int = None) -> bool:
        if deneme is None:
            deneme = config.YENIDEN_DENEME
        for i in range(deneme):
            try:
                if not self._oturum_ok():
                    self._yeniden_baslat()
                self.driver.get(url)
                bekle(config.MIN_BEKLEME, config.MAKS_BEKLEME)
                return True
            except TimeoutException:
                log.warning(f"Zaman aşımı ({i+1}/{deneme})")
                if i < deneme - 1:
                    bekle(3, 5)
            except (InvalidSessionIdException, WebDriverException) as h:
                log.error(f"Tarayıcı hatası ({i+1}/{deneme}): {type(h).__name__}")
                if i < deneme - 1:
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
# İLAN TOPLAYICI
# ============================================================

class IlanToplayici:
    def __init__(self, tarayici: Tarayici):
        self.t = tarayici

    @property
    def driver(self):
        return self.t.driver

    def sayfa_linklerini_al(self) -> list[str]:
        linkler = []
        try:
            soup = BeautifulSoup(self.driver.page_source, "lxml")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/ilan/" in href and re.search(r'/\d{6,12}$', href):
                    tam = urljoin("https://www.arabam.com", href)
                    if tam not in linkler:
                        linkler.append(tam)
            log.info(f"Bu sayfada {len(linkler)} ilan bulundu.")
        except Exception as h:
            log.error(f"Link toplama hatası: {h}")
        return linkler

    def topla(self, kategori_url: str) -> list[str]:
        gorulen = set()
        tum = []
        sayfa = 1
        ardisik_bos = 0

        while True:
            if config.MAKS_SAYFA > 0 and sayfa > config.MAKS_SAYFA:
                log.info(f"Maks sayfa limitine ulaşıldı ({config.MAKS_SAYFA}).")
                break

            sep = "&" if "?" in kategori_url else "?"
            url = f"{kategori_url}{sep}page={sayfa}"
            if not self.t.git(url):
                break

            log.info(f"--- Sayfa {sayfa} ---")
            linkler = self.sayfa_linklerini_al()

            if not linkler:
                log.info("Bu sayfada ilan yok, durduruluyor.")
                break

            yeni = [l for l in linkler if l not in gorulen]

            for l in yeni:
                gorulen.add(l)
                tum.append(l)

            if yeni:
                ardisik_bos = 0
                log.info(f"  → {len(yeni)} yeni, toplam {len(tum)} ilan.")
            else:
                ardisik_bos += 1
                log.info(f"  → Yeni ilan yok (ardışık boş: {ardisik_bos}/3)")
                if ardisik_bos >= 3:
                    log.info("Ardışık 3 sayfada yeni ilan yok, durduruluyor.")
                    break

            sayfa += 1

        log.info(f"Toplam {len(tum)} benzersiz ilan toplandı.")
        return tum


# ============================================================
# FOTOĞRAF BULUCU & İNDİRİCİ
# ============================================================

class FotoIslem:
    def __init__(self, tarayici: Tarayici):
        self.t = tarayici
        self._ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/146.0"
        try:
            self._ua = self.t.driver.execute_script("return navigator.userAgent;")
        except Exception:
            pass

    @property
    def driver(self):
        return self.t.driver

    def foto_bul(self) -> list[str]:
        """Galeri slider'ındaki gerçek araç fotoğraflarını çıkarır."""
        try:
            js = """
            var urls = [];
            var seen = new Set();
            document.querySelectorAll('.swiper-slide:not(.lightbox-swiper_thumbnail) img.swiper-lazy').forEach(function(img) {
                var src = img.dataset.src || img.src || '';
                if (src && src.indexOf('ilanfotograflari') > -1 && !seen.has(src)) {
                    seen.add(src);
                    src = src.replace(/_\\d+x\\d+\\./, '_800x600.');
                    urls.push(src);
                }
            });
            if (urls.length === 0) {
                document.querySelectorAll('img[data-src*="ilanfotograflari"]').forEach(function(img) {
                    var src = img.dataset.src || '';
                    if (src && !seen.has(src)) {
                        seen.add(src);
                        src = src.replace(/_\\d+x\\d+\\./, '_800x600.');
                        urls.push(src);
                    }
                });
            }
            return urls;
            """
            urls = self.driver.execute_script(js) or []

            temiz = []
            gorulen = set()
            for u in urls:
                if '_120x90.' in u or '_240x180.' in u:
                    continue
                if u not in gorulen:
                    gorulen.add(u)
                    temiz.append(u)

            log.info(f"İlanda {len(temiz)} araç fotoğrafı bulundu.")
            return temiz
        except Exception as h:
            log.error(f"Fotoğraf bulma hatası: {h}")
            return []

    def indir(self, url: str, kayit_yolu: str) -> bool:
        """Tek bir fotoğrafı indir (requests ile)."""
        for d in range(config.YENIDEN_DENEME):
            try:
                r = std_requests.get(url, timeout=15, headers={
                    "User-Agent": self._ua,
                    "Referer": "https://www.arabam.com/",
                })
                if r.status_code == 200 and len(r.content) > 1000:
                    with open(kayit_yolu, "wb") as f:
                        f.write(r.content)
                    return True
            except Exception:
                if d < config.YENIDEN_DENEME - 1:
                    bekle(0.5, 1)
        return False


# ============================================================
# ANA İŞLEM
# ============================================================

def calistir():
    klasor_olustur(config.DATASET_DIR)
    kategori = list(config.KATEGORILER.keys())[0]

    # Chrome başlat
    tarayici = Tarayici()
    tarayici.baslat()
    toplayici = IlanToplayici(tarayici)
    foto = FotoIslem(tarayici)

    # İlanları topla
    linkler = []
    for adi, url in config.KATEGORILER.items():
        log.info(f"Kategori: {adi}")
        linkler.extend(toplayici.topla(url))

    toplam = len(linkler)
    log.info(f"Toplam {toplam} ilan. İndirme başlıyor...")
    print("=" * 60)

    indirilen_toplam = 0
    islenen = 0

    for sira, ilan_url in enumerate(linkler):
        ilan_no = ilan_no_cikar(ilan_url)
        ilan_klasoru = os.path.join(config.DATASET_DIR, kategori, ilan_no)

        # Zaten var mı?
        if os.path.exists(ilan_klasoru):
            mevcut = len([f for f in os.listdir(ilan_klasoru)
                          if f.endswith(('.jpg', '.png', '.webp'))])
            if mevcut >= 1:
                islenen += 1
                continue

        log.info(f"[{sira+1}/{toplam}] {ilan_no}")

        if not tarayici.git(ilan_url):
            log.warning(f"  Sayfa yüklenemedi, atlıyorum.")
            continue

        bekle(config.ILAN_MIN_BEKLEME, config.ILAN_MAKS_BEKLEME)

        fotolar = foto.foto_bul()
        if not fotolar:
            log.info(f"  Fotoğraf yok, atlıyorum.")
            continue

        klasor_olustur(ilan_klasoru)
        indirilen = 0
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {}
            for i, foto_url in enumerate(fotolar):
                dosya = os.path.join(ilan_klasoru, f"foto_{i+1}.jpg")
                futures[pool.submit(foto.indir, foto_url, dosya)] = dosya
            for f in as_completed(futures):
                if f.result():
                    indirilen += 1

        indirilen_toplam += indirilen
        islenen += 1
        log.info(f"  {indirilen}/{len(fotolar)} foto indirildi. [Toplam: {indirilen_toplam}]")

    tarayici.kapat()
    print("=" * 60)
    log.info(f"BİTTİ! {islenen} ilan işlendi, {indirilen_toplam} fotoğraf indirildi.")
    log.info(f"Klasör: {os.path.abspath(config.DATASET_DIR)}")


if __name__ == "__main__":
    calistir()
