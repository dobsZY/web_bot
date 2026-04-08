# -*- coding: utf-8 -*-
"""
Arabam.com Fotoğraf Seçici - Web Arayüzü
==========================================
İlanları tarar, fotoğrafları gösterir, kullanıcı seçer, indirir.

Kullanım:
    python app.py
"""

import os
import sys
import time
import random
import logging
import re
import threading
from pathlib import Path
from urllib.parse import urljoin, quote, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed

import undetected_chromedriver as uc
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    InvalidSessionIdException,
)
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from flask import Flask, render_template, jsonify, request, redirect, Response

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
        """Thread-safe indirme."""
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
                    return False

                with open(kayit_yolu, "wb") as f:
                    f.write(yanit.content)

                boyut = os.path.getsize(kayit_yolu)
                if boyut < 3000:
                    os.remove(kayit_yolu)
                    return False

                log.info(f"  ✓ {os.path.basename(kayit_yolu)} ({boyut//1024} KB)")
                return True

            except Exception:
                if d < config.YENIDEN_DENEME - 1:
                    bekle(0.5, 1)
        return False


# ============================================================
# FLASK APP
# ============================================================

app = Flask(__name__)

# Global durum
durum = {
    "tarayici": None,
    "toplayici": None,
    "foto": None,
    "linkler": [],
    "sira": 0,
    "mevcut_fotolar": [],
    "mevcut_url": "",
    "mevcut_ilan_no": "",
    "hazir": False,
    "ilan_hazir": False,       # Mevcut ilan fotoğrafları hazır mı?
    "ilan_yukleniyor": False,  # Chrome şu anda ilan yüklüyor mu?
    "indirilen_toplam": 0,
    "atlanan_toplam": 0,
}

# Chrome işlemleri için kilit
chrome_kilit = threading.Lock()


def ilan_topla_thread():
    """Arka planda ilan linklerini toplar."""
    log.info("İlan toplama başlıyor...")
    d = durum
    with chrome_kilit:
        d["tarayici"] = Tarayici()
        d["tarayici"].baslat()
        d["toplayici"] = IlanToplayici(d["tarayici"])
        d["foto"] = FotoIslem(d["tarayici"])

        for adi, url in config.KATEGORILER.items():
            log.info(f"Kategori: {adi}")
            linkler = d["toplayici"].topla(url)
            d["linkler"].extend(linkler)

    d["hazir"] = True
    log.info(f"Toplam {len(d['linkler'])} ilan toplandı. Seçim arayüzü hazır.")
    # İlk ilanı otomatik yükle
    _sonraki_ilani_yukle()


def _thumbnail_indir(url, dosya_yolu):
    """Tek bir thumbnail'i diske indir."""
    import requests as std_requests
    try:
        # 800x600 -> 240x180 thumbnail (hızlı yükleme için)
        thumb_url = re.sub(r'_\d+x\d+\.', '_240x180.', url)
        r = std_requests.get(thumb_url, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/146.0",
            "Referer": "https://www.arabam.com/",
        })
        if r.status_code == 200 and len(r.content) > 500:
            with open(dosya_yolu, "wb") as f:
                f.write(r.content)
            return True
    except Exception as h:
        log.debug(f"Thumbnail hatası: {h}")
    return False


def _sonraki_ilani_yukle():
    """Arka planda Chrome ile sonraki ilanı yükle, fotoğrafları bul ve thumbnail'lerini indir."""
    d = durum
    d["ilan_hazir"] = False
    d["ilan_yukleniyor"] = True
    d["thumb_yollar"] = []

    def _yukle():
        try:
            # Zaten indirilmiş ilanları atla
            while d["sira"] < len(d["linkler"]):
                ilan_url = d["linkler"][d["sira"]]
                ilan_no = ilan_no_cikar(ilan_url)
                kategori = list(config.KATEGORILER.keys())[0]
                ilan_klasoru = os.path.join(config.DATASET_DIR, kategori, ilan_no)
                if os.path.exists(ilan_klasoru):
                    mevcut = len([f for f in os.listdir(ilan_klasoru)
                                  if f.endswith(('.jpg', '.png', '.webp'))])
                    if mevcut >= 6:
                        log.info(f"İlan {ilan_no} zaten indirilmiş, atlıyorum.")
                        d["sira"] += 1
                        continue
                break

            if d["sira"] >= len(d["linkler"]):
                d["ilan_yukleniyor"] = False
                d["ilan_hazir"] = True
                return

            ilan_url = d["linkler"][d["sira"]]
            ilan_no = ilan_no_cikar(ilan_url)

            log.info(f"[BG] [{d['sira']+1}/{len(d['linkler'])}] {ilan_url}")

            with chrome_kilit:
                if not d["tarayici"].git(ilan_url):
                    log.warning(f"[BG] Sayfa yüklenemedi: {ilan_url}")
                    d["mevcut_fotolar"] = []
                    d["mevcut_url"] = ilan_url
                    d["mevcut_ilan_no"] = ilan_no
                    d["ilan_hazir"] = True
                    d["ilan_yukleniyor"] = False
                    return

                bekle(config.ILAN_MIN_BEKLEME, config.ILAN_MAKS_BEKLEME)
                fotolar = d["foto"].foto_bul()

            d["mevcut_fotolar"] = fotolar
            d["mevcut_url"] = ilan_url
            d["mevcut_ilan_no"] = ilan_no

            # Thumbnail'leri diske indir
            thumb_dir = os.path.join("static", "temp", ilan_no)
            klasor_olustur(thumb_dir)

            thumb_yollar = []
            basarili = 0
            for i, foto_url in enumerate(fotolar):
                dosya = os.path.join(thumb_dir, f"thumb_{i}.jpg")
                if _thumbnail_indir(foto_url, dosya):
                    thumb_yollar.append(f"/static/temp/{ilan_no}/thumb_{i}.jpg")
                    basarili += 1
                else:
                    thumb_yollar.append("")  # Boş = yüklenemedi

            d["thumb_yollar"] = thumb_yollar
            d["ilan_hazir"] = True
            d["ilan_yukleniyor"] = False

            log.info(f"[BG] {len(fotolar)} fotoğraf, {basarili} thumbnail hazır.")
        except Exception as h:
            log.error(f"[BG] İlan yükleme hatası: {h}")
            d["ilan_yukleniyor"] = False
            d["ilan_hazir"] = True

    threading.Thread(target=_yukle, daemon=True).start()


def _temel_veri():
    """Template'e gönderilecek temel veriler."""
    return {
        "sira": durum["sira"] + 1,
        "toplam": len(durum["linkler"]),
        "indirilen": durum["indirilen_toplam"],
        "atlanan": durum["atlanan_toplam"],
    }


@app.route("/")
def anasayfa():
    d = durum

    # Henüz ilanlar toplanmadıysa
    if not d["hazir"]:
        return render_template("secici.html", bekle=True, **_temel_veri())

    # Tüm ilanlar bittiyse
    if d["sira"] >= len(d["linkler"]) and d["ilan_hazir"]:
        return render_template("secici.html", bitti=True, **_temel_veri())

    # İlan henüz yüklenmiyorsa yüklemeyi başlat
    if not d["ilan_hazir"] and not d["ilan_yukleniyor"]:
        _sonraki_ilani_yukle()

    # İlan yükleniyorsa bekleme sayfası göster
    if not d["ilan_hazir"]:
        return render_template("secici.html", bekle=False, yukleniyor=True, **_temel_veri())

    # İlan hazır — fotoğrafları göster
    # thumb_yollar ve fotolar eşleştirilmiş liste olarak gönder
    foto_listesi = []
    for i, foto_url in enumerate(d["mevcut_fotolar"]):
        thumb = d["thumb_yollar"][i] if i < len(d["thumb_yollar"]) else ""
        foto_listesi.append({"url": foto_url, "thumb": thumb, "idx": i})

    return render_template("secici.html",
                           foto_listesi=foto_listesi,
                           ilan_url=d["mevcut_url"],
                           **_temel_veri())


@app.route("/indir", methods=["POST"])
def indir_route():
    d = durum
    secili = request.form.getlist("secili")

    if not secili or not d["mevcut_fotolar"]:
        d["sira"] += 1
        return redirect("/")

    ilan_no = d["mevcut_ilan_no"]
    kategori = list(config.KATEGORILER.keys())[0]
    ilan_klasoru = os.path.join(config.DATASET_DIR, kategori, ilan_no)
    klasor_olustur(ilan_klasoru)

    indirilen = 0
    gorevler = []
    for i, idx_str in enumerate(sorted(secili, key=int)):
        idx = int(idx_str)
        if idx < len(d["mevcut_fotolar"]):
            dosya = os.path.join(ilan_klasoru, f"foto_{i+1}.jpg")
            gorevler.append((d["mevcut_fotolar"][idx], dosya))

    if gorevler:
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {
                pool.submit(d["foto"].indir, url, yol): yol
                for url, yol in gorevler
            }
            for f in as_completed(futures):
                if f.result():
                    indirilen += 1

    d["indirilen_toplam"] += indirilen
    d["sira"] += 1

    log.info(f"İlan {ilan_no}: {indirilen}/{len(gorevler)} fotoğraf indirildi.")
    _sonraki_ilani_yukle()
    return redirect("/")


@app.route("/proxy-img")
def proxy_img():
    """Resimleri sunucu üzerinden proxy'le — CORS sorununu çözer."""
    url = request.args.get("url", "")
    if not url:
        return Response("No URL", status=400)

    # Birden fazla yöntemle dene
    yontemler = [
        ("requests", _indir_requests),
        ("curl_cffi", _indir_curl),
    ]
    for adi, fonk in yontemler:
        try:
            icerik, tip = fonk(url)
            if icerik:
                return Response(icerik, content_type=tip,
                                headers={"Cache-Control": "public, max-age=3600"})
        except Exception as h:
            log.debug(f"Proxy ({adi}) hatası: {h}")
            continue

    return Response("Error", status=502)


def _indir_requests(url):
    """Standart requests ile indir."""
    import requests as std_requests
    r = std_requests.get(url, timeout=15, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/146.0.0.0 Safari/537.36",
        "Referer": "https://www.arabam.com/",
        "Accept": "image/*,*/*;q=0.8",
    })
    r.raise_for_status()
    return r.content, r.headers.get("Content-Type", "image/jpeg")


def _indir_curl(url):
    """curl_cffi ile indir."""
    oturum = cffi_requests.Session(impersonate="chrome")
    oturum.headers.update({
        "Referer": "https://www.arabam.com/",
        "Accept": "image/*,*/*;q=0.8",
    })
    yanit = oturum.get(url, timeout=15)
    yanit.raise_for_status()
    return yanit.content, yanit.headers.get("Content-Type", "image/jpeg")


@app.route("/atla")
def atla_route():
    durum["sira"] += 1
    durum["atlanan_toplam"] += 1
    log.info(f"İlan atlandı. Sonraki: {durum['sira']+1}")
    _sonraki_ilani_yukle()
    return redirect("/")


# ============================================================
# BAŞLAT
# ============================================================

if __name__ == "__main__":
    klasor_olustur(config.DATASET_DIR)

    # Arka planda ilan topla
    t = threading.Thread(target=ilan_topla_thread, daemon=True)
    t.start()

    log.info("Web arayüzü başlatılıyor: http://localhost:5000")
    print("\n" + "=" * 50)
    print("  TARAYICIDA AÇ: http://localhost:5000")
    print("=" * 50 + "\n")

    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False, threaded=True)
