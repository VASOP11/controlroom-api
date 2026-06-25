"""Debug ORSR lookup pre SK shops"""
from registry_lookup import lookup_orsr

tests = [
    ("51747391", "minilove.sk"),
    ("48288713", "lavanda.sk"),
    ("55498787", "elmishop.sk"),
    ("46168931", "isexshop.sk"),
    ("46359338", "sedooz.sk"),
]

print("\n=== ORSR LOOKUP DEBUG ===\n")

for ico, shop in tests:
    print(f"--- {shop} (ICO: {ico}) ---")
    r = lookup_orsr(ico)
    found = r.get("found")
    meno = r.get("obchodne_meno")
    konatelia = r.get("konatelia", [])
    error = r.get("error")

    print(f"  found: {found}")
    print(f"  obchodne_meno: {meno}")
    print(f"  konatelia ({len(konatelia)}):")
    if konatelia:
        for k in konatelia:
            print(f"    {k.get('meno')} ({k.get('funkcia')})")
    else:
        print("    PRAZDNE!")
    if error:
        print(f"  error: {error}")
    print()
