import asyncio, sys
sys.stdout.reconfigure(encoding='utf-8')
from main import _scrape_all_pages, associate_persons_with_roles

async def main():
    for url, expected_email, expected_meno in [
        ("https://www.stavbaeu.cz/",               "info@stavbaeu.cz", None),
        ("https://www.profesionalnikosmetika.cz/",  "777",             "Jindrová"),
    ]:
        domain = url.split("//")[1].split("/")[0].replace("www.", "")
        r = await _scrape_all_pages(url)
        text = r.get("text", "") if isinstance(r, dict) else r[0]
        osoby = associate_persons_with_roles(text)

        email_ok = expected_email.lower() in text.lower() if expected_email else True
        meno_ok = any(expected_meno.lower() in o.get("meno", "").lower()
                      for o in osoby) if expected_meno else True

        status = "OK" if email_ok and meno_ok else "FAIL"
        print(f"{status} {domain}")
        print(f"   email ok: {email_ok} | meno ok: {meno_ok}")
        top2 = [(o.get("meno"), o.get("rola")) for o in osoby[:2]]
        print(f"   osoby: {top2}")

asyncio.run(main())
