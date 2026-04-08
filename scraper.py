# -*- coding: utf-8 -*-
"""
Arabam.com Ticari Araç Fotoğraf Scraper
========================================
arabam.com üzerindeki ticari araç ilanlarından
fotoğrafları otomatik indirerek CV veri seti oluşturur.

Kayıt formatı: dataset/{kategori}/{ilan_no}/foto_1.jpg ...

Kullanım:
    python scraper.py
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

import undetected_chromedriver as uc
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    InvalidSessionIdException,
)
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

import config


# ============================================================
# LOGGING
# ============================================================

def logger_kur() -> logging.Logger:
    logger = logging.getLogger("ArabamScraper")
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
    """URL sonundaki sayısal ilan numarasını çıkarır."""
    eslesen = re.search(r'/(\d{6,12})(?:\?|$)', url)
    if eslesen:
        return eslesen.group(1)
    return str(abs(hash(url)))[:10]


# ============================================================
# TARAYICI
# ============================================================

class Tarayici:
    """undetected-chromedriver ile basit Chrome yönetimi."""

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

                log.info(f"Yükleniyor: {url}")
                self.driver.get(url)
                bekle(config.MIN_BEKLEME, config.MAKS_BEKLEME)
                return True

            except TimeoutException:
                log.warning(f"Zaman aşımı ({i+1}/{deneme})")
                if i < deneme - 1:
                    bekle(5, 10)
            except (InvalidSessionIdException, WebDriverException) as h:
                log.error(f"Tarayıcı hatası ({i+1}/{deneme}): {type(h).__name__}")
                if i < deneme - 1:
                    self._yeniden_baslat()
                    bekle(3, 6)

        log.error(f"Sayfa yüklenemedi: {url}")
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
# İLAN TOPLAYICI (arabam.com)
# ============================================================

class IlanToplayici:
    """
    arabam.com kategori sayfalarını tarar, ilan linklerini toplar.
    Sayfalama: ?page=1, ?page=2, ...
    """

    def __init__(self, tarayici: Tarayici):
        self.t = tarayici

    @property
    def driver(self):
        return self.t.driver

    def sayfa_linklerini_al(self) -> list[str]:
        """Mevcut sayfadaki ilan linklerini çıkarır."""
        linkler = []
        try:
            soup = BeautifulSoup(self.driver.page_source, "lxml")

            # arabam.com ilan linkleri: /ilan/.../XXXXXXXX formatında
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
        """Tüm sayfalardaki ilan linklerini toplar."""
        gorulen = set()
        tum = []
        sayfa = 1
        ardisik_bos = 0

        while True:
            # Sayfa limiti varsa kontrol et (0 = sınırsız)
            if config.MAKS_SAYFA > 0 and sayfa > config.MAKS_SAYFA:
                log.info(f"Maks sayfa limitine ulaşıldı ({config.MAKS_SAYFA}).")
                break

            # take=50 zaten URL'de, &page= ekle
            sep = "&" if "?" in kategori_url else "?"
            url = f"{kategori_url}{sep}page={sayfa}"
            if not self.t.git(url):
                break

            log.info(f"--- Sayfa {sayfa} ---")
            linkler = self.sayfa_linklerini_al()

            if not linkler:
                log.info("Bu sayfada ilan yok, durduruluyor.")
                break

            # Sadece yeni (daha önce görülmemiş) linkleri ekle
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
# FOTOĞRAF İNDİRİCİ (arabam.com)
# ============================================================

class FotoIndirici:
    """
    arabam.com ilan detay sayfasından fotoğrafları bulur ve indirir.
    curl_cffi ile TLS parmak izi gizleme kullanır.

    Kayıt: dataset/{kategori}/{ilan_no}/foto_1.jpg, foto_2.jpg, ...
    """

    def __init__(self, tarayici: Tarayici):
        self.t = tarayici
        self._ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/146.0"
        self._ua_guncelle()

    @property
    def driver(self):
        return self.t.driver

    def _ua_guncelle(self):
        try:
            self._ua = self.driver.execute_script("return navigator.userAgent;")
        except Exception:
            pass

    def foto_bul(self) -> list[str]:
        """Galeri slider'ındaki gerçek araç fotoğraflarını çıkarır."""
        try:
            # arabam.com yapısı:
            # - Galeri: swiper-slide içindeki img.swiper-lazy
            # - Thumbnail: swiper-slide.lightbox-swiper_thumbnail (ATLA)
            # - Gerçek foto URL: 'ilanfotograflari' içerir
            # - Büyük boyut: _800x600.jpg
            js = """
            var urls = [];
            var seen = new Set();
            // Ana galeri slide'ları (thumbnail olmayanlar)
            document.querySelectorAll('.swiper-slide:not(.lightbox-swiper_thumbnail) img.swiper-lazy').forEach(function(img) {
                var src = img.dataset.src || img.src || '';
                if (src && src.indexOf('ilanfotograflari') > -1 && !seen.has(src)) {
                    seen.add(src);
                    // Küçük boyutu büyüğe çevir
                    src = src.replace(/_\d+x\d+\./, '_800x600.');
                    urls.push(src);
                }
            });
            // Fallback: data-src ile tüm slider resimlerini tara
            if (urls.length === 0) {
                document.querySelectorAll('img[data-src*="ilanfotograflari"]').forEach(function(img) {
                    var src = img.dataset.src || '';
                    if (src && !seen.has(src)) {
                        seen.add(src);
                        src = src.replace(/_\d+x\d+\./, '_800x600.');
                        urls.push(src);
                    }
                });
            }
            return urls;
            """
            urls = self.driver.execute_script(js) or []

            # Tekrar ve thumbnail temizliği
            temiz = []
            gorulen = set()
            for u in urls:
                # 120x90 gibi küçük boyutları atla
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
        """Tek bir görseli indirir (thread-safe, kendi session'ı ile)."""
        # Her çağrı kendi session'ını kullansın (curl_cffi thread-safe değil)
        oturum = cffi_requests.Session(impersonate="chrome")
        oturum.headers.update({
            "User-Agent": self._ua,
            "Referer": "https://www.arabam.com/",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        })

        for d in range(config.YENIDEN_DENEME):
            try:
                yanit = oturum.get(url, timeout=20)
                yanit.raise_for_status()

                tip = yanit.headers.get("Content-Type", "")
                if "image" not in tip and "octet" not in tip:
                    log.warning(f"Görsel değil ({tip}): {url[:80]}")
                    return False

                with open(kayit_yolu, "wb") as f:
                    f.write(yanit.content)

                boyut = os.path.getsize(kayit_yolu)
                if boyut < 3000:
                    os.remove(kayit_yolu)
                    log.debug(f"  ✗ Çok küçük ({boyut}B): {url[:60]}")
                    return False

                log.info(f"  ✓ {os.path.basename(kayit_yolu)} ({boyut//1024} KB)")
                return True

            except Exception as h:
                log.debug(f"  İndirme hatası ({d+1}/{config.YENIDEN_DENEME}): {h}")
                if d < config.YENIDEN_DENEME - 1:
                    bekle(0.5, 1)
        return False

    def ilan_indir(self, ilan_url: str, kategori_klasoru: str) -> int:
        """
        Bir ilanın detay sayfasına gidip hedef fotoğrafları indirir.
        Her ilan kendi klasörüne: {kategori}/{ilan_no}/foto_1.jpg
        """
        indirilen = 0
        ilan_no = ilan_no_cikar(ilan_url)

        # Her ilan için ayrı klasör oluştur
        ilan_klasoru = os.path.join(kategori_klasoru, ilan_no)

        # Zaten indirilmiş mi kontrol et
        if os.path.exists(ilan_klasoru):
            mevcut = len([f for f in os.listdir(ilan_klasoru) if f.endswith(('.jpg', '.png', '.webp'))])
            if mevcut >= len(config.HEDEF_FOTO_INDEKSLERI):
                log.info(f"İlan {ilan_no} zaten indirilmiş ({mevcut} foto), atlanıyor.")
                return mevcut

        try:
            if not self.t.git(ilan_url):
                return 0

            bekle(config.ILAN_MIN_BEKLEME, config.ILAN_MAKS_BEKLEME)

            fotos = self.foto_bul()
            if not fotos:
                log.warning(f"İlan {ilan_no}: Fotoğraf bulunamadı.")
                return 0

            klasor_olustur(ilan_klasoru)

            # İndirilecek görevleri hazırla
            gorevler = []
            for idx in config.HEDEF_FOTO_INDEKSLERI:
                if idx >= len(fotos):
                    break
                dosya = os.path.join(ilan_klasoru, f"foto_{idx+1}.jpg")
                if os.path.exists(dosya):
                    indirilen += 1
                    continue
                gorevler.append((fotos[idx], dosya))

            # Paralel indir (6 fotoğraf aynı anda)
            if gorevler:
                with ThreadPoolExecutor(max_workers=6) as pool:
                    futures = {
                        pool.submit(self.indir, url, yol): yol
                        for url, yol in gorevler
                    }
                    for f in as_completed(futures):
                        if f.result():
                            indirilen += 1

        except Exception as h:
            log.error(f"İlan hatası ({ilan_no}): {h}")

        return indirilen


# ============================================================
# ANA ORKESTRATÖR
# ============================================================

class ArabamScraper:
    """Tüm bileşenleri koordine eder."""

    def __init__(self):
        self.tarayici = Tarayici()
        self.toplayici = None
        self.indirici = None
        self.ist = {
            "toplam_ilan": 0,
            "islenen": 0,
            "indirilen": 0,
            "hatali": 0,
        }

    def baslat(self):
        klasor_olustur(config.DATASET_DIR)
        self.tarayici.baslat()
        self.toplayici = IlanToplayici(self.tarayici)
        self.indirici = FotoIndirici(self.tarayici)

    def kategori_isle(self, adi: str, url: str):
        log.info("=" * 60)
        log.info(f"KATEGORİ: {adi.upper()}")
        log.info(f"URL: {url}")
        log.info("=" * 60)

        kat_klasor = os.path.join(config.DATASET_DIR, adi)
        klasor_olustur(kat_klasor)

        linkler = self.toplayici.topla(url)
        self.ist["toplam_ilan"] += len(linkler)

        if not linkler:
            log.warning(f"{adi}: İlan bulunamadı.")
            return

        for sira, ilan_url in enumerate(linkler, 1):
            log.info(f"\n[{sira}/{len(linkler)}] {ilan_url}")

            try:
                n = self.indirici.ilan_indir(ilan_url, kat_klasor)
                self.ist["indirilen"] += n
                self.ist["islenen"] += 1
            except Exception as h:
                log.error(f"Hata: {h}")
                self.ist["hatali"] += 1

            # Cooldown
            if (sira % config.COOLDOWN_ILAN_SAYISI == 0
                    and sira < len(linkler)):
                mola = random.uniform(config.COOLDOWN_MIN, config.COOLDOWN_MAKS)
                log.info(f"\n☕ COOLDOWN: {mola:.0f} sn mola...")
                time.sleep(mola)

    def calistir(self):
        log.info("=" * 60)
        log.info("ARABAM.COM TİCARİ ARAÇ FOTOĞRAF SCRAPER")
        log.info("=" * 60)

        t0 = time.time()

        try:
            self.baslat()

            for adi, url in config.KATEGORILER.items():
                try:
                    self.kategori_isle(adi, url)
                except Exception as h:
                    log.error(f"Kategori hatası ({adi}): {h}")

        except KeyboardInterrupt:
            log.info("\nCtrl+C — durduruluyor.")
        except Exception as h:
            log.error(f"Kritik hata: {h}", exc_info=True)
        finally:
            self.tarayici.kapat()

            dk = int((time.time() - t0) // 60)
            sn = int((time.time() - t0) % 60)

            log.info("\n" + "=" * 60)
            log.info("ÖZET")
            log.info("=" * 60)
            log.info(f"Toplam ilan      : {self.ist['toplam_ilan']}")
            log.info(f"İşlenen          : {self.ist['islenen']}")
            log.info(f"İndirilen görsel : {self.ist['indirilen']}")
            log.info(f"Hatalı           : {self.ist['hatali']}")
            log.info(f"Süre             : {dk} dk {sn} sn")
            log.info("=" * 60)


if __name__ == "__main__":
    ArabamScraper().calistir()
