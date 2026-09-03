# MJD Kupi Auth Testing

Use the public backend URL from `frontend/.env`.

1. `POST /api/auth/login` with `{ "email": "manager@mjd-kupi.local", "password": "MjdKupi#2026" }` and save cookies.
2. `GET /api/auth/me` with the saved cookies; verify role is `Merchant Admin`.
3. Vendor and Kasir roles must receive 403 from protected outlet creation.
4. `POST /api/auth/logout` clears the session cookies.

Demo password is for local testing only and must be changed before production use.