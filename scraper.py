# -*- coding: utf-8 -*-
"""
Sahibinden.com Ticari Araç Arka Cephe Fotoğraf Scraper
=======================================================
Bu bot, sahibinden.com üzerindeki ticari araç ilanlarından
arka cephe fotoğraflarını otomatik olarak indirerek bir
Computer Vision veri seti oluşturur.

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

import requests
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

import config


# ============================================================
# LOGGING AYARLARI
# ============================================================

def logger_kur() -> logging.Logger:
    """
    Hem konsola hem de dosyaya yazan bir logger oluşturur.
    Tarih, seviye ve mesaj bilgisi loglanır.
    """
    logger = logging.getLogger("SahibindenScraper")
    logger.setLevel(logging.DEBUG)

    # Konsol handler (INFO ve üstü)
    konsol = logging.StreamHandler(sys.stdout)
    konsol.setLevel(logging.INFO)
    konsol_format = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )
    konsol.setFormatter(konsol_format)

    # Dosya handler (DEBUG ve üstü)
    dosya = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
    dosya.setLevel(logging.DEBUG)
    dosya_format = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s [%(funcName)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    dosya.setFormatter(dosya_format)

    logger.addHandler(konsol)
    logger.addHandler(dosya)
    return logger


log = logger_kur()


# ============================================================
# YARDIMCI FONKSİYONLAR
# ============================================================

def rastgele_bekle(min_sn: float, maks_sn: float) -> None:
    """Gerçek kullanıcı davranışını taklit etmek için rastgele süre bekler."""
    sure = random.uniform(min_sn, maks_sn)
    log.debug(f"Bekleniyor: {sure:.1f} saniye")
    time.sleep(sure)


def klasor_olustur(yol: str) -> None:
    """Verilen yolda klasör yoksa oluşturur."""
    Path(yol).mkdir(parents=True, exist_ok=True)


def ilan_no_cikar(url: str) -> str:
    """
    İlan URL'sinden benzersiz ilan numarasını çıkarır.
    Örn: .../ilan/1234567/detay -> 1234567
    """
    # Sahibinden URL yapısı: .../ilan/<id>/...  veya sonunda -<id> şeklinde
    eslesen = re.search(r'/(\d{5,12})', url)
    if eslesen:
        return eslesen.group(1)
    # Bulunamazsa URL hash'i ile benzersiz isim üret
    return str(abs(hash(url)))[:12]


# ============================================================
# TARAYICI YÖNETİCİSİ
# ============================================================

class TarayiciYoneticisi:
    """
    undetected-chromedriver ile stealth modda Chrome tarayıcısını
    yönetir. Anti-bot atlatma mekanizmalarını içerir.
    """

    def __init__(self):
        self.driver = None
        self.ua = UserAgent(browsers=["chrome"])

    def baslat(self) -> uc.Chrome:
        """
        Stealth ayarlarıyla Chrome tarayıcısını başlatır.
        Bot tespit edilmesini engellemek için çeşitli önlemler alır.
        """
        log.info("Chrome tarayıcı başlatılıyor (stealth mod)...")

        options = uc.ChromeOptions()

        # Rastgele bir User-Agent seç
        user_agent = self.ua.random
        options.add_argument(f"--user-agent={user_agent}")
        log.debug(f"User-Agent: {user_agent}")

        # Pencere boyutu
        options.add_argument(
            f"--window-size={config.PENCERE_GENISLIK},{config.PENCERE_YUKSEKLIK}"
        )

        # Headless mod (ayara göre)
        if config.HEADLESS:
            options.add_argument("--headless=new")

        # Bot tespit önleme ek argümanları
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-first-run")
        options.add_argument("--no-service-autorun")
        options.add_argument("--password-store=basic")
        options.add_argument("--disable-extensions")
        options.add_argument("--lang=tr-TR")

        # Bildirim ve pop-up'ları engelle
        prefs = {
            "profile.default_content_setting_values.notifications": 2,
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        }
        options.add_experimental_option("prefs", prefs)

        try:
            self.driver = uc.Chrome(options=options, version_main=None)
            self.driver.set_page_load_timeout(config.SAYFA_TIMEOUT)

            # navigator.webdriver özelliğini gizle
            self.driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": """
                        Object.defineProperty(navigator, 'webdriver', {
                            get: () => undefined
                        });
                        // Chrome nesnesini gerçek gibi göster
                        window.chrome = { runtime: {} };
                        // Dil ayarını Türkçe yap
                        Object.defineProperty(navigator, 'language', {
                            get: () => 'tr-TR'
                        });
                        Object.defineProperty(navigator, 'languages', {
                            get: () => ['tr-TR', 'tr', 'en-US', 'en']
                        });
                    """
                },
            )

            log.info("Tarayıcı başarıyla başlatıldı.")
            return self.driver

        except Exception as hata:
            log.error(f"Tarayıcı başlatma hatası: {hata}")
            raise

    def rastgele_fare_hareketi(self) -> None:
        """
        Sayfada rastgele fare hareketleri yaparak insan davranışını simüle eder.
        Bu, bot tespit algoritmalarını yanıltmaya yardımcı olur.
        """
        if not self.driver:
            return
        try:
            eylem = ActionChains(self.driver)
            # 2-4 arasında rastgele fare hareketi yap
            for _ in range(random.randint(2, 4)):
                x = random.randint(100, config.PENCERE_GENISLIK - 200)
                y = random.randint(100, config.PENCERE_YUKSEKLIK - 200)
                eylem.move_by_offset(
                    random.randint(-50, 50),
                    random.randint(-50, 50),
                )
            eylem.perform()
            log.debug("Rastgele fare hareketi yapıldı.")
        except Exception:
            # Fare hareketi kritik değil, hata olursa yoksay
            pass

    def sayfaya_git(self, url: str, deneme: int = None) -> bool:
        """
        Belirtilen URL'ye gider. Başarısız olursa yeniden dener.
        Cloudflare challenge sayfasını algılayıp bekler.
        """
        if deneme is None:
            deneme = config.YENIDEN_DENEME

        for i in range(deneme):
            try:
                log.info(f"Sayfa yükleniyor: {url}")
                self.driver.get(url)
                rastgele_bekle(config.MIN_BEKLEME, config.MAKS_BEKLEME)

                # Cloudflare challenge kontrolü
                sayfa_kaynak = self.driver.page_source.lower()
                if "challenge" in sayfa_kaynak or "just a moment" in sayfa_kaynak:
                    log.warning("Cloudflare challenge algılandı, bekleniyor...")
                    time.sleep(15)

                self.rastgele_fare_hareketi()
                return True

            except TimeoutException:
                log.warning(f"Sayfa zaman aşımı (deneme {i + 1}/{deneme}): {url}")
                if i < deneme - 1:
                    rastgele_bekle(5, 10)
            except WebDriverException as hata:
                log.error(f"WebDriver hatası (deneme {i + 1}/{deneme}): {hata}")
                if i < deneme - 1:
                    rastgele_bekle(5, 10)

        log.error(f"Sayfa yüklenemedi: {url}")
        return False

    def kapat(self) -> None:
        """Tarayıcıyı güvenli şekilde kapatır."""
        if self.driver:
            try:
                self.driver.quit()
                log.info("Tarayıcı kapatıldı.")
            except Exception:
                pass


# ============================================================
# İLAN TOPLAYICI
# ============================================================

class IlanToplayici:
    """
    Sahibinden kategori sayfalarında gezinerek ilan linklerini toplar.
    Sayfalandırma (pagination) yapısını takip eder.
    """

    def __init__(self, tarayici: TarayiciYoneticisi):
        self.tarayici = tarayici
        self.driver = tarayici.driver

    def sayfa_ilan_linklerini_al(self) -> list[str]:
        """
        Mevcut liste sayfasındaki tüm ilan detay linklerini çıkarır.
        Sahibinden'de ilanlar genellikle bir tablo veya kart yapısında listelenir.
        """
        linkler = []
        try:
            soup = BeautifulSoup(self.driver.page_source, "lxml")

            # Sahibinden ilan listesi: .classifiedTitle sınıfındaki <a> etiketleri
            # veya searchResultsItem altındaki linkler
            seciciler = [
                "td.searchResultsTitleValue a",       # Klasik tablo görünümü
                "a.classifiedTitle",                    # Kart görünümü
                ".searchResultsLargeThumbnail a.titleIcon",  # Büyük thumbnail
                "#searchResultsTable .searchResultsItem a[href*='/ilan/']",
            ]

            bulunan_linkler = set()
            for secici in seciciler:
                elemanlar = soup.select(secici)
                for eleman in elemanlar:
                    href = eleman.get("href", "")
                    if href and "/ilan/" in href:
                        # Tam URL oluştur
                        tam_url = urljoin("https://www.sahibinden.com", href)
                        bulunan_linkler.add(tam_url)

            linkler = list(bulunan_linkler)
            log.info(f"Bu sayfada {len(linkler)} ilan linki bulundu.")

        except Exception as hata:
            log.error(f"İlan linkleri alınırken hata: {hata}")

        return linkler

    def sonraki_sayfa_var_mi(self) -> bool:
        """
        Sayfalandırmada bir sonraki sayfa olup olmadığını kontrol eder.
        Varsa o sayfaya tıklar ve True döner.
        """
        try:
            soup = BeautifulSoup(self.driver.page_source, "lxml")

            # "Sonraki" butonu veya ">" ikonu
            sonraki_seciciler = [
                'a.prevNextBut[title="Sonraki"]',
                'a[class*="next"]',
                'ul.pageNaviButtons a[title="Sonraki"]',
            ]

            for secici in sonraki_seciciler:
                sonraki = soup.select_one(secici)
                if sonraki and sonraki.get("href"):
                    href = sonraki["href"]
                    sonraki_url = urljoin("https://www.sahibinden.com", href)
                    log.info(f"Sonraki sayfa bulundu: {sonraki_url}")
                    return self.tarayici.sayfaya_git(sonraki_url)

            # Alternatif: Selenium ile doğrudan tıklama
            try:
                sonraki_btn = self.driver.find_element(
                    By.CSS_SELECTOR, 'a.prevNextBut[title="Sonraki"]'
                )
                if sonraki_btn:
                    sonraki_btn.click()
                    rastgele_bekle(config.MIN_BEKLEME, config.MAKS_BEKLEME)
                    return True
            except NoSuchElementException:
                pass

            log.info("Son sayfaya ulaşıldı, başka sayfa yok.")
            return False

        except Exception as hata:
            log.error(f"Sayfalandırma hatası: {hata}")
            return False

    def kategori_ilanlarini_topla(self, kategori_url: str) -> list[str]:
        """
        Bir kategorideki tüm sayfalardaki ilan linklerini toplar.
        config.MAKS_SAYFA ayarına göre sayfa limiti uygular.
        """
        tum_linkler = []
        sayfa_no = 1

        # İlk sayfaya git
        if not self.tarayici.sayfaya_git(kategori_url):
            log.error(f"Kategori sayfası açılamadı: {kategori_url}")
            return tum_linkler

        while True:
            log.info(f"--- Sayfa {sayfa_no} taranıyor ---")

            # Bu sayfadaki ilan linklerini al
            linkler = self.sayfa_ilan_linklerini_al()
            tum_linkler.extend(linkler)

            # Sayfa limiti kontrolü
            if config.MAKS_SAYFA > 0 and sayfa_no >= config.MAKS_SAYFA:
                log.info(
                    f"Maksimum sayfa sayısına ulaşıldı ({config.MAKS_SAYFA})."
                )
                break

            # Bir sonraki sayfaya geç
            if not self.sonraki_sayfa_var_mi():
                break

            sayfa_no += 1

        # Tekrar eden linkleri temizle
        tum_linkler = list(dict.fromkeys(tum_linkler))
        log.info(
            f"Toplam {len(tum_linkler)} benzersiz ilan linki toplandı."
        )
        return tum_linkler


# ============================================================
# FOTOĞRAF İNDİRİCİ
# ============================================================

class FotografIndirici:
    """
    İlan detay sayfalarından belirtilen sıradaki fotoğrafları
    bulur ve yüksek çözünürlüklü hallerini indirir.
    """

    def __init__(self, tarayici: TarayiciYoneticisi):
        self.tarayici = tarayici
        self.driver = tarayici.driver
        # İndirme istekleri için oturum oluştur
        self.oturum = requests.Session()
        self.oturum.headers.update({
            "User-Agent": self.driver.execute_script(
                "return navigator.userAgent;"
            ),
            "Referer": "https://www.sahibinden.com/",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8",
        })

    def _cerezleri_aktar(self) -> None:
        """
        Selenium tarayıcısındaki çerezleri requests oturumuna aktarır.
        Bu sayede indirme istekleri de aynı oturum gibi görünür.
        """
        try:
            cerezler = self.driver.get_cookies()
            for cerez in cerezler:
                self.oturum.cookies.set(
                    cerez["name"],
                    cerez["value"],
                    domain=cerez.get("domain", ""),
                )
            log.debug(f"{len(cerezler)} çerez aktarıldı.")
        except Exception as hata:
            log.warning(f"Çerez aktarım hatası: {hata}")

    def ilan_fotograflarini_bul(self) -> list[str]:
        """
        Açık olan ilan detay sayfasındaki fotoğraf galerisi URL'lerini çıkarır.
        Yüksek çözünürlüklü versiyonları hedefler.
        """
        foto_urlleri = []
        try:
            # Sayfanın tam yüklenmesini bekle
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            soup = BeautifulSoup(self.driver.page_source, "lxml")

            # Yöntem 1: data-source veya data-original özniteliği olan görseller
            # Sahibinden galeri görselleri genellikle küçük resimlerdir,
            # asıl görselin büyük hali farklı bir attribute'da tutulur.
            foto_seciciler = [
                # Ana galeri görselleri
                'div.classifiedDetailMainPhoto img',
                'div#classifiedDetailPhotos img',
                # Thumbnail galerisi
                'div.classifiedDetailSlideItem img',
                'ul.classifiedDetailPhotoList img',
                # Genel fotoğraf alanları
                'div[class*="photo"] img',
                'div[class*="gallery"] img',
                'img[class*="classifiedPhoto"]',
            ]

            bulunan = set()
            for secici in foto_seciciler:
                gorseller = soup.select(secici)
                for img in gorseller:
                    # Yüksek çözünürlük URL'sini bul
                    url = (
                        img.get("data-source")
                        or img.get("data-original")
                        or img.get("data-src")
                        or img.get("src")
                        or ""
                    )
                    if url and "placeholder" not in url.lower():
                        # Küçük resim URL'sini büyük resim URL'sine çevir
                        url = self._buyuk_resim_url(url)
                        if url not in bulunan:
                            bulunan.add(url)
                            foto_urlleri.append(url)

            # Yöntem 2: JavaScript ile galeri verilerini çek
            if not foto_urlleri:
                try:
                    # Sahibinden galeri verisini JS ile al
                    js_script = """
                        var urls = [];
                        // classifiedImages global değişkeni
                        if (typeof classifiedImages !== 'undefined') {
                            classifiedImages.forEach(function(img) {
                                urls.push(img.url || img.src || '');
                            });
                        }
                        // Alternatif: thumbnail listesinden
                        document.querySelectorAll(
                            'img[src*="sahibinden"], img[data-src*="sahibinden"]'
                        ).forEach(function(img) {
                            var src = img.dataset.source
                                || img.dataset.original
                                || img.dataset.src
                                || img.src;
                            if (src && src.indexOf('placeholder') === -1) {
                                urls.push(src);
                            }
                        });
                        return urls;
                    """
                    js_sonuc = self.driver.execute_script(js_script)
                    if js_sonuc:
                        for url in js_sonuc:
                            if url and url not in bulunan:
                                url = self._buyuk_resim_url(url)
                                bulunan.add(url)
                                foto_urlleri.append(url)
                except Exception as js_hata:
                    log.debug(f"JS galeri çekimi başarısız: {js_hata}")

            log.info(f"İlanda {len(foto_urlleri)} fotoğraf bulundu.")

        except Exception as hata:
            log.error(f"Fotoğraf URL'leri çıkarılırken hata: {hata}")

        return foto_urlleri

    @staticmethod
    def _buyuk_resim_url(url: str) -> str:
        """
        Sahibinden küçük resim (thumbnail) URL'sini yüksek çözünürlüklü
        versiyonuna dönüştürür.
        Örn: .../_thmb_img/... -> .../_img/...
             ...ilanNo_s.jpg  -> ...ilanNo.jpg
        """
        # Tam URL'ye çevir
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = "https://www.sahibinden.com" + url

        # Thumbnail kalıplarını büyük resme çevir
        donusumler = [
            ("_thmb_img", "_img"),
            ("_thmb/", "/"),
            ("/lt_", "/"),
            ("_s.jpg", ".jpg"),
            ("_s.jpeg", ".jpeg"),
            ("_s.png", ".png"),
            ("/x90/", "/x800/"),
            ("/x120/", "/x800/"),
            ("/x150/", "/x800/"),
            ("/x240/", "/x800/"),
        ]
        for eski, yeni in donusumler:
            if eski in url:
                url = url.replace(eski, yeni)

        return url

    def gorsel_indir(self, url: str, kayit_yolu: str) -> bool:
        """
        Tek bir görseli belirtilen yola indirir.
        Yeniden deneme mekanizması içerir.
        """
        for deneme in range(config.YENIDEN_DENEME):
            try:
                yanit = self.oturum.get(url, timeout=20, stream=True)
                yanit.raise_for_status()

                # İçerik tipi kontrolü (gerçekten bir görsel mi?)
                icerik_tipi = yanit.headers.get("Content-Type", "")
                if "image" not in icerik_tipi and "octet-stream" not in icerik_tipi:
                    log.warning(f"Görsel değil ({icerik_tipi}): {url}")
                    return False

                # Dosyayı kaydet
                with open(kayit_yolu, "wb") as dosya:
                    for parca in yanit.iter_content(chunk_size=8192):
                        dosya.write(parca)

                # Dosya boyutu kontrolü (çok küçükse muhtemelen hata görseli)
                boyut = os.path.getsize(kayit_yolu)
                if boyut < 5000:  # 5KB'den küçükse şüpheli
                    log.warning(
                        f"Görsel çok küçük ({boyut} byte), atlanıyor: {url}"
                    )
                    os.remove(kayit_yolu)
                    return False

                log.info(
                    f"İndirildi ({boyut / 1024:.1f} KB): "
                    f"{os.path.basename(kayit_yolu)}"
                )
                return True

            except requests.exceptions.RequestException as hata:
                log.warning(
                    f"İndirme hatası (deneme {deneme + 1}/"
                    f"{config.YENIDEN_DENEME}): {hata}"
                )
                if deneme < config.YENIDEN_DENEME - 1:
                    rastgele_bekle(2, 5)

        log.error(f"Görsel indirilemedi: {url}")
        return False

    def ilan_fotograflarini_indir(
        self, ilan_url: str, kategori_klasoru: str
    ) -> int:
        """
        Bir ilanın detay sayfasına gidip hedeflenen fotoğrafları indirir.
        Dönen değer: indirilen fotoğraf sayısı.
        """
        indirilen = 0
        ilan_no = ilan_no_cikar(ilan_url)

        try:
            # İlan detay sayfasına git
            if not self.tarayici.sayfaya_git(ilan_url):
                log.warning(f"İlan sayfası açılamadı: {ilan_url}")
                return 0

            rastgele_bekle(config.ILAN_MIN_BEKLEME, config.ILAN_MAKS_BEKLEME)

            # Çerezleri requests oturumuna aktar
            self._cerezleri_aktar()

            # Fotoğraf URL'lerini bul
            foto_urlleri = self.ilan_fotograflarini_bul()

            if not foto_urlleri:
                log.warning(f"İlanda fotoğraf bulunamadı: {ilan_no}")
                return 0

            # Hedeflenen indekslerdeki fotoğrafları indir
            for indeks in config.HEDEF_FOTO_INDEKSLERI:
                if indeks >= len(foto_urlleri):
                    log.debug(
                        f"İlan {ilan_no}: Fotoğraf indeksi {indeks + 1} yok "
                        f"(toplam {len(foto_urlleri)} fotoğraf)."
                    )
                    continue

                foto_url = foto_urlleri[indeks]

                # Dosya uzantısını belirle
                uzanti = ".jpg"
                if ".png" in foto_url.lower():
                    uzanti = ".png"
                elif ".webp" in foto_url.lower():
                    uzanti = ".webp"

                # Benzersiz dosya adı: ilanNo_sıra.uzantı
                dosya_adi = f"{ilan_no}_{indeks + 1}{uzanti}"
                kayit_yolu = os.path.join(kategori_klasoru, dosya_adi)

                # Zaten indirilmiş mi kontrol et
                if os.path.exists(kayit_yolu):
                    log.info(f"Zaten mevcut, atlanıyor: {dosya_adi}")
                    indirilen += 1
                    continue

                # Görseli indir
                if self.gorsel_indir(foto_url, kayit_yolu):
                    indirilen += 1

                # İndirmeler arası kısa bekleme
                rastgele_bekle(
                    config.INDIRME_MIN_BEKLEME, config.INDIRME_MAKS_BEKLEME
                )

        except Exception as hata:
            log.error(f"İlan işlenirken hata (ilan: {ilan_no}): {hata}")

        return indirilen


# ============================================================
# ANA ORKESTRATÖR
# ============================================================

class SahibindenScraper:
    """
    Tüm bileşenleri bir araya getiren ana sınıf.
    Kategori gezintisi, ilan toplama ve fotoğraf indirme
    işlemlerini koordine eder.
    """

    def __init__(self):
        self.tarayici = TarayiciYoneticisi()
        self.toplayici = None
        self.indirici = None
        self.istatistik = {
            "toplam_ilan": 0,
            "islenen_ilan": 0,
            "indirilen_gorsel": 0,
            "hatali_ilan": 0,
        }

    def baslat(self) -> None:
        """Tüm bileşenleri başlatır ve ana dataset klasörünü oluşturur."""
        # Ana dataset klasörünü oluştur
        klasor_olustur(config.DATASET_DIR)
        log.info(f"Dataset dizini: {config.DATASET_DIR}")

        # Tarayıcıyı başlat
        self.tarayici.baslat()
        self.toplayici = IlanToplayici(self.tarayici)
        self.indirici = FotografIndirici(self.tarayici)

    def kategori_isle(self, kategori_adi: str, kategori_url: str) -> None:
        """
        Tek bir kategoriyi baştan sona işler:
        1) Kategori sayfalarını tara, ilan linklerini topla
        2) Her ilanın detay sayfasına gir, hedef fotoğrafları indir
        """
        log.info("=" * 60)
        log.info(f"KATEGORİ: {kategori_adi.upper()}")
        log.info(f"URL: {kategori_url}")
        log.info("=" * 60)

        # Kategori alt klasörünü oluştur
        kategori_klasoru = os.path.join(config.DATASET_DIR, kategori_adi)
        klasor_olustur(kategori_klasoru)

        # İlan linklerini topla
        ilan_linkleri = self.toplayici.kategori_ilanlarini_topla(kategori_url)
        self.istatistik["toplam_ilan"] += len(ilan_linkleri)

        if not ilan_linkleri:
            log.warning(f"{kategori_adi} kategorisinde ilan bulunamadı.")
            return

        # Her ilan için fotoğrafları indir
        for sira, ilan_url in enumerate(ilan_linkleri, start=1):
            log.info(
                f"\n[{sira}/{len(ilan_linkleri)}] İlan işleniyor: {ilan_url}"
            )

            try:
                indirilen = self.indirici.ilan_fotograflarini_indir(
                    ilan_url, kategori_klasoru
                )
                self.istatistik["indirilen_gorsel"] += indirilen
                self.istatistik["islenen_ilan"] += 1

            except Exception as hata:
                log.error(f"İlan hatası: {hata}")
                self.istatistik["hatali_ilan"] += 1

            # İlanlar arası rastgele bekleme (bot tespitini engellemek için)
            rastgele_bekle(config.MIN_BEKLEME, config.MAKS_BEKLEME)

    def calistir(self) -> None:
        """
        Ana çalıştırma fonksiyonu. Tüm kategorileri sırayla işler.
        Program sonunda özet istatistikleri gösterir.
        """
        log.info("=" * 60)
        log.info("SAHİBİNDEN TİCARİ ARAÇ FOTOĞRAF SCRAPER BAŞLADI")
        log.info("=" * 60)

        baslangic = time.time()

        try:
            self.baslat()

            for kategori_adi, kategori_url in config.KATEGORILER.items():
                try:
                    self.kategori_isle(kategori_adi, kategori_url)
                except Exception as hata:
                    log.error(
                        f"Kategori hatası ({kategori_adi}): {hata}"
                    )
                    # Bir kategori başarısız olsa bile diğerlerine devam et
                    continue

        except KeyboardInterrupt:
            log.info("\nKullanıcı tarafından durduruldu (Ctrl+C).")
        except Exception as hata:
            log.error(f"Kritik hata: {hata}", exc_info=True)
        finally:
            # Tarayıcıyı kapat
            self.tarayici.kapat()

            # Geçen süre
            gecen = time.time() - baslangic
            dakika = int(gecen // 60)
            saniye = int(gecen % 60)

            # Özet istatistikler
            log.info("\n" + "=" * 60)
            log.info("ÖZET İSTATİSTİKLER")
            log.info("=" * 60)
            log.info(f"Toplam ilan sayısı    : {self.istatistik['toplam_ilan']}")
            log.info(f"İşlenen ilan sayısı   : {self.istatistik['islenen_ilan']}")
            log.info(f"İndirilen görsel      : {self.istatistik['indirilen_gorsel']}")
            log.info(f"Hatalı ilan sayısı    : {self.istatistik['hatali_ilan']}")
            log.info(f"Toplam süre           : {dakika} dk {saniye} sn")
            log.info("=" * 60)


# ============================================================
# GİRİŞ NOKTASI
# ============================================================

if __name__ == "__main__":
    scraper = SahibindenScraper()
    scraper.calistir()
