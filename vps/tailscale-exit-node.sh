#!/usr/bin/env bash
# Hostinger VPS'i Tailscale "exit node" (telefon icin VPN cikisi) yapar ve durumu kontrol eder.
# Kullanim (VPS uzerinde, root olarak):
#   bash tailscale-exit-node.sh check   -> sadece kontrol
#   bash tailscale-exit-node.sh setup   -> kurulum + kontrol
set -euo pipefail

MODE="${1:-check}"

ok()   { echo "  [OK]   $*"; }
fail() { echo "  [HATA] $*"; }

check() {
  echo "== Tailscale kurulu mu?"
  if command -v tailscale >/dev/null; then ok "$(tailscale version | head -1)"; else fail "tailscale yok -> setup calistir"; return; fi

  echo "== tailscaled servisi"
  systemctl is-active --quiet tailscaled && ok "aktif" || fail "calismiyor: systemctl enable --now tailscaled"

  echo "== Oturum / IP"
  tailscale ip -4 2>/dev/null && ok "bagli" || fail "giris yapilmamis: tailscale up"

  echo "== IP forwarding"
  [ "$(sysctl -n net.ipv4.ip_forward)" = "1" ] && ok "IPv4 forward=1" || fail "IPv4 forward kapali"
  [ "$(sysctl -n net.ipv6.conf.all.forwarding)" = "1" ] && ok "IPv6 forward=1" || fail "IPv6 forward kapali"

  echo "== Exit node ilani"
  if tailscale debug prefs 2>/dev/null | grep -q '"0.0.0.0/0"'; then
    ok "exit node ilan edilmis (admin panelde onaylandigindan emin ol)"
  else
    fail "exit node ilan edilmemis: tailscale set --advertise-exit-node"
  fi

  echo "== Firewall (UFW)"
  if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    ufw status | grep -q tailscale0 && ok "tailscale0 izinli" || fail "UFW aktif ama tailscale0 izinli degil: ufw allow in on tailscale0"
    grep -q '^DEFAULT_FORWARD_POLICY="ACCEPT"' /etc/default/ufw && ok "UFW forward ACCEPT" \
      || fail "UFW forward DROP -> /etc/default/ufw: DEFAULT_FORWARD_POLICY=\"ACCEPT\" ; ufw reload"
  else
    ok "UFW kapali/yok"
  fi

  echo "== UDP 41641 (dogrudan baglanti icin, opsiyonel)"
  tailscale netcheck 2>/dev/null | grep -E "UDP|Nearest DERP" || true

  echo "== Bagli cihazlar"
  tailscale status || true
}

setup() {
  if ! command -v tailscale >/dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
  fi
  systemctl enable --now tailscaled

  cat >/etc/sysctl.d/99-tailscale.conf <<'EOF'
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
EOF
  sysctl -p /etc/sysctl.d/99-tailscale.conf

  # UDP GRO ayari (Tailscale'in Linux exit node onerisi, hiz icin)
  NETDEV=$(ip -o route get 8.8.8.8 | awk '{for(i=1;i<=NF;i++) if($i=="dev") print $(i+1)}')
  command -v ethtool >/dev/null || apt-get install -y ethtool
  ethtool -K "$NETDEV" rx-udp-gro-forwarding on rx-gro-list off || true

  if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    ufw allow in on tailscale0
    ufw allow 41641/udp
    sed -i 's/^DEFAULT_FORWARD_POLICY=.*/DEFAULT_FORWARD_POLICY="ACCEPT"/' /etc/default/ufw
    ufw reload
  fi

  # Giris yapilmamissa link verir; yapilmissa sadece ayari gunceller
  if tailscale ip -4 >/dev/null 2>&1; then
    tailscale set --advertise-exit-node
  else
    tailscale up --advertise-exit-node --ssh
  fi

  echo
  echo ">> SON ADIM: https://login.tailscale.com/admin/machines -> VPS satiri -> '...' ->"
  echo "   'Edit route settings' -> 'Use as exit node' kutusunu isaretle."
  echo ">> Telefonda: Tailscale app -> Exit Node -> VPS'i sec."
  echo
  check
}

case "$MODE" in
  check) check ;;
  setup) setup ;;
  *) echo "Kullanim: $0 {check|setup}"; exit 1 ;;
esac
