import sys
sys.stdout.reconfigure(encoding='utf-8')
from main import associate_persons_with_roles

CASES = [
    # Tieto NESMÚ byť nájdené
    ("Google Tag Manager noscript gtm.js dataLayer", False, "Tag Manager"),
    ("Kupujúci podnikateľ je povinný uhradiť cenu", False, "Kupujúci"),
    ("Fox Specialist Tackle rybárske nástrahy Fox", False, "Fox"),
    ("predávajúci spotrebiteľ zmluvná strana", False, "predávajúci"),
    # Tieto MUSIA byť nájdené
    ("Zodpovedný vedúci: Ing. Martin Mikuľák +421 910 621 045", True, "Mikuľák"),
    ("konateľ spoločnosti Ján Lamanec, IČO: 36515388", True, "Lamanec"),
    ("predávajúcim je Daša Kozmérová so sídlom Bratislava", True, "Kozmérová"),
    ("CEO a zakladateľ Peter Chodelka info@blendea.sk", True, "Chodelka"),
]

ok_count = 0
for text, should_find, fragment in CASES:
    osoby = associate_persons_with_roles(text)
    found = any(fragment.lower() in o.get('meno', '').lower() for o in osoby)
    ok = found == should_find
    if ok:
        ok_count += 1
    marker = 'OK' if ok else 'FAIL'
    top = osoby[0] if osoby else {}
    print(f"{marker} {'NAJST' if should_find else 'SKIP'} '{fragment}': found={found} | top={top.get('meno', '')}|{top.get('rola', '')}")

print(f"\n{ok_count}/8 testov preslo")
