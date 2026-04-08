# Kurulum ve Anti-Bot Katmanları Rehberi

## Hızlı Başlangıç

```bash
# 1. Bağımlılıkları kur
pip install -r requirements.txt

# 2. Botu çalıştır (proxy ve çerez dosyası olmadan da çalışır)
python scraper.py
```

---

## 5 Anti-Bot Katmanı

### Katman 1: Proxy Rotasyonu

Bot, `proxies.txt` dosyasından proxy listesi okur. Dosya yoksa doğrudan bağlantı kullanılır.

**Proxy dosyası oluşturma:**

Proje dizininde `proxies.txt` adlı bir dosya oluşturun. Her satıra bir proxy yazın:

```
# HTTP proxy (kullanıcı adı / şifre ile)
http://kullanici:sifre@1.2.3.4:8080

# SOCKS5 proxy
socks5://kullanici:sifre@5.6.7.8:1080

# Basit format (user:pass olmadan)
9.10.11.12:3128

# Alternatif format: host:port:user:pass
1.2.3.4:8080:kullanici:sifre
```

**Proxy temin kaynakları:**
- **4G/Mobil proxy** (en etkili): Bright Data, Proxy-Seller, Soax
- **Residential proxy**: Smartproxy, Oxylabs
- **Datacenter proxy** (en ucuz): Webshare, ProxyRack

**Ayarlar** (`config.py`):
- `PROXY_ROTASYON_ARALIGI = 5` — Her 5 istekte proxy değişir

---

### Katman 2: Anti-Detect Tarayıcı

`undetected-chromedriver` otomatik olarak temel bot tespitini atlatır. Ek olarak:

- **Canvas parmak izi**: Her oturumda piksel verileri hafifçe değiştirilir
- **WebGL renderer/vendor**: Intel UHD Graphics 630 olarak gösterilir
- **navigator.plugins**: Gerçek Chrome plugin listesi döndürülür
- **navigator.webdriver**: `undefined` olarak maskelenir

Bu katman otomatik çalışır, ek yapılandırma gerekmez.

---

### Katman 3: TLS/SSL Parmak İzi Gizleme

Görsel indirme istekleri `curl_cffi` kütüphanesi ile yapılır.
Standart `requests` kütüphanesi yerine `curl_cffi` kullanılarak,
HTTP isteklerinin TLS parmak izi gerçek bir Chrome tarayıcısıyla
aynı görünür. Bu, Akamai/Cloudflare gibi servislerin
"bu istek tarayıcıdan mı yoksa bottan mı geliyor?" kontrolünü atlatır.

Bu katman otomatik çalışır. `curl_cffi` yüklü olduğundan emin olun:

```bash
pip install curl_cffi
```

---

### Katman 4: Çerez Isıtma ve Yönetimi

Bot, çerezleri `cookies.json` dosyasına kaydeder ve sonraki çalıştırmalarda yükler.

**İlk çalıştırma akışı:**
1. Bot Chrome'u açar ve sahibinden.com'a gider
2. Eğer CAPTCHA/engel çıkarsa terminalde `ENTER'a basın` mesajı görünür
3. Chrome penceresinde CAPTCHA'yı çözün
4. Terminale dönüp ENTER'a basın
5. Çerezler otomatik olarak `cookies.json`'a kaydedilir

**Sonraki çalıştırmalar:**
- `cookies.json` varsa çerezler otomatik yüklenir
- Sahibinden sizi "tanır", CAPTCHA gelmesi daha az olasıdır

**Manuel çerez oluşturma (opsiyonel):**
1. Normal Chrome'da sahibinden.com'a gidin
2. F12 > Application > Cookies > sahibinden.com
3. Tüm çerezleri JSON formatında kopyalayın
4. `cookies.json` dosyasına yapıştırın

---

### Katman 5: İnsanlaştırılmış DOM Etkileşimi

Eski basit `time.sleep()` + doğrusal fare hareketleri yerine:

- **Bézier eğrili fare hareketi**: Fare, iki kontrol noktalı kübik Bézier eğrisi boyunca hareket eder. Akamai'nin doğrusal fare hareketlerini tespit eden algoritmasını atlatır.

- **Organik scroll**: Düzensiz hızda, duraklamalı, bazen yukarı geri dönen scroll. "İçerik okuyormuş gibi" uzun duraklamalar.

- **İnsansı tıklama gecikmesi**: Log-normal dağılımlı tepki süresi (gerçek insan tepki süresi dağılımına yakın).

**Ayarlar** (`config.py`):
```python
BEZIER_ADIM_SAYISI = 25     # Fare hareket adım sayısı
SCROLL_MIN_ADIM = 3          # Min scroll adımı
SCROLL_MAKS_ADIM = 7         # Maks scroll adımı
```

---

## Dosya Yapısı

```
web_bot/
├── config.py          # Tüm ayarlar
├── scraper.py         # Ana bot kodu (5 katman entegre)
├── requirements.txt   # Python bağımlılıkları
├── proxies.txt        # Proxy listesi (opsiyonel, oluşturulacak)
├── cookies.json       # Çerez deposu (otomatik oluşur)
├── chrome_profil/     # Kalıcı Chrome profili (otomatik oluşur)
├── scraper.log        # Çalışma logları (otomatik oluşur)
├── KURULUM.md         # Bu dosya
├── README.md          # Proje açıklaması
└── dataset/           # İndirilen görseller (otomatik oluşur)
    ├── kamyon_kamyonet/
    ├── minibus_midibus/
    ├── cekici/
    └── oto_kurtarici/
```

---

## Sorun Giderme

| Sorun | Çözüm |
|-------|-------|
| "Olağan dışı erişim" sürekli çıkıyor | Proxy kullanın veya `COOLDOWN_ILAN_SAYISI`'nı 3'e düşürün |
| ChromeDriver versiyon hatası | `config.py` yok ama `scraper.py`'de `version_main=146`'yı Chrome versiyonunuza göre değiştirin |
| Görsel indirme başarısız | `curl_cffi` kurulu mu kontrol edin: `pip install curl_cffi` |
| CAPTCHA çözülmüyor | Chrome penceresinde çözün, terminalde ENTER'a basın |
| IP engeli (5 dk bekleme) | Normal — bot otomatik bekler. Proxy ile bu sorun azalır |
