# -*- coding: utf-8 -*-
"""
Letgo İlan Özellik Toplayıcı
=============================
Mevcut dataset_letgo/van/ klasöründeki ilan numaralarından giderek
her ilanın detay sayfasındaki özellikleri çeker ve klasöre ozellikler.txt yazar.
Resimleri tekrar indirmez.

Kullanım:
    python letgo_ozellik.py
"""

import os
import sys
import time
import random
import logging
import re
import json
from pathlib import Path

import undetected_chromedriver as uc
from selenium.common.exceptions import TimeoutException, WebDriverException

# ============================================================
# AYARLAR
# ============================================================

DATASET_DIR = "dataset_letgo"
KATEGORI = "van"
OZELLIK_DOSYA = "ozellikler.txt"

# Tarayıcı
HEADLESS = False
PENCERE_GENISLIK = 1920
PENCERE_YUKSEKLIK = 1080
SAYFA_TIMEOUT = 30

# Bekleme
MIN_BEKLEME = 2.0
MAKS_BEKLEME = 4.0
COOLDOWN_HER = 50       # Her 50 ilanda bir mola
COOLDOWN_SURE = 10      # 10 sn mola

# ============================================================
# LOG
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("letgo_ozellik")

# ============================================================
# YARDIMCILAR
# ============================================================

def bekle(min_sn: float, maks_sn: float) -> None:
    time.sleep(random.uniform(min_sn, maks_sn))


def ilan_url_olustur(ilan_id: str) -> str:
    """İlan ID'sinden detay URL'si oluştur."""
    return f"https://www.letgo.com/item/detay-iid-{ilan_id}"


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

        self.driver = uc.Chrome(options=options, version_main=146)
        self.driver.set_page_load_timeout(SAYFA_TIMEOUT)
        self.driver.implicitly_wait(5)
        log.info("Chrome hazır.")

    def git(self, url: str) -> bool:
        for deneme in range(3):
            try:
                self.driver.get(url)
                return True
            except TimeoutException:
                log.warning(f"  Timeout ({deneme+1}/3): {url[:60]}")
            except WebDriverException as e:
                log.warning(f"  Hata ({deneme+1}/3): {str(e)[:80]}")
            bekle(1, 2)
        return False

    def kapat(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None


# ============================================================
# ÖZELLİK ÇEKME
# ============================================================

def ozellikleri_cek(driver) -> dict:
    """Detay sayfasından ilan özelliklerini çek."""
    try:
        veri = driver.execute_script("""
        var data = {};

        // 1. Sayfa başlığı
        var h1 = document.querySelector('h1');
        data.baslik = h1 ? h1.innerText.trim() : '';

        // 2. Fiyat
        var fiyatEl = document.querySelector('[data-testid="ad-price-txt"]') ||
                      document.querySelector('[class*="price"]');
        data.fiyat = fiyatEl ? fiyatEl.innerText.trim() : '';

        // 3. Açıklama
        var descEl = document.querySelector('[data-testid="ad-description-txt"]') ||
                     document.querySelector('[class*="description"]');
        data.aciklama = descEl ? descEl.innerText.trim() : '';

        // 4. Özellik tablosu — tüm key-value çiftleri
        data.ozellikler = {};
        // Letgo'da özellikler genelde li veya div içinde key: value şeklinde
        document.querySelectorAll('li, [class*="param"], [class*="detail"], [class*="spec"]').forEach(function(el) {
            var spans = el.querySelectorAll('span, p, div');
            if (spans.length >= 2) {
                var key = spans[0].innerText.trim();
                var val = spans[spans.length - 1].innerText.trim();
                if (key && val && key !== val && key.length < 50) {
                    data.ozellikler[key] = val;
                }
            }
        });

        // 5. JSON-LD'den ek bilgi
        document.querySelectorAll('script[type="application/ld+json"]').forEach(function(s) {
            try {
                var j = JSON.parse(s.textContent);
                if (j.mainEntity) {
                    var e = j.mainEntity;
                    if (e.name && !data.baslik) data.baslik = e.name;
                    if (e.description && !data.aciklama) data.aciklama = e.description;
                    if (e.brand && e.brand.name) data.ozellikler['Marka'] = e.brand.name;
                    if (e.offers && e.offers.price) data.ozellikler['Fiyat (JSON)'] = e.offers.price + ' ' + (e.offers.priceCurrency || '');
                }
            } catch(ex) {}
        });

        // 6. Konum
        var locEl = document.querySelector('[class*="location"], [data-testid*="location"]');
        data.konum = locEl ? locEl.innerText.trim() : '';

        // 7. Tarih
        var dateEl = document.querySelector('[class*="date"], [data-testid*="date"]');
        data.tarih = dateEl ? dateEl.innerText.trim() : '';

        return data;
        """)
        return veri or {}
    except Exception as h:
        log.error(f"  Özellik çekme hatası: {h}")
        return {}


def txt_yaz(klasor: str, veri: dict) -> None:
    """Özellikleri txt dosyasına yaz."""
    dosya = os.path.join(klasor, OZELLIK_DOSYA)
    with open(dosya, "w", encoding="utf-8") as f:
        if veri.get("baslik"):
            f.write(f"Başlık: {veri['baslik']}\n")
        if veri.get("fiyat"):
            f.write(f"Fiyat: {veri['fiyat']}\n")
        if veri.get("konum"):
            f.write(f"Konum: {veri['konum']}\n")
        if veri.get("tarih"):
            f.write(f"Tarih: {veri['tarih']}\n")

        ozellikler = veri.get("ozellikler", {})
        if ozellikler:
            f.write("\n--- Özellikler ---\n")
            for k, v in ozellikler.items():
                f.write(f"{k}: {v}\n")

        if veri.get("aciklama"):
            f.write(f"\n--- Açıklama ---\n{veri['aciklama']}\n")


# ============================================================
# ANA İŞLEM
# ============================================================

def calistir():
    van_dir = os.path.join(DATASET_DIR, KATEGORI)
    if not os.path.isdir(van_dir):
        log.error(f"Klasör bulunamadı: {van_dir}")
        return

    # Tüm ilan klasörlerini al
    tum_klasorler = sorted([
        d for d in os.listdir(van_dir)
        if os.path.isdir(os.path.join(van_dir, d)) and d.isdigit()
    ])

    # Zaten özelliği olan ilanları atla
    eksik = []
    for ilan_id in tum_klasorler:
        txt_yol = os.path.join(van_dir, ilan_id, OZELLIK_DOSYA)
        if not os.path.exists(txt_yol):
            eksik.append(ilan_id)

    toplam = len(tum_klasorler)
    zaten = toplam - len(eksik)
    log.info(f"Toplam {toplam} ilan, {zaten} tanesi zaten özellikli, {len(eksik)} ilan işlenecek.")

    if not eksik:
        log.info("Tüm ilanların özellikleri mevcut!")
        return

    # Tarayıcı başlat
    tarayici = Tarayici()
    tarayici.baslat()

    basarili = 0
    hatali = 0

    for sira, ilan_id in enumerate(eksik):
        ilan_klasoru = os.path.join(van_dir, ilan_id)
        url = ilan_url_olustur(ilan_id)

        log.info(f"[{sira+1}/{len(eksik)}] {ilan_id}")

        if not tarayici.git(url):
            log.warning(f"  Sayfa açılamadı, atlıyorum.")
            hatali += 1
            continue

        bekle(MIN_BEKLEME, MAKS_BEKLEME)

        # Popup kapat
        try:
            tarayici.driver.execute_script("""
            document.querySelectorAll('[class*="close"], [class*="dismiss"], [aria-label="Close"]').forEach(function(b) { b.click(); });
            """)
        except Exception:
            pass

        veri = ozellikleri_cek(tarayici.driver)

        if not veri or (not veri.get("baslik") and not veri.get("ozellikler")):
            log.warning(f"  Özellik bulunamadı, atlıyorum.")
            hatali += 1
            continue

        txt_yaz(ilan_klasoru, veri)
        basarili += 1
        log.info(f"  ✓ {veri.get('baslik', '?')[:40]} | {len(veri.get('ozellikler', {}))} özellik")

        # Mola
        if (sira + 1) % COOLDOWN_HER == 0:
            log.info(f"  Mola ({COOLDOWN_SURE}sn)...")
            time.sleep(COOLDOWN_SURE)

    tarayici.kapat()
    print("=" * 60)
    log.info(f"BİTTİ! {basarili} başarılı, {hatali} hatalı, toplam {len(eksik)} işlendi.")


if __name__ == "__main__":
    calistir()
