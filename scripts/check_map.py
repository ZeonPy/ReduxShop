from app.countries import COUNTRIES
from app.smsfast_countries import provider_country_id, SMSFAST_COUNTRIES

missing = []
for country in COUNTRIES:
    if provider_country_id(country.name) is None:
        missing.append(country.name)

print("catalog", len(COUNTRIES), "missing", len(missing))
print(missing)
used = {provider_country_id(c.name) for c in COUNTRIES}
used.discard(None)
all_ids = {api_id for api_id, _ in SMSFAST_COUNTRIES}
print("provider entries", len(SMSFAST_COUNTRIES), "used", len(used))
print("unused", sorted(all_ids - used))
