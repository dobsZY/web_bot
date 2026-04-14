# -*- coding: utf-8 -*-
"""
Arabam.com Otomobil Bilgi Toplayıcı
====================================
2016-2026 arası yıl yıl tarayarak ilan bilgilerini toplar.
Liste sayfasından tüm bilgileri çeker (detay sayfasına girmez → hızlı).

Klasör yapısı:
    arabam_data/Marka_Model_Yıl/
        bilgi.json    (tüm ilan bilgileri)

Durdurup devam edebilir — JSON progress dosyası tutar.

Kullanım:
    python arabam_bilgi.py
"""

import os
import sys
import time
import json
import random
import logging
import re
import signal
from pathlib import Path
from urllib.parse import urljoin

import undetected_chromedriver as uc
from selenium.common.exceptions import TimeoutException, WebDriverException
from bs4 import BeautifulSoup

# ============================================================
# AYARLAR
# ============================================================

DATASET_DIR = r"C:\arabam_data"
PROGRESS_FILE = os.path.join(DATASET_DIR, "_progress.json")

BASE_URL = "https://www.arabam.com/ikinci-el/otomobil"
YIL_BASLANGIC = 2016
YIL_BITIS = 2026
SAYFA_BASINA = 50      # take=50
MAKS_SAYFA = 50        # Site limiti

# Hız ayarları
SAYFA_BEKLEME_MIN = 1.5
SAYFA_BEKLEME_MAKS = 3.0
COOLDOWN_HER = 30       # Her 30 sayfada mola
COOLDOWN_SURE = 8

# ============================================================
# LOG
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("arabam")

# ============================================================
# DURDURMA SİNYALİ
# ============================================================

_durdur = False

def _sinyal_yakala(sig, frame):
    global _durdur
    _durdur = True
    log.info("\n⏸  Durdurma sinyali alındı! Mevcut sayfa bittikten sonra duracak...")

signal.signal(signal.SIGINT, _sinyal_yakala)

# ============================================================
# YARDIMCILAR
# ============================================================

def bekle(min_sn: float, maks_sn: float) -> None:
    time.sleep(random.uniform(min_sn, maks_sn))


def klasor_olustur(yol: str) -> None:
    Path(yol).mkdir(parents=True, exist_ok=True)


def temiz_ad(text: str) -> str:
    """Dosya/klasör adı için güvenli string."""
    text = text.strip()
    text = re.sub(r'[\\/:*?"<>|]', '', text)
    text = re.sub(r'\s+', '_', text)
    text = text.replace('.', '_')
    return text[:80]


def progress_yukle() -> dict:
    """Kaldığı yeri yükle."""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"tamamlanan_yillar": [], "mevcut_yil": None, "mevcut_sayfa": 0, "toplam_ilan": 0}


def progress_kaydet(data: dict) -> None:
    """İlerlemeyi kaydet."""
    klasor_olustur(DATASET_DIR)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================
# TARAYICI
# ============================================================

class Tarayici:
    def __init__(self):
        self.driver = None

    def baslat(self):
        log.info("Chrome başlatılıyor...")
        options = uc.ChromeOptions()
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--lang=tr-TR")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")

        self.driver = uc.Chrome(options=options)
        self.driver.set_page_load_timeout(30)
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
# LİSTE SAYFASINDAN BİLGİ ÇEK
# ============================================================

def ilan_bilgisi_cek(driver) -> list[dict]:
    """Sayfa kaynağından tüm ilanların bilgilerini çek."""
    try:
        soup = BeautifulSoup(driver.page_source, "lxml")
    except Exception as e:
        log.error(f"Sayfa parse hatası: {e}")
        return []

    items = []

    for tr in soup.select("tr.listing-list-item"):
        try:
            tds = tr.select("td")
            if len(tds) < 7:
                continue

            # Link ve ID
            a = tr.select_one('a[href*="/ilan/"]')
            if not a:
                continue
            href = a.get("href", "")
            url = urljoin("https://www.arabam.com", href)
            id_match = re.search(r'/(\d{6,12})(?:\?|$|")', url)
            ilan_id = id_match.group(1) if id_match else ""

            # Bilgi alanları (td sırasına göre)
            # td[0]: foto küçük resim
            # td[1]: Marka Model (ilk satır)
            # td[2]: İlan başlığı
            # td[3]: Yıl
            # td[4]: KM
            # td[5]: Renk
            # td[6]: Fiyat
            # td[7]: Tarih
            # td[8]: Konum
            marka_model = tds[1].get_text(strip=True) if len(tds) > 1 else ""
            baslik = tds[2].get_text(strip=True) if len(tds) > 2 else ""
            yil = tds[3].get_text(strip=True) if len(tds) > 3 else ""
            km = tds[4].get_text(strip=True) if len(tds) > 4 else ""
            renk = tds[5].get_text(strip=True) if len(tds) > 5 else ""
            fiyat = tds[6].get_text(strip=True) if len(tds) > 6 else ""
            tarih = tds[7].get_text(strip=True) if len(tds) > 7 else ""
            konum_raw = tds[8].get_text(separator="|", strip=True) if len(tds) > 8 else ""
            # Buton metinlerini temizle
            konum_parts = konum_raw.split("|")
            konum = " ".join(p.strip() for p in konum_parts[:2] if p.strip())

            # Küçük resim URL
            img = tr.select_one("img")
            img_url = ""
            if img:
                img_url = img.get("data-src") or img.get("src") or ""

            item = {
                "id": ilan_id,
                "url": url,
                "marka_model": marka_model,
                "baslik": baslik,
                "yil": yil,
                "km": km,
                "renk": renk,
                "fiyat": fiyat,
                "tarih": tarih,
                "konum": konum,
                "img_url": img_url,
            }
            items.append(item)

        except Exception as e:
            log.debug(f"İlan parse hatası: {e}")
            continue

    return items


def ilan_kaydet(item: dict) -> bool:
    """Tek bir ilanı marka_model_yıl klasörüne kaydet."""
    marka_model = item.get("marka_model", "Bilinmiyor")
    yil = item.get("yil", "0")
    ilan_id = item.get("id", "unknown")

    klasor_adi = temiz_ad(f"{marka_model}_{yil}")
    if not klasor_adi:
        klasor_adi = f"bilinmiyor_{yil}"

    klasor = os.path.join(DATASET_DIR, klasor_adi)
    klasor_olustur(klasor)

    dosya = os.path.join(klasor, f"{ilan_id}.json")
    if os.path.exists(dosya):
        return False  # Zaten var

    with open(dosya, "w", encoding="utf-8") as f:
        json.dump(item, f, ensure_ascii=False, indent=2)

    return True


# ============================================================
# ANA İŞLEM
# ============================================================

def calistir():
    global _durdur

    klasor_olustur(DATASET_DIR)
    progress = progress_yukle()

    tamamlanan = set(progress.get("tamamlanan_yillar", []))
    toplam_ilan = progress.get("toplam_ilan", 0)

    yillar = list(range(YIL_BASLANGIC, YIL_BITIS + 1))

    # Kaldığı yıldan devam
    mevcut_yil = progress.get("mevcut_yil")
    mevcut_sayfa = progress.get("mevcut_sayfa", 0)

    tarayici = Tarayici()
    tarayici.baslat()

    baslangic = time.time()
    sayfa_sayaci = 0

    for yil in yillar:
        if _durdur:
            break

        if yil in tamamlanan:
            log.info(f"Yıl {yil} zaten tamamlanmış, atlıyorum.")
            continue

        # Kaldığı sayfadan devam
        if mevcut_yil == yil:
            baslangic_sayfa = mevcut_sayfa
        else:
            baslangic_sayfa = 1

        log.info(f"\n{'='*60}")
        log.info(f"YIL: {yil} (sayfa {baslangic_sayfa}'den başlıyor)")
        log.info(f"{'='*60}")

        yil_ilan = 0
        ardisik_bos = 0

        for sayfa in range(baslangic_sayfa, MAKS_SAYFA + 1):
            if _durdur:
                # Durduruluyor — ilerlemeyi kaydet
                progress["mevcut_yil"] = yil
                progress["mevcut_sayfa"] = sayfa
                progress["toplam_ilan"] = toplam_ilan
                progress_kaydet(progress)
                log.info(f"İlerleme kaydedildi. (Yıl: {yil}, Sayfa: {sayfa})")
                break

            url = f"{BASE_URL}?minYear={yil}&maxYear={yil}&take={SAYFA_BASINA}&page={sayfa}"

            if not tarayici.git(url):
                log.warning(f"  Sayfa açılamadı: {url}")
                ardisik_bos += 1
                if ardisik_bos >= 3:
                    break
                continue

            bekle(SAYFA_BEKLEME_MIN, SAYFA_BEKLEME_MAKS)

            items = ilan_bilgisi_cek(tarayici.driver)

            if not items:
                ardisik_bos += 1
                log.info(f"  Sayfa {sayfa}: ilan yok (ardışık boş: {ardisik_bos})")
                if ardisik_bos >= 2:
                    log.info(f"  Yıl {yil} bitti.")
                    break
                continue

            ardisik_bos = 0
            yeni = 0
            for item in items:
                if ilan_kaydet(item):
                    yeni += 1

            yil_ilan += len(items)
            toplam_ilan += yeni
            sayfa_sayaci += 1

            gecen = time.time() - baslangic
            log.info(f"  Sayfa {sayfa}: {len(items)} ilan, {yeni} yeni | "
                     f"Yıl {yil}: {yil_ilan} | Toplam: {toplam_ilan}")

            # İlerleme kaydet (her 5 sayfada)
            if sayfa_sayaci % 5 == 0:
                progress["mevcut_yil"] = yil
                progress["mevcut_sayfa"] = sayfa + 1
                progress["toplam_ilan"] = toplam_ilan
                progress_kaydet(progress)

            # Mola
            if sayfa_sayaci % COOLDOWN_HER == 0:
                log.info(f"  Mola ({COOLDOWN_SURE}sn)...")
                time.sleep(COOLDOWN_SURE)

        if not _durdur:
            # Yıl tamamlandı
            tamamlanan.add(yil)
            progress["tamamlanan_yillar"] = list(tamamlanan)
            progress["mevcut_yil"] = None
            progress["mevcut_sayfa"] = 0
            progress["toplam_ilan"] = toplam_ilan
            progress_kaydet(progress)
            log.info(f"Yıl {yil} tamamlandı! ({yil_ilan} ilan)")

    tarayici.kapat()

    gecen_toplam = time.time() - baslangic
    print("\n" + "=" * 60)
    if _durdur:
        log.info(f"DURAKLATILDI! Toplam {toplam_ilan} ilan kaydedildi.")
        log.info(f"Devam etmek için tekrar çalıştırın: python arabam_bilgi.py")
    else:
        log.info(f"BİTTİ! Toplam {toplam_ilan} ilan kaydedildi.")
    log.info(f"Süre: {gecen_toplam/60:.1f} dakika")
    log.info(f"Klasör: {os.path.abspath(DATASET_DIR)}")


if __name__ == "__main__":
    calistir()
