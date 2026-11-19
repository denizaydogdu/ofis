#!/bin/bash
# One-command setup (README "Kurulum ve ilk çalıştırma" / "Install and first run", the owner 2026-11-19): writes
# ofis.json from ofis.example.json, creates the folders it points at, and starts the server. Interactive; run it
# from anywhere — it moves to its own folder first. An existing ofis.json is personal and never overwritten: the
# script then only creates missing folders and starts the server. bash 3.2 (macOS) compatible.
#
# Kurulum:  bash kurulum.sh
#
# Sorular (boş cevap = parantez içindeki varsayılan):
#   1. Obsidian kasandaki OFIS klasörü (vault_ofis)
#   2. Ar-Ge çalışma klasörü (projects.arge.path)
#   3. Ofisin sana hitap edeceği ad (sahip_adi)
#   4. Sayfada görünen ofis adı (ofis_adi)
# Sonunda: klasörleri Claude Code'a güvenilir yapmayı hatırlatır ve sunucuyu başlatır.

set -u

KLASOR="$(cd "$(dirname "$0")" && pwd)"
cd "$KLASOR"

ac() { printf '%s' "$1" | sed "s|^~|$HOME|"; }   # ~/... -> $HOME/...
sor() {  # sor '<soru (varsayılan)>' <varsayılan> -> cevap; boş ya da yalnız boşluk = varsayılan (review finding 2)
  local cevap
  printf '%s' "$1" >&2
  read -r cevap || cevap=""
  cevap="$(printf '%s' "$cevap" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  printf '%s' "${cevap:-$2}"
}

echo "Ofis kurulumu"
echo "-------------"

# --- gereksinimler ---
if ! command -v python3 >/dev/null 2>&1; then
  echo "HATA: python3 bulunamadı. Python 3.9 ya da üstü gerekli (README: Gereksinimler)."
  exit 1
fi
command -v claude >/dev/null 2>&1 || echo "UYARI: 'claude' komutu PATH'te değil. CEO oturumu ve işler başlamaz;"
command -v claude >/dev/null 2>&1 || echo "         Claude Code'u kurup 'claude' komutunu PATH'e ekle (README: Gereksinimler)."

# --- ofis.json ---
if [ -f ofis.json ]; then
  echo
  echo "ofis.json zaten var — ayarların duruyor, üzerine yazılmaz."
else
  echo "ofis.json yok; ofis.example.json'dan oluşturulacak."
  echo "Yolları şimdi soracağım. Boş bırakırsan parantez içindeki varsayılan kullanılır."
  echo
  KASA="$(sor 'Obsidian kasandaki OFIS klasörü (~/Documents/Obsidian Vault/OFIS): ' "$HOME/Documents/Obsidian Vault/OFIS")"
  ARGE="$(sor 'Ar-Ge çalışma klasörü (~/ofis-arge): ' "$HOME/ofis-arge")"
  SAHIP="$(sor 'Ofisin sana hitap edeceği ad (Sahip): ' 'Sahip')"
  AD="$(sor 'Sayfada görünen ofis adı (Ofis): ' 'Ofis')"

  KASA="$(ac "$KASA")"
  ARGE="$(ac "$ARGE")"
  if python3 - "$KASA" "$ARGE" "$SAHIP" "$AD" <<'PY'
import json, sys
kasa, arge, sahip, ad = sys.argv[1:5]
with open("ofis.example.json", encoding="utf-8") as f:
    cfg = json.load(f)
cfg["vault_ofis"] = kasa
cfg["projects"]["arge"]["path"] = arge
cfg["sahip_adi"] = sahip
cfg["ofis_adi"] = ad
with open("ofis.json", "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
    f.write("\n")
PY
  then
    echo "ofis.json yazıldı (ofis.example.json'un geri kalanı olduğu gibi duruyor)."
  else
    echo "HATA: ofis.json yazılamadı."
    exit 1
  fi
fi

# --- klasörler ---
YOLLAR="$(mktemp "${TMPDIR:-/tmp}/ofis-kurulum.XXXXXX")"
if python3 - "$YOLLAR" <<'PY'
import json, sys
try:
    with open("ofis.json", encoding="utf-8") as f:
        cfg = json.load(f)
except Exception as e:
    print(f"HATA: ofis.json okunamadı ({type(e).__name__}: {e})", file=sys.stderr)
    sys.exit(1)
paths = [cfg.get("vault_ofis", "")]
projects = cfg.get("projects") or {}
if isinstance(projects.get("arge"), dict):
    paths.append(projects["arge"].get("path", ""))
for line in paths:
    if line:
        print(line.replace("~", __import__("os").path.expanduser("~")))
PY
then
  while IFS= read -r yol; do
    [ -d "$yol" ] && continue
    if mkdir -p -- "$yol" 2>/dev/null; then
      echo "Klasör oluşturuldu: $yol"
    else
      echo "UYARI: klasör oluşturulamadı: $yol (elle oluştur: mkdir -p \"$yol\")"
    fi
  done < "$YOLLAR"
fi
rm -f "$YOLLAR"

# --- Claude Code güveni ---
echo
echo "Son bir elle yapılan adım: klasörleri Claude Code'a güvenilir tanıtmak."
echo "Claude Code güvenmediği bir klasörde oturum başlatmaz; her klasörde bir kez:"
echo
echo "  cd \"$KLASOR\" && claude     # bu depo (CEO burada çalışır), sonra çık"
if [ -f ofis.json ]; then
  ARGE_YOL="$(python3 -c 'import json,os; c=json.load(open("ofis.json")); print((c.get("projects",{}).get("arge") or {}).get("path","").replace("~", os.path.expanduser("~")))')"
  [ -n "$ARGE_YOL" ] && echo "  cd \"$ARGE_YOL\" && claude    # Ar-Ge klasörü, sonra çık"
fi
echo
echo "Güvenilmeyen bir klasörün işi kaybolmaz: sırada bekler, onay verince başlar."
echo "Sonradan eklediğin her proje klasörü için de aynısı geçerli (Ayarlar sekmesi komutu gösterir)."

# --- sunucu ---
echo
echo "Sunucu nasıl başlasın?"
echo "  1) Şimdi, bu terminalde   (kapatmak için Ctrl-C)"
echo "  2) Oturum açılışında       (macOS launchd; günlüğü ~/Library/Logs/ofis/server.log)"
echo "  3) Başlatma — kendim başlatacağım"
SECIM="$(sor 'Seçim (1): ' '1')"
case "$SECIM" in
  2)
    echo
    if python3 bin/autostart.py install; then
      python3 bin/autostart.py status
      echo
      echo "Sunucu oturum açılışında başlar; sayfa: http://127.0.0.1:8800"
    else
      echo "UYARI: otomatik başlatma kurulamadı; sunucuyu kendin başlat: python3 bin/server.py"
    fi
    ;;
  3)
    echo
    echo "Kurulum bitti. Sunucuyu başlatmak için:  python3 bin/server.py"
    ;;
  *)
    echo
    exec python3 bin/server.py
    ;;
esac
