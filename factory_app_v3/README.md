# factory_app_v3 (Production-only)

This is the clean rewrite of the legacy `factory_app` focusing on **production + QC** only.

## Scope

Included domains:
- Pre-expansion
- Block making
- Cutting / wire cutting
- Boxing
- PR16
- Moulding (moulded cornice + moulded boxing)
- Extrusion
- Quality control

Explicitly excluded for now:
- Attendance

## Status

Scaffolded application package with production-only blueprint registration. Next step is migrating one domain at a time from the legacy app into `app/domains/*`.
