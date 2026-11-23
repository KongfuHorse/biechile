#!/bin/sh
# biechile NAS connectivity test. Read-only: it only opens web pages and prints results.
# It changes nothing on the NAS except a temporary folder in /tmp, which it deletes at the end.
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
T=/tmp/biechile-nettest; mkdir -p $T
echo "===== BIECHILE NETTEST START ====="
echo "time: $(date '+%F %T %z')"
echo "system: $(uname -srm)"
echo "cpu: $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2)"
echo "mem: $(free -m 2>/dev/null | awk '/Mem:/{print $2" MB total, "$7" MB available"}')"
echo "disk: $(df -h / 2>/dev/null | awk 'NR==2{print $4" free on /"}')"
for c in curl wget python3 docker timeout git; do
  if command -v $c >/dev/null 2>&1; then echo "have $c: yes"; else echo "have $c: NO"; fi
done
v=$(docker version --format '{{.Server.Version}}' 2>/dev/null); echo "docker server: ${v:-cannot talk to docker as this user (try sudo)}"
echo "--- websites (code / seconds / bytes / note) ---"
n=0
check() {
  n=$((n+1)); f=$T/p$n
  r=$(curl -s -L -k -A "$UA" -o $f -m 25 -w "%{http_code} %{time_total} %{size_download}" "$2" 2>/dev/null)
  [ -z "$r" ] && r="000 - 0"
  note=""
  grep -qi "\$_ts\|412 Precondition" $f 2>/dev/null && note="JS-challenge"
  grep -qi "accessrestriction\|暂不支持访问" $f 2>/dev/null && note="geo-block"
  grep -qi "验证码\|captcha\|滑块" $f 2>/dev/null && note="$note captcha"
  case "$r" in 000*) note="no-connection";; esac
  printf "%-12s %-34s %s %s\n" "$1" "$(echo $2 | cut -d/ -f3)" "$r" "$note"
}
check cloud  "https://arfagbvdcooyudfyyupb.supabase.co/rest/v1/"
check cloud  "https://github.com/"
check cloud  "https://raw.githubusercontent.com/github/gitignore/main/README.md"
check cloud  "https://ghcr.io/v2/"
check cloud  "https://registry-1.docker.io/v2/"
check cloud  "https://api.anthropic.com/"
check cloud  "https://pypi.org/simple/requests/"
check mirror "https://mirrors.aliyun.com/pypi/simple/requests/"
check mirror "https://registry.cn-hangzhou.aliyuncs.com/v2/"
check site   "https://biechile.com/"
check cn-food "https://spcjsac.gsxt.gov.cn/"
check cn-samr "https://www.samr.gov.cn/"
check cn-recall "https://dpac.samr.gov.cn/"
check cn-nmpa "https://www.nmpa.gov.cn/"
check cn-nmpa "https://datasearch.nmpa.gov.cn/datasearch/home-index.html"
check cn-tm   "https://sbj.cnipa.gov.cn/sbj/index.html"
check cn-gsxt "https://www.gsxt.gov.cn/index.html"
check cn-prov "https://scjgj.sh.gov.cn/"
check cn-prov "https://amr.gd.gov.cn/"
check cn-city "https://amr.sz.gov.cn/"
check cn-biz  "https://aiqicha.baidu.com/"
echo "--- docker pull test (up to 90 s) ---"
if command -v docker >/dev/null 2>&1; then
  s=$(date +%s)
  if timeout 90 docker pull -q hello-world >/dev/null 2>&1; then echo "docker hub pull: ok in $(( $(date +%s)-s )) s"
  else echo "docker hub pull: FAILED or too slow"; fi
  docker image rm hello-world >/dev/null 2>&1
else echo "docker not found for this user (try with sudo)"; fi
rm -rf $T
echo "===== BIECHILE NETTEST END ====="
